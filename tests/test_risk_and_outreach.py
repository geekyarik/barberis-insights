import datetime as dt

from conftest import client, visit

from barberis_insights.clients.profile import rebuild_profiles
from barberis_insights.clients.risk import risk_list
from barberis_insights.db.models import Client, ClientProfile, OutreachCase
from barberis_insights.metrics import Dataset
from barberis_insights.outreach import service
from barberis_insights.outreach.attribution import attribute
from barberis_insights.outreach.sheets import FakeSheet, sync, tab_name

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
    [case] = service.propose(s, risk_list(s, ("overdue",)))
    return case


def test_attribution_won_back_once(s):
    case = _one_case(s)
    service.set_status(s, case, "called", on=D("2026-08-01"))
    visit(s, 30, "2026-08-20", cost=850); s.flush()
    r1 = attribute(s, today=D("2026-09-01"))
    assert case.status == "won_back" and case.returned_on == D("2026-08-20") and case.revenue_recovered == 850 and r1["won_back"] == 1
    assert attribute(s, today=D("2026-09-02"))["won_back"] == 0  # no double counting


def test_attribution_not_returned_after_window(s):
    case = _one_case(s)
    service.set_status(s, case, "no_answer", on=D("2026-07-25"))  # after the client's last visit (2026-07-20)
    assert attribute(s, today=D("2026-09-10"))["not_returned"] == 0  # window (60 days) still open
    assert attribute(s, today=D("2026-09-25"))["not_returned"] == 1 and case.status == "not_returned"


def test_sheet_round_trip(s):
    """Ukrainian sheet (the default): push, admin edits, pull, archive; a second sync changes nothing."""
    for cid in (40, 41):
        regular(s, cid, "2026-07-20"); client(s, cid)
    build(s)
    cases = service.propose(s, risk_list(s, ("overdue",)))
    assert len(cases) == 2 and all(c.status == "proposed" for c in cases)
    sheet = FakeSheet()
    call, done = tab_name("call", "uk"), tab_name("done", "uk")
    assert sync(s, sheet, ["call_only", "pct10"], "uk")["pushed"] == 0          # nothing approved yet
    assert set(sheet.tabs()) == {"Обдзвін", "Завершені"} and sheet.headers(call)[0] == "№ звернення"
    service.approve(s, [c.id for c in cases], assigned_to="admin")
    r = sync(s, sheet, ["call_only", "pct10"], "uk")
    assert r["pushed"] == 2 and len(sheet.read(call)) == 2 and all(c.status == "in_sheet" for c in cases)
    assert sheet.read(call)[0]["Рекомендована пропозиція"] in ("Дружній дзвінок без знижки", "Знижка 10% на наступний візит")
    a, b = cases
    sheet.edit(call, a.id, **{"Результат": "Записався", "Дата дзвінка": "30.09.2026", "Запропоновано": "Знижка 10% на наступний візит",
                              "Коментар адміністратора": "Прийде в п'ятницю"})
    sheet.edit(call, b.id, **{"Результат": "Не турбувати", "Дата дзвінка": "2026-09-30"})
    r = sync(s, sheet, ["call_only", "pct10"], "uk")
    assert r["pulled_changes"] == 2
    assert a.status == "booked" and a.offer_given == "pct10" and a.contacted_on == D("2026-09-30")
    assert b.status == "do_not_contact" and s.get(Client, 41).do_not_contact is True
    assert r["archived"] == 1 and [row["№ звернення"] for row in sheet.read(call)] == [str(a.id)]
    archived = sheet.read(done)
    assert archived[0]["Статус"] == "не турбувати" and "Телефон" not in archived[0]
    again = sync(s, sheet, ["call_only", "pct10"], "uk")
    assert again["pulled_changes"] == 0 and again["pushed"] == 0 and again["archived"] == 0  # idempotent
    assert "Прийде в п'ятницю" in [e.note for e in a.events if e.note]
    assert sheet.dropdowns[(call, sheet.headers(call).index("Результат"))][2] == "Записався"


def test_sheet_reads_either_language(s):
    """An English sheet already in use keeps its headers; outcomes typed in either language are understood."""
    for cid in (42, 43):
        regular(s, cid, "2026-07-20"); client(s, cid)
    build(s)
    cases = service.propose(s, risk_list(s, ("overdue",)))
    service.approve(s, [c.id for c in cases])
    sheet = FakeSheet()
    sync(s, sheet, ["call_only"], "en")
    assert "Call list" in sheet.tabs() and len(sheet.read("Call list")) == 2
    a, b = cases
    sheet.edit("Call list", a.id, **{"Outcome": "Booked"})
    sheet.edit("Call list", b.id, **{"Outcome": "Не відповів"})
    r = sync(s, sheet, ["call_only"], "uk")                  # switched to Ukrainian while the English tab has rows
    assert r["pulled_changes"] == 2 and a.status == "booked" and b.status == "no_answer"
    assert "Call list" in sheet.tabs() and "Обдзвін" not in sheet.tabs()


def test_empty_sheet_switches_language(s):
    sheet = FakeSheet()
    sync(s, sheet, ["call_only"], "en")
    assert set(sheet.tabs()) == {"Call list", "Done"}
    sync(s, sheet, ["call_only"], "uk")                      # no rows yet: renamed and re-headed in Ukrainian
    assert set(sheet.tabs()) == {"Обдзвін", "Завершені"} and sheet.headers("Обдзвін")[1] == "Клієнт"


def test_offer_arms_are_assigned(s):
    for cid in range(50, 60):
        regular(s, cid, "2026-07-20"); client(s, cid)
    build(s)
    cases = service.propose(s, risk_list(s, ("overdue",)), arms=["call_only", "pct10"], seed=1)
    arms = {c.offer_arm for c in cases}
    assert arms == {"call_only", "pct10"} and all(c.suggested_offer == c.offer_arm for c in cases)


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
