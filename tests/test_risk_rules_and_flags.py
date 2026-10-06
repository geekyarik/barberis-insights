import datetime as dt

from conftest import client, visit

from barberis_insights.clients.profile import rebuild_profiles
from barberis_insights.clients.risk import risk_list
from sqlalchemy import select

from barberis_insights.db.models import Client, ClientProfile
from barberis_insights.metrics import Dataset

ASOF = dt.date(2026, 10, 1)
D = lambda s: dt.date.fromisoformat(s)


def regular(s, cid, last, every=28, n=6, barber=1, cost=800):
    """n visits every `every` days ending on `last`."""
    for i in range(n):
        visit(s, cid, D(last) - dt.timedelta(days=every * (n - 1 - i)), barber, cost)


def seg(s, cid):
    return s.get(ClientProfile, cid).segment


def build(s):
    s.flush()
    rebuild_profiles(s, Dataset.load(s), ASOF)


def test_segments(s):
    regular(s, 10, "2026-09-20")            # 11 days ago, gap 28 → active
    regular(s, 11, "2026-08-25")            # 37 days > gap 28, < max(45, 42) → slipping
    regular(s, 12, "2026-07-20")            # 73 days > 45 → overdue
    regular(s, 13, "2026-02-01")            # > 180 → lapsed
    visit(s, 14, "2026-06-01")              # one visit, 122 days → one_time
    regular(s, 15, "2026-09-25", n=5); visit(s, 15, "2026-09-28", barber=2)  # last visit with another barber → switched
    build(s)
    assert [seg(s, c) for c in (10, 11, 12, 13, 14, 15)] == ["active", "slipping", "overdue", "lapsed", "one_time", "switched"]


def test_eligibility_excludes_consent_and_dnc(s):
    for cid in (20, 21, 22, 23):
        regular(s, cid, "2026-07-20")
    client(s, 20); client(s, 21, data_processing_allowed=False); client(s, 22, do_not_contact=True); client(s, 23, phone=None)
    build(s)
    eligible = [r["client_id"] for r in risk_list(s, ("overdue",))]
    assert eligible == [20]
    reasons = {r["client_id"]: r["ineligible_reasons"] for r in risk_list(s, ("overdue",), include_ineligible=True)}
    assert reasons[21] == ["no_consent"] and reasons[22] == ["dnc"] and reasons[23] == ["no_phone"]


def _one_case(s, cid=30):
    regular(s, cid, "2026-07-20"); client(s, cid)
    build(s)
    [case] = service.propose(s, [r for r in risk_list(s, ("overdue",)) if r["client_id"] == cid])
    return case


# ------------------------------------------------------------------ the offer rule (docs/OFFERS.md)
def _facts(**kw):
    import datetime as dt
    from barberis_insights.clients.profile import Facts
    base = dict(client=1, first=dt.date(2025, 1, 1), last=dt.date(2026, 1, 1), visits=6, spend=5000.0, usual_barber=1, last_barber=1, median_gap=30.0, days_since=60)
    return Facts(**(base | kw))


def test_an_early_overdue_regular_gets_a_call_and_a_late_one_gets_the_booking_offer():
    from barberis_insights.clients.risk import classify
    assert classify(_facts(days_since=60))[::2] == ("overdue", "call_only")                  # line is 45: 15 days past it
    assert classify(_facts(days_since=100))[::2] == ("overdue", "book_now")                  # 55 days past it


def test_lapsed_regulars_get_the_offer_only_while_the_data_says_they_can_return():
    from barberis_insights.clients.risk import classify
    assert classify(_facts(days_since=300))[::2] == ("lapsed", "book_now")
    assert classify(_facts(days_since=400))[::2] == ("lapsed", None)                         # silent for over a year
    assert classify(_facts(days_since=400, visits=2))[::2] == ("lapsed", None)               # not a regular


