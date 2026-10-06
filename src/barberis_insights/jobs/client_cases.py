"""client_cases: every morning, fetch fresh data, update the active win-back cases, and open cases for clients who crossed a risk line.

Flow: fetch (appointments, including future bookings) → process the database (profiles, then follow-up of active cases, then new cases).
The data must be fresh first: when it is not, the job is `blocked` and the owner is alerted, and no case is opened from stale data.
A day missed while the laptop slept is not replayed: cases are about today, so only the latest slot runs.
"""
from __future__ import annotations

import datetime as dt

from ..cases import service as cases
from ..clients.profile import rebuild_profiles
from ..config import settings
from ..ingest.status import data_status
from ..metrics import Dataset
from ..notifications import service as notify
from . import fetch
from .registry import JobContext, job

AHEAD_DAYS = 60       # how far into the future the fetch looks for bookings


@job("client_cases", "Client cases", hours=(8,))
def client_cases(ctx: JobContext) -> dict:
    today = ctx.slot.date()
    if today < ctx.now.date():
        return {"status": "skipped", "note": "a newer run covers this day"}
    got = None
    if settings.weekly_fetch and not ctx.dry_run:                          # 1. fresh data from the CRM into the local database
        got = fetch.fetch_fresh(ctx.s, today - dt.timedelta(days=1), ctx.now, ahead_days=AHEAD_DAYS, schedules=False)
        if not got["ok"]:
            notify.send_alert(ctx.s, "job_failed", today.isoformat(), job="client_cases: fetch", error=got.get("error", "")[:200])
        else:
            got["bookings_dropped"] = fetch.reconcile_future(ctx.s, got, today, AHEAD_DAYS)
    last = data_status(ctx.s)["last_visit"]
    if last is None or (today - last).days > settings.data_stale_days:      # never open cases from stale data
        return {"status": "blocked", "missing": [f"data up to {today - dt.timedelta(days=1)}"], "fetch": got}
    rebuild_profiles(ctx.s, Dataset.load(ctx.s))                           # 2. process the database
    followed = cases.refresh(ctx.s, today)                                 # a client who came back must not get a new case
    opened = cases.detect(ctx.s, today)
    opened.pop("ids", None)
    return {"opened": opened["opened"], "left_out": opened["left_out"], "followed_up": followed, "fetch": got}
