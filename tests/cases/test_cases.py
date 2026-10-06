import datetime as dt

import pytest
from conftest import client, visit

from barberis_insights.cases import service as cases
from barberis_insights.clients import contact
from barberis_insights.clients.profile import rebuild_profiles
from barberis_insights.db.models import Appointment, RiskCase
from barberis_insights.metrics import Dataset

D = lambda s: dt.date.fromisoformat(s)
TODAY = D("2026-10-01")


def regular(s, cid, last, every=28, n=6, barber=1, cost=800):
    for i in range(n):
        visit(s, cid, D(last) - dt.timedelta(days=every * (n - 1 - i)), barber, cost)


def build(s):
    s.flush()
    rebuild_profiles(s, Dataset.load(s), TODAY)


def booking(s, cid, day, status="confirmed"):
    return visit(s, cid, day, 1, 800, status=status)


def one_case(s, cid):
    return s.query(RiskCase).filter_by(client_id=cid).one()


def test_a_case_opens_for_each_client_past_a_line_with_a_snapshot(s):
    regular(s, 10, "2026-06-20"); client(s, 10)                     # overdue regular, 103 days away, line 45: 58 days past it
    visit(s, 11, "2026-08-10"); client(s, 11)                       # first-timer 52 days ago
    regular(s, 12, "2026-09-25"); client(s, 12)                     # active: no case
    build(s)
    out = cases.detect(s, TODAY)
    assert out["opened"] == 2
    c = one_case(s, 10)
    assert c.trigger == "overdue" and c.trigger_days == 45 and c.crossed_on == D("2026-06-20") + dt.timedelta(days=45) and c.status == "open"
    assert c.offer == "book_now" and c.expires_on == TODAY + dt.timedelta(days=14) and c.snapshot["visits"] == 6 and c.snapshot["last_visit"] == "2026-06-20"
    assert one_case(s, 11).trigger == "first_timer" and not s.query(RiskCase).filter_by(client_id=12).count()


def test_running_again_opens_nothing_new_and_a_closed_case_does_not_reopen(s):
    regular(s, 10, "2026-07-20"); client(s, 10); build(s)
    assert cases.detect(s, TODAY)["opened"] == 1 and cases.detect(s, TODAY)["opened"] == 0
    cases.no_answer(s, one_case(s, 10), "anna")
    assert cases.detect(s, TODAY + dt.timedelta(days=1))["opened"] == 0          # same client, same line, same silence


def test_flagged_clients_and_clients_without_a_phone_get_no_case(s):
    for cid in (20, 21, 22):
        regular(s, cid, "2026-07-20")
    client(s, 20); client(s, 21, phone=None); client(s, 22)
    build(s)
    contact.add_flag(s, 22, "abroad")
    out = cases.detect(s, TODAY)
    assert out["opened"] == 1 and out["left_out"]["no_phone"] == 1 and out["left_out"]["blocked"] == 1


def test_a_client_who_crosses_a_later_line_gets_a_new_case_once_the_first_is_closed(s):
    regular(s, 10, "2026-03-01"); client(s, 10)                      # 214 days away: lapsed
    build(s)
    cases.detect(s, TODAY)
    assert one_case(s, 10).trigger == "lapsed"


def test_a_visit_closes_the_case_and_says_whether_anyone_called_first(s):
    regular(s, 10, "2026-07-20"); client(s, 10); regular(s, 11, "2026-07-20"); client(s, 11); build(s)
    cases.detect(s, TODAY)
    cases.record_booking(s, one_case(s, 10), "anna", None, today=TODAY)
    visit(s, 10, "2026-10-03", 1, 900); visit(s, 11, "2026-10-04", 1, 700); s.flush()
    out = cases.refresh(s, D("2026-10-05"))
    a, b = one_case(s, 10), one_case(s, 11)
    assert out["visited"] == 2 and a.status == b.status == "closed" and a.outcome == b.outcome == "visited"
    assert a.contacted is True and b.contacted is False and a.visit_revenue == 900 and b.visited_on == D("2026-10-04")


