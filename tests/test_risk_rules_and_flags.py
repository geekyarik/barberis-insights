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


def _so(**kw):
    """(segment, offer) for a client with these facts."""
    from barberis_insights.clients.risk import classify
    r = classify(_facts(**kw))
    return r[0], r[3]


def test_an_early_overdue_regular_gets_a_call_and_a_late_one_gets_the_booking_offer():
    assert _so(days_since=60) == ("overdue", "call_only")                  # gap 30: the line is 45, so 15 days past it
    assert _so(days_since=100) == ("overdue", "book_now")                  # 55 days past it


def test_a_client_with_two_visits_has_one_fixed_line_and_only_ever_gets_a_call():
    assert _so(visits=2, median_gap=None, days_since=55)[0] == "slipping" or _so(visits=2, median_gap=None, days_since=55)[0] == "active"
    assert _so(visits=2, median_gap=None, days_since=70) == ("overdue", "call_only")      # line 60, not 45
    assert _so(visits=2, median_gap=None, days_since=100) == ("overdue", "call_only")     # however late, no discount


def test_the_lapsed_line_follows_the_clients_own_rhythm_within_limits():
    assert _so(median_gap=30.0, days_since=110)[0] == "overdue" and _so(median_gap=30.0, days_since=125)[0] == "lapsed"     # 2 x 30 = 60, floor 120
    assert _so(median_gap=90.0, days_since=170)[0] == "overdue" and _so(median_gap=90.0, days_since=185)[0] == "lapsed"     # 2 x 90 = 180
    assert _so(median_gap=250.0, days_since=380)[0] == "lapsed"                                                              # 2 x 250 is capped at 365, but never before the overdue line (375)


def test_lapsed_regulars_get_the_offer_only_while_the_data_says_they_can_return():
    assert _so(days_since=300) == ("lapsed", "book_now")
    assert _so(days_since=400) == ("lapsed", None)                                         # silent for over a year
    assert _so(days_since=300, visits=2, median_gap=None) == ("lapsed", None)              # not a regular


def test_first_timers_get_the_offer_only_while_the_first_visit_is_recent():
    assert _so(visits=1, median_gap=None, days_since=20)[0] == "active"                    # not yet 28 days
    assert _so(visits=1, median_gap=None, days_since=35) == ("one_time", "book_now")
    assert _so(visits=1, median_gap=None, days_since=300) == ("one_time", None)


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


# ------------------------------------------------------------------ the chance of returning, and the priority built on it
def test_the_return_model_learns_that_silence_lowers_the_chance_and_visits_raise_it():
    from barberis_insights.clients.return_model import fit
    day = dt.date(2025, 1, 1)
    hist = {}
    for c in range(200):                                       # regulars who come back after 28 or 50 days, alternately
        d, hist[c] = day, [day]
        for i in range(9):
            d += dt.timedelta(days=28 if i % 2 == 0 else 50); hist[c].append(d)
    for c in range(200, 600):                                  # one-timers who never come back
        hist[c] = [day]
    m = fit(hist, dt.date(2026, 6, 1))
    assert m.chance(8, 31) > 0.5                               # a regular a few days late usually comes
    assert m.chance(1, 120) < 0.05                             # a one-timer silent 120 days never does
    assert m.chance(1, 40) < 0.05 and m.chance(8, 40) > m.chance(1, 40)


def test_priority_is_chance_times_a_years_value_so_the_likelier_and_richer_go_first(s):
    from barberis_insights.clients.risk import yearly_value, priority
    from barberis_insights.clients.return_model import ReturnModel
    model = ReturnModel(cells={(2, 3): [100, 50]}, by_silence={3: [100, 50]})          # 50% for 3 visits, 75-104 days silent
    rich, poor = _facts(spend=12000.0, visits=6, days_since=80), _facts(spend=3000.0, visits=6, days_since=80)
    assert priority(rich, model)[1] == 0.5 and priority(rich, model)[0] > priority(poor, model)[0] * 3
    assert round(yearly_value(poor)) == round(500 * 365 / 30)
    assert priority(_facts(days_since=80), None)[1] == 0.1
