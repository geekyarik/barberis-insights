"""weekly_review: on Monday morning, last week against the week before and last year, overdue regulars and the goals.

The slot's Monday names the report: its window is the ISO week before it. The job needs completed visits and shifts imported up to
that week's Sunday; until they are, it is `blocked`. When several weeks are caught up in one tick, every week gets its report
but the owner receives one message: the latest week in full and the earlier ones as one line each.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from ..db.models import ReportRun
from ..ingest.status import complete_through
from ..notifications import service as notify
from ..reports import service as reports
from .registry import JobContext, job


def _week(monday: dt.date) -> str:
    iso = (monday - dt.timedelta(days=7)).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _deliver(s, results: list[dict], now: dt.datetime, sleep) -> None:
    ids = [r["report_id"] for r in results if r.get("report_id")]
    if not ids:
        return
    reps = [s.get(ReportRun, i) for i in ids]
    latest, earlier = reps[-1], reps[:-1]
    behind_before = _behind_before(s, reps[0])
    notify.send_report(s, latest, catchup=[r.content for r in earlier] or None, sleep=sleep)
    if behind_before is not None:
        for g in latest.content["goals"]["behind"]:
            if g["id"] not in behind_before:
                notify.send_alert(s, "goal_behind", now.date().isoformat(), sleep=sleep, title=g["title"], scope=g["scope"])


def _behind_before(s, first: ReportRun) -> set | None:
    """Goals already behind in the report before this run's first one (None when there is no earlier report)."""
    prev = s.scalar(select(ReportRun).where(ReportRun.report_key == "weekly_review", ReportRun.window_to < first.window_to).order_by(ReportRun.window_to.desc()).limit(1))
    return {g["id"] for g in prev.content["goals"]["behind"]} if prev else None


@job("weekly_review", "Weekly review", hours=(9,), weekday=0, deliver=_deliver)
def weekly_review(ctx: JobContext) -> dict:
    monday = ctx.slot.date()
    f, t = monday - dt.timedelta(days=7), monday - dt.timedelta(days=1)
    if not complete_through(ctx.s, t):
        return {"status": "blocked", "missing": [_week(monday)]}
    existing = ctx.s.scalar(select(ReportRun).where(ReportRun.report_key == "weekly_review", ReportRun.window_from == f, ReportRun.created_by == "schedule"))
    r = existing or reports.weekly_review(ctx.s, f, t, created_by="manual" if ctx.dry_run else "schedule")
    return {"report_id": r.id, "week": r.content["week"]}
