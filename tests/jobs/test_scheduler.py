import datetime as dt

import pytest
from conftest import visit
from metric_helpers import slot as shift

from barberis_insights.config import settings
from barberis_insights.db.models import Delivery, JobRun
from barberis_insights.jobs import service as jobs
from barberis_insights.jobs.registry import JOBS
from barberis_insights.notifications import service as notify
from barberis_insights.notifications.channels import register
from barberis_insights.notifications.channels.fake import FakeChannel

NOSLEEP = lambda _: None
D = dt.date.fromisoformat
MON = dt.datetime(2026, 3, 16, 10, 0)       # Monday after the window 2026-03-09 .. 2026-03-15


@pytest.fixture
def owner(s, monkeypatch):
    monkeypatch.setattr(settings, "telegram_owner_chat_id", 1)
    fake = FakeChannel()
    register(fake)
    notify.ensure_owner(s)
    s.commit()
    return fake


def data_through(s, day: str):
    visit(s, 1, day, 1, 700)
    shift(s, 1, day)
    s.flush()


def tick(s, now, **kw):
    return jobs.tick(s, now, sleep=NOSLEEP, **kw)


def test_a_due_weekly_review_runs_once_and_is_delivered(s, owner):
    data_through(s, "2026-03-15")
    out = [r for r in tick(s, MON, only="weekly_review")]
    assert out[0]["status"] == "ok" and out[0]["content"]["week"] == "2026-W11"
    assert len(owner.sent) == 1 and "Тижневий огляд" in owner.sent[0][1]
    assert tick(s, MON + dt.timedelta(minutes=15), only="weekly_review") == []        # nothing is due any more
    assert len(owner.sent) == 1


def test_before_its_hour_nothing_is_due(s, owner):
    data_through(s, "2026-03-15")
    s.add(JobRun(job="weekly_review", slot="2026-03-09T09", status="ok")); s.flush()   # last week's review is done
    assert tick(s, dt.datetime(2026, 3, 16, 8, 59), only="weekly_review") == []


def test_incomplete_data_blocks_the_job_and_alerts_once_a_day(s, owner):
    data_through(s, "2026-03-10")                      # the week is not fully imported
    out = tick(s, MON, only="weekly_review")
    assert out[0]["status"] == "blocked" and out[0]["missing"] == ["2026-W11"]
    assert len(owner.sent) == 1 and "чекає на дані" in owner.sent[0][1] and "2026-W11" in owner.sent[0][1]
    tick(s, MON + dt.timedelta(hours=1), only="weekly_review")                         # still blocked: no second alert
    assert len(owner.sent) == 1 and s.query(JobRun).filter_by(status="blocked").count() == 1
    data_through(s, "2026-03-15")                      # the data arrives
    assert tick(s, MON + dt.timedelta(hours=2), only="weekly_review")[0]["status"] == "ok"
    assert len(owner.sent) == 2                         # the review itself


def test_missed_weeks_are_all_processed_in_order_and_sent_as_one_message(s, owner):
    data_through(s, "2026-03-22")
    s.add(JobRun(job="weekly_review", slot="2026-03-02T09", status="ok")); s.flush()
    out = tick(s, dt.datetime(2026, 3, 23, 12, 0), only="weekly_review")
    assert [r["slot"] for r in out] == ["2026-03-09T09", "2026-03-16T09", "2026-03-23T09"]
    assert [r["status"] for r in out] == ["ok"] * 3
    assert len(owner.sent) == 1                         # one message
    text = owner.sent[0][1]
    assert "тиждень 12" in text and "Наздогнали" in text and text.count("тиждень 10") == 1 and "тиждень 11" in text


def test_a_blocked_slot_holds_back_the_later_ones(s, owner):
    data_through(s, "2026-03-05")                      # the week of 2-8 March is not complete
    s.add(JobRun(job="weekly_review", slot="2026-03-02T09", status="ok")); s.flush()
    out = tick(s, dt.datetime(2026, 3, 23, 12, 0), only="weekly_review")
    assert [(r["slot"], r["status"]) for r in out] == [("2026-03-09T09", "blocked")]


def test_the_first_run_does_not_backfill(s, owner):
    data_through(s, "2026-03-22")
    out = tick(s, dt.datetime(2026, 3, 23, 12, 0), only="weekly_review")
    assert [r["slot"] for r in out] == ["2026-03-23T09"]


