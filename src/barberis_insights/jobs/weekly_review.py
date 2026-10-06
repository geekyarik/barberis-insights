"""weekly_review: on Monday morning, last week against the week before and last year, overdue regulars and the goals.

The slot's Monday names the week: the ISO week before it. The job needs completed visits and shifts imported up to that week's
Sunday; until they are, it is `blocked`. Its figures are computed from the data when it runs and sent as a message; nothing is
kept except the job's own record. When several weeks are caught up in one tick, every week is computed but the owner receives one
message: the latest week in full and the earlier ones as one line each.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from ..config import settings
from ..db.models import JobRun
from ..clients.profile import rebuild_profiles
from ..metrics import Dataset
from ..ingest.status import complete_through
from ..notifications import service as notify
from ..notifications import weekly
from . import fetch
from .registry import JobContext, job


def _week(monday: dt.date) -> str:
    iso = (monday - dt.timedelta(days=7)).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _deliver(s, results: list[dict], now: dt.datetime, sleep) -> None:
    done = [r["content"] for r in results if r.get("content")]
    if not done:
        return
    latest, earlier = done[-1], done[:-1]
    behind_before = _behind_before(s, done[0])
    notify.send_weekly(s, latest, catchup=earlier or None, sleep=sleep)
    if behind_before is not None:
        for g in latest["goals"]["behind"]:
            if g["id"] not in behind_before:
                notify.send_alert(s, "goal_behind", now.date().isoformat(), sleep=sleep, title=g["title"], scope=g["scope"])


def _behind_before(s, first: dict) -> set | None:
    """Goals that were behind in the previous week's message (None when no earlier week was recorded)."""
    for run in s.scalars(select(JobRun).where(JobRun.job == "weekly_review", JobRun.status == "ok").order_by(JobRun.id.desc()).limit(20)):
        c = (run.counts or {}).get("content")
        if c and c["window"][1] < first["window"][1]:
            return {g["id"] for g in c["goals"]["behind"]}
    return None


@job("weekly_review", "Weekly review", hours=(9,), weekday=0, deliver=_deliver)
def weekly_review(ctx: JobContext) -> dict:
    monday = ctx.slot.date()
    f, t = monday - dt.timedelta(days=7), monday - dt.timedelta(days=1)
    got = None
    if settings.weekly_fetch and not ctx.dry_run:                       # 1. fresh data from the CRM into the local database
        got = fetch.fetch_fresh(ctx.s, t, ctx.now)
        if not got["ok"]:
            notify.send_alert(ctx.s, "job_failed", ctx.now.date().isoformat(), job="weekly_review: fetch", error=got.get("error", "")[:200])
    if not complete_through(ctx.s, t):                                  # never report on a week the database does not hold yet
        return {"status": "blocked", "missing": [_week(monday)], "fetch": got}
    rebuild_profiles(ctx.s, Dataset.load(ctx.s))                        # 2. process the database: client profiles, then the analyses
    content = weekly.weekly_content(ctx.s, f, t, created_by="manual" if ctx.dry_run else "schedule")
    return {"content": content, "week": content["week"], "fetch": got}