def test_a_future_booking_marks_the_case_but_does_not_close_it(s):
    regular(s, 10, "2026-07-20"); client(s, 10); build(s); cases.detect(s, TODAY)
    booking(s, 10, "2026-10-08")
    cases.refresh(s, TODAY)
    c = one_case(s, 10)
    assert c.status == "booking_exists" and c.booked_for == D("2026-10-08") and c.appointment_id is not None and c.outcome is None
    cases.refresh(s, D("2026-10-07"))
    assert one_case(s, 10).status == "booking_exists"              # still waiting for the visit


def test_a_booking_that_disappears_sends_the_case_back_to_open(s):
    regular(s, 10, "2026-07-20"); client(s, 10); build(s); cases.detect(s, TODAY)
    a = booking(s, 10, "2026-10-08"); cases.refresh(s, TODAY)
    a.deleted = True; s.flush()
    out = cases.refresh(s, D("2026-10-02"))
    c = one_case(s, 10)
    assert out["booking_lost"] == 1 and c.status == "open" and c.appointment_id is None and any(e.kind == "booking_lost" for e in c.events)


def test_a_booking_the_administrator_reports_waits_a_few_days_for_the_crm(s):
    regular(s, 10, "2026-07-20"); client(s, 10); build(s); cases.detect(s, TODAY)
    cases.record_booking(s, one_case(s, 10), "anna", None, today=TODAY)
    cases.refresh(s, TODAY + dt.timedelta(days=2))
    assert one_case(s, 10).status == "booking_exists"             # inside the grace period
    cases.refresh(s, TODAY + dt.timedelta(days=5))
    assert one_case(s, 10).status == "open"                        # never showed up in the CRM


def test_an_unprocessed_case_expires_after_the_term_but_a_booked_one_does_not(s):
    regular(s, 10, "2026-07-20"); client(s, 10); regular(s, 11, "2026-07-20"); client(s, 11); build(s); cases.detect(s, TODAY)
    booking(s, 11, "2026-11-20")
    out = cases.refresh(s, TODAY + dt.timedelta(days=15))
    assert out["expired"] == 1 and one_case(s, 10).outcome == "expired" and one_case(s, 11).status == "booking_exists"


def test_rejecting_for_a_client_reason_flags_the_client_and_closes_the_case(s):
    regular(s, 10, "2026-07-20"); client(s, 10); build(s); cases.detect(s, TODAY)
    c = one_case(s, 10)
    cases.reject(s, c, "anna", "mobilised", "serves since spring")
    assert c.status == "closed" and c.outcome == "rejected" and c.reason == "mobilised" and c.contacted and c.processed_by == "anna"
    assert contact.active_flags(s)[10].reason == "mobilised"


def test_a_declined_offer_or_wrong_number_closes_without_flagging_the_client(s):
    regular(s, 10, "2026-07-20"); client(s, 10); build(s); cases.detect(s, TODAY)
    cases.reject(s, one_case(s, 10), "anna", "declined_offer")
    assert one_case(s, 10).outcome == "rejected" and 10 not in contact.active_flags(s)


def test_reason_other_needs_a_comment_and_a_failed_rejection_changes_nothing(s):
    regular(s, 10, "2026-07-20"); client(s, 10); build(s); cases.detect(s, TODAY)
    with pytest.raises(contact.CommentRequired):
        cases.reject(s, one_case(s, 10), "anna", "other", "")
    assert one_case(s, 10).status == "open"
    with pytest.raises(ValueError):
        cases.reject(s, one_case(s, 10), "anna", "vacation")


def test_one_try_only_no_answer_closes_the_case(s):
    regular(s, 10, "2026-07-20"); client(s, 10); build(s); cases.detect(s, TODAY)
    cases.no_answer(s, one_case(s, 10), "anna")
    c = one_case(s, 10)
    assert c.status == "closed" and c.outcome == "no_answer"
    with pytest.raises(ValueError):
        cases.no_answer(s, c, "anna")                              # a closed case cannot be processed again