def test_a_failed_job_alerts_and_is_retried_after_an_hour(s, owner, monkeypatch):
    data_through(s, "2026-03-15")
    real = JOBS["weekly_review"].run
    boom = lambda ctx: (_ for _ in ()).throw(RuntimeError("boom"))
    monkeypatch.setitem(JOBS, "weekly_review", JOBS["weekly_review"].__class__(**{**JOBS["weekly_review"].__dict__, "run": boom}))
    assert tick(s, MON, only="weekly_review")[0]["status"] == "failed"
    assert len(owner.sent) == 1 and "boom" in owner.sent[0][1]
    assert tick(s, MON + dt.timedelta(minutes=20), only="weekly_review")[0]["status"] == "waiting_to_retry"
    monkeypatch.setitem(JOBS, "weekly_review", JOBS["weekly_review"].__class__(**{**JOBS["weekly_review"].__dict__, "run": real}))
    s.query(JobRun).update({"finished": jobs.utcnow() - dt.timedelta(hours=2)})
    assert tick(s, MON + dt.timedelta(hours=2), only="weekly_review")[0]["status"] == "ok"


def test_a_run_in_progress_is_not_started_twice(s, owner):
    data_through(s, "2026-03-15")
    s.add(JobRun(job="weekly_review", slot="x", status="running", started=jobs.utcnow())); s.flush()
    assert tick(s, MON, only="weekly_review") == [{"job": "weekly_review", "status": "busy"}]


def test_data_watch_alerts_when_the_data_is_old(s, owner):
    visit(s, 1, "2026-03-01", 1); s.flush()
    out = tick(s, dt.datetime(2026, 3, 10, 9, 5), only="data_watch")
    assert out[0]["stale"] is True and out[0]["age_days"] == 9 and "Дані застаріли" in owner.sent[0][1]


def test_data_watch_is_quiet_when_the_data_is_fresh(s, owner):
    visit(s, 1, "2026-03-09", 1); s.flush()
    out = tick(s, dt.datetime(2026, 3, 10, 9, 5), only="data_watch")
    assert out[0]["stale"] is False and owner.sent == []


def test_a_dry_run_records_and_sends_nothing(s, owner):
    data_through(s, "2026-03-15")
    out = tick(s, MON, dry_run=True)
    assert any(r["job"] == "weekly_review" and r["would_run"] for r in out)
    assert s.query(JobRun).count() == 0 and owner.sent == []


def test_run_now_ignores_the_schedule_and_dry_run_leaves_no_trace(s, owner):
    data_through(s, "2026-03-15")
    r = jobs.run_now(s, "weekly_review", dt.datetime(2026, 3, 16, 9), dry_run=True, now=MON, sleep=NOSLEEP)
    s.rollback()
    assert r["status"] == "ok" and s.query(JobRun).count() == 0 and owner.sent == []


# ------------------------------------------------------------------ the weekly flow: init -> fresh fetch -> process -> send
@pytest.fixture
def fetcher(s, monkeypatch):
    """A fake Altegio: records what was asked and, when told to, brings the week's data the way an import would."""
    from barberis_insights.jobs import fetch
    monkeypatch.setattr(settings, "weekly_fetch", True)
    calls = {"asked": [], "arrive": None, "ok": True}

    def fake(f, t, staff_ids, clients=False):
        calls["asked"].append((f, t, staff_ids))
        if calls["arrive"]:
            calls["arrive"]()
        if calls.get("imports", True) and calls["ok"]:
            from barberis_insights.db.models import SyncRun
            s.add(SyncRun(source="altegio_api", status="ok")); s.flush()
        return {"ok": calls["ok"], "error": "" if calls["ok"] else "Altegio login failed (HTTP 401)"}
    monkeypatch.setattr(fetch, "_fetch", fake)
    return calls


def test_the_weekly_flow_fetches_before_it_processes_and_sends(s, owner, fetcher):
    fetcher["arrive"] = lambda: data_through(s, "2026-03-15")              # the data only exists after the fetch
    out = tick(s, MON, only="weekly_review")
    assert out[0]["status"] == "ok" and len(fetcher["asked"]) == 1
    f, t, staff = fetcher["asked"][0]
    assert t == D("2026-03-15") and staff == [1, 2]                         # the week's end, and every active barber's shifts
    assert len(owner.sent) == 1 and "Тижневий огляд" in owner.sent[0][1]