def test_first_timers_get_the_offer_only_while_the_first_visit_is_recent():
    from barberis_insights.clients.risk import classify
    assert classify(_facts(visits=1, median_gap=None, days_since=70))[::2] == ("one_time", "book_now")
    assert classify(_facts(visits=1, median_gap=None, days_since=300))[::2] == ("one_time", None)


def test_seeding_retires_the_first_guess_offers(s):
    from barberis_insights.db.models import Offer
    from barberis_insights.outreach.offers import seed_offers
    s.add(Offer(code="pct10", label="old", kind="percent", value=10, valid_days=30, active=True)); s.flush()
    seed_offers(s)
    assert s.get(Offer, "pct10").active is False and s.get(Offer, "book_now").active is True and s.get(Offer, "book_now").value == 15


# ------------------------------------------------------------------ why not to call, and phones people know
def _ids(s, **kw):
    return {r["client_id"]: r for r in risk_list(s, ("overdue",), **kw)}


def test_a_flag_takes_the_client_off_the_list_and_says_why(s):
    from barberis_insights.clients import contact
    for cid in (30, 31):
        regular(s, cid, "2026-07-20"); client(s, cid)
    build(s)
    contact.add_flag(s, 30, "mobilised", "serves since the spring")
    assert list(_ids(s)) == [31]
    row = _ids(s, include_ineligible=True)[30]
    assert row["ineligible_reasons"] == ["flag_mobilised"] and row["flag"]["comment"] == "serves since the spring"


def test_a_flag_with_a_recheck_date_ends_by_itself_and_can_be_lifted(s):
    from barberis_insights.clients import contact
    regular(s, 32, "2026-07-20"); client(s, 32); regular(s, 33, "2026-07-20"); client(s, 33)
    build(s)
    contact.add_flag(s, 32, "abroad", until=dt.date.today() + dt.timedelta(days=30)); contact.add_flag(s, 33, "moved")
    assert not _ids(s)
    f = contact.active_flags(s, today=dt.date.today() + dt.timedelta(days=31))
    assert 32 not in f and 33 in f                                           # the dated one has run out
    contact.lift_flag(s, 33)
    assert 33 in _ids(s)


def test_a_newer_flag_replaces_the_older_one_and_the_old_one_stays_as_history(s):
    from barberis_insights.clients import contact
    contact.add_flag(s, 34, "abroad", "first"); contact.add_flag(s, 34, "moved", "second")
    assert contact.active_flags(s)[34].comment == "second" and len(contact.history(s, 34)) == 2


def test_an_unknown_reason_or_a_past_date_is_refused(s):
    import pytest
    from barberis_insights.clients import contact
    with pytest.raises(ValueError):
        contact.add_flag(s, 35, "vacation")
    with pytest.raises(ValueError):
        contact.add_flag(s, 35, "abroad", until=dt.date.today() - dt.timedelta(days=1))


def test_a_client_without_a_phone_cannot_be_called(s):
    regular(s, 36, "2026-07-20"); client(s, 36, phone=None)
    build(s)
    assert 36 not in _ids(s) and "no_phone" in _ids(s, include_ineligible=True)[36]["ineligible_reasons"]


def test_reason_other_needs_a_comment(s):
    import pytest
    from barberis_insights.clients import contact
    for blank in ("", "   "):
        with pytest.raises(contact.CommentRequired):
            contact.add_flag(s, 36, "other", blank)
    assert contact.add_flag(s, 36, "other", "waiting for a visa").reason == "other"
    assert contact.add_flag(s, 37, "abroad").comment == ""      # other reasons stay optional


def test_lifting_a_flag_also_clears_the_older_do_not_contact_mark(s):
    from barberis_insights.clients import contact
    regular(s, 38, "2026-07-20"); client(s, 38, do_not_contact=True)
    build(s)
    assert 38 not in _ids(s) and "dnc" in _ids(s, include_ineligible=True)[38]["ineligible_reasons"]
    from barberis_insights.db.models import Client
    contact.lift_flag(s, 38); s.get(Client, 38).do_not_contact = False       # what the single "lift" button does
    assert 38 in _ids(s)
