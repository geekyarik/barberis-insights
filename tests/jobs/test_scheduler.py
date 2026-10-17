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
    """A fake headless Claude: records its prompt and, when told to, imports the week the way the real ingest would."""
    from barberis_insights.jobs import fetch
    monkeypatch.setattr(settings, "weekly_fetch", True)
    calls = {"prompts": [], "arrive": None, "ok": True}

    def run(prompt, out=None):
        calls["prompts"].append(prompt)
        if calls["arrive"]:
            calls["arrive"]()
        if calls.get("imports", True) and calls["ok"]:
            from barberis_insights.db.models import SyncRun
            s.add(SyncRun(source="connector_files", status="ok")); s.flush()
        return {"ok": calls["ok"], "error": "" if calls["ok"] else "claude is not signed in"}
    monkeypatch.setattr(fetch, "_runner", run)
    monkeypatch.setattr(settings, "data_dir", __import__("pathlib").Path(__import__("tempfile").mkdtemp()))
    return calls


def test_the_weekly_flow_fetches_before_it_processes_and_sends(s, owner, fetcher):
    fetcher["arrive"] = lambda: data_through(s, "2026-03-15")              # the data only exists after the fetch
    out = tick(s, MON, only="weekly_review")
    assert out[0]["status"] == "ok" and len(fetcher["prompts"]) == 1
    assert "2026-03-15" in fetcher["prompts"][0] and "team_member_id=1" in fetcher["prompts"][0]
    assert len(owner.sent) == 1 and "Тижневий огляд" in owner.sent[0][1]


def test_without_fresh_data_the_week_is_blocked_and_nothing_is_sent(s, owner, fetcher):
    fetcher["ok"] = False
    out = tick(s, MON, only="weekly_review")
    assert out[0]["status"] == "blocked" and out[0]["fetch"]["ok"] is False
    texts = " ".join(m[1] for m in owner.sent)
    assert "Тижневий огляд" not in texts and "claude is not signed in" in texts      # the owner is told why


def test_a_failed_fetch_still_sends_when_the_database_already_holds_the_week(s, owner, fetcher):
    data_through(s, "2026-03-15")
    fetcher["ok"] = False
    out = tick(s, MON, only="weekly_review")
    assert out[0]["status"] == "ok" and any("Тижневий огляд" in m[1] for m in owner.sent)
    assert any("claude is not signed in" in m[1] for m in owner.sent)


def test_a_dry_run_never_starts_the_fetch(s, owner, fetcher):
    data_through(s, "2026-03-15")
    jobs.run_now(s, "weekly_review", MON, dry_run=True)
    assert fetcher["prompts"] == []


def test_a_fetch_that_imported_nothing_is_a_failure_even_if_claude_says_it_is_done(s, owner, fetcher):
    data_through(s, "2026-03-15")
    fetcher["imports"] = False                        # Claude reports success but no import ran
    out = tick(s, MON, only="weekly_review")
    assert out[0]["fetch"]["ok"] is False and out[0]["fetch"]["imported"] is False
    assert any("nothing was imported" in m[1] for m in owner.sent)         # the owner is told


def test_the_fetch_prompt_only_allows_the_two_read_tools_and_no_files_or_shell(s):
    from barberis_insights.jobs import fetch
    prompt = fetch.build_prompt(s, dt.date(2026, 3, 1), dt.date(2026, 3, 15), None)
    assert "appointments_list" in prompt and "team_member_id=1" in prompt and "Do not write files" in prompt
    assert fetch.ALLOWED.count("mcp__") == 2 and "Bash" not in fetch.ALLOWED and "Write" not in fetch.ALLOWED


# ---- reading what the headless Claude fetched
def _stream(*events):
    import json
    return "\n".join(json.dumps(e) for e in events)


def _call(tid, name="mcp__claude_ai_Altegio_Pro__appointments_list"):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": name, "input": {}}]}}


def _result(tid, payload, error=False):
    import json
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid, "is_error": error, "content": [{"type": "text", "text": payload if isinstance(payload, str) else json.dumps(payload)}]}]}}


def _page(ids, more=False, key="datetime", stamp="2026-03-10T18:20:00+03:00"):
    return {"items": [{"id": i, key: stamp, "status": "arrived", "team_member_id": 1, "client_id": 7, "total_cost": 500, "services": []} for i in ids],
            "pagination": {"page": 1, "has_more": more, "next_page": 2 if more else None}}


def test_the_stream_parser_collects_every_page_in_the_shape_the_connector_returns():
    from barberis_insights.jobs.fetch import parse_stream
    got = parse_stream(_stream(_call("a"), _result("a", _page([1, 2], more=True)), _call("b"), _result("b", _page([3])), {"type": "result", "result": "done"}))
    assert len(got["payloads"]) == 2 and got["problems"] == [] and got["reply"] == "done"


def test_an_unfinished_pagination_or_a_failed_call_is_a_problem():
    from barberis_insights.jobs.fetch import parse_stream
    cut = parse_stream(_stream(_call("a"), _result("a", _page([1], more=True))))
    assert any("stopped before the last" in p for p in cut["problems"])
    failed = parse_stream(_stream(_call("a"), _result("a", "boom", error=True)))
    assert failed["payloads"] == [] and failed["problems"]
    nothing = parse_stream(_stream({"type": "result", "result": "done"}))
    assert any("no appointment result" in p for p in nothing["problems"])


def test_results_of_other_tools_are_ignored():
    from barberis_insights.jobs.fetch import parse_stream
    got = parse_stream(_stream(_call("x", "ToolSearch"), _result("x", {"items": [{"id": 9}]}), _call("a"), _result("a", _page([1]))))
    assert len(got["payloads"]) == 1


def test_the_importer_reads_both_the_old_date_and_the_new_datetime_shape(s):
    from barberis_insights.db.models import Appointment
    from barberis_insights.ingest.connector_files import detect, ingest_payloads
    new, old = _page([501]), _page([502], key="date", stamp="2026-03-11 09:30:00")
    assert detect(new) == "appointments" and detect(old) == "appointments"
    out = ingest_payloads(s, [new, old])
    assert out["appointments_added"] == 2 and out["skipped_files"] == 0
    a, b = s.get(Appointment, 501), s.get(Appointment, 502)
    assert (a.date, a.start) == (D("2026-03-10"), "18:20") and (b.date, b.start) == (D("2026-03-11"), "09:30")


def test_fetch_fresh_imports_what_the_runner_returns_and_fails_on_a_shape_it_does_not_know(s, monkeypatch):
    from barberis_insights.jobs import fetch
    monkeypatch.setattr(fetch, "_runner", lambda prompt, out=None: {"ok": True, "payloads": [_page([601, 602])], "reply": "done"})
    res = fetch.fetch_fresh(s, D("2026-03-15"))
    assert res["ok"] is True and res["imported"] is True and res["appointments_added"] == 2
    monkeypatch.setattr(fetch, "_runner", lambda prompt, out=None: {"ok": True, "payloads": [{"items": [{"id": 1, "what": "?"}]}], "reply": "done"})
    bad = fetch.fetch_fresh(s, D("2026-03-15"))
    assert bad["ok"] is False and "shape" in bad["error"]