def test_the_queue_is_ordered_by_value_and_next_open_skips_the_one_just_done(s):
    regular(s, 10, "2026-07-20", cost=500); client(s, 10); regular(s, 11, "2026-07-20", cost=1500); client(s, 11); build(s); cases.detect(s, TODAY)
    rows = cases.case_rows(s, "open")
    assert [r["client_id"] for r in rows] == [11, 10] and cases.counts(s) == {"open": 2, "booking": 0, "processed": 0}
    assert cases.next_open(s, one_case(s, 11).id).client_id == 10


def test_an_early_overdue_regular_gets_a_call_not_a_discount(s):
    regular(s, 10, "2026-07-20"); client(s, 10); build(s); cases.detect(s, TODAY)       # 73 days away: 28 past the line
    assert one_case(s, 10).offer == "call_only"


# ------------------------------------------------------------------ the first run, the crossing window, and clients of a barber who left
def test_the_first_run_opens_only_the_highest_priority_tenth(s, monkeypatch):
    from barberis_insights.config import settings
    monkeypatch.setattr(settings, "case_first_run_min", 2)
    for cid in range(100, 120):                                   # 20 overdue regulars, the later ones richer
        regular(s, cid, "2026-06-20", cost=400 + 100 * (cid - 100)); client(s, cid)
    build(s)
    out = cases.detect(s, TODAY)
    assert out["first_run"] is True and out["opened"] == 2 and out["left_out"]["first_run_cap"] == 18
    assert {c.client_id for c in s.query(RiskCase)} == {119, 118}


def test_after_the_first_run_only_clients_who_just_crossed_a_line_get_a_case(s, monkeypatch):
    from barberis_insights.config import settings
    monkeypatch.setattr(settings, "case_first_run_min", 1)
    regular(s, 10, "2026-06-20"); client(s, 10)                    # crossed the 45 day line in early August
    build(s); cases.detect(s, TODAY)                               # the first run takes it (the only one)
    regular(s, 11, "2026-06-20"); client(s, 11)                    # an old crossing: does not open
    regular(s, 12, str(TODAY - dt.timedelta(days=52))); client(s, 12)   # crossed 7 days ago: opens
    build(s)
    out = cases.detect(s, TODAY)
    assert out["first_run"] is False and out["left_out"]["crossed_long_ago"] >= 1
    assert s.query(RiskCase).filter_by(client_id=12).count() == 1 and s.query(RiskCase).filter_by(client_id=11).count() == 0


def test_clients_of_a_barber_who_left_are_marked_with_a_same_level_barber_to_suggest(s):
    from barberis_insights.db.models import Barber
    s.add_all([Barber(altegio_id=5, key="gone", name="Gone", tier="Майстер", active=False), Barber(altegio_id=6, key="busy", name="Busy", tier="Майстер", active=True),
               Barber(altegio_id=7, key="free", name="Free", tier="Майстер", active=True), Barber(altegio_id=8, key="exp", name="Expert", tier="Експерт", active=True)])
    s.flush()
    for i in range(5):
        visit(s, 900 + i, TODAY - dt.timedelta(days=10 + i), 6, 500)                # Busy had five recent visits, Free none
    visit(s, 950, TODAY - dt.timedelta(days=12), 2, 500)                            # the test shop's own barber B (same tier) had one
    regular(s, 10, "2026-06-20", barber=5); client(s, 10)
    build(s); cases.detect(s, TODAY)
    snap = one_case(s, 10).snapshot
    assert snap["barber_left"] is True and snap["suggested_barber_id"] == 7        # same tier ("Майстер"), the least busy
    assert cases.case_rows(s, "open")[0]["barber_left"] is True


def test_a_case_stores_the_chance_of_returning_and_a_priority_that_follows_it(s):
    regular(s, 10, "2026-06-20"); client(s, 10); build(s); cases.detect(s, TODAY)
    c = one_case(s, 10)
    assert c.snapshot["return_chance"] is not None and c.priority > 0