def test_without_fresh_data_the_week_is_blocked_and_nothing_is_sent(s, owner, fetcher):
    fetcher["ok"] = False
    out = tick(s, MON, only="weekly_review")
    assert out[0]["status"] == "blocked" and out[0]["fetch"]["ok"] is False
    texts = " ".join(m[1] for m in owner.sent)
    assert "Тижневий огляд" not in texts and "Altegio login failed" in texts       # the owner is told why


def test_a_failed_fetch_still_sends_when_the_database_already_holds_the_week(s, owner, fetcher):
    data_through(s, "2026-03-15")
    fetcher["ok"] = False
    out = tick(s, MON, only="weekly_review")
    assert out[0]["status"] == "ok" and any("Тижневий огляд" in m[1] for m in owner.sent)
    assert any("Altegio login failed" in m[1] for m in owner.sent)


def test_a_dry_run_never_starts_the_fetch(s, owner, fetcher):
    data_through(s, "2026-03-15")
    jobs.run_now(s, "weekly_review", MON, dry_run=True)
    assert fetcher["asked"] == []


def test_a_fetch_that_imported_nothing_is_a_failure_even_if_it_reports_success(s, owner, fetcher):
    data_through(s, "2026-03-15")
    fetcher["imports"] = False                        # the fake reports success but no import ran
    out = tick(s, MON, only="weekly_review")
    assert out[0]["fetch"]["ok"] is False and out[0]["fetch"]["imported"] is False
    assert any("nothing was imported" in m[1] for m in owner.sent)         # the owner is told


# ---- the fetch imports what Altegio returns
def _rec(i, attendance=1, day="2026-03-10", staff=1, client=7, cost=500, phone="380501112233"):
    return {"id": i, "date": f"{day} 18:20:00", "datetime": f"{day}T18:20:00+03:00", "attendance": attendance, "confirmed": 1, "deleted": False, "online": True,
            "length": 3600, "staff_id": staff, "staff": {"name": "A"}, "services": [{"title": "Cut", "cost": cost, "amount": 2}],
            "client": {"id": client, "name": "Іван", "display_name": "Іван", "phone": phone, "email": ""}}


def test_fetch_fresh_imports_appointments_clients_and_shifts_in_this_process(s, monkeypatch):
    from barberis_insights.db.models import Appointment, Client, ScheduleSlot
    from barberis_insights.jobs import fetch
    monkeypatch.setattr(fetch, "_fetch", lambda f, t, staff, clients=False: {"ok": True, "records": [_rec(601), _rec(602, attendance=-1)],
                                                              "schedules": {1: [{"date": "2026-03-16", "is_working": 1, "slots": [{"from": "10:00", "to": "20:00"}]}]}})
    res = fetch.fetch_fresh(s, D("2026-03-15"))
    assert res["ok"] is True and res["imported"] is True and res["appointments_added"] == 2
    a, b = s.get(Appointment, 601), s.get(Appointment, 602)
    assert (a.status, b.status) == ("arrived", "no_show") and a.total_cost == 500 and a.duration_min == 60       # the line's cost counts once, not times its amount
    assert s.get(Client, 7).phone == "+380501112233" and s.query(ScheduleSlot).filter_by(barber_id=1).count() == 1


def test_fetch_fresh_reports_a_failure_without_a_credential(s, monkeypatch):
    from barberis_insights.jobs import fetch
    monkeypatch.setattr(fetch, "_fetch", lambda f, t, staff, clients=False: {"ok": False, "error": "Altegio login failed (HTTP 401): check the partner token, login and password"})
    res = fetch.fetch_fresh(s, D("2026-03-15"))
    assert res["ok"] is False and "partner token" in res["error"] and res["imported"] is False


def test_the_weekly_fetch_also_refreshes_the_client_list(s, monkeypatch):
    from barberis_insights.db.models import Client
    from barberis_insights.jobs import fetch
    from conftest import client as make_client
    make_client(s, 7, phone=None)
    seen = {}
    monkeypatch.setattr(fetch, "_fetch", lambda f, t, staff, clients=False: seen.update(clients=clients) or {"ok": True, "records": [_rec(701)], "schedules": {}, "client_list": [{"id": 7, "phone": "380509998877", "comment": "", "sms_not": 0}]})
    res = fetch.fetch_fresh(s, D("2026-03-15"), clients=True)
    assert seen["clients"] is True and res["ok"] and s.get(Client, 7).phone == "+380509998877"
