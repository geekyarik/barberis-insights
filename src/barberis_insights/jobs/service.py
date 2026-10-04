"""The Scheduler service. One launchd agent calls `tick` every 15 minutes; a tick runs every job that is due.

A slot is a scheduled moment (a date and an hour, on the shop's clock). Every missed slot is processed, none skipped, in
strict order per job: a slot runs only after the previous one is done. A slot whose data is incomplete is `blocked` and
stops that job's chain, with one alert a day, until the data arrives. A failed slot is retried after an hour.
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Callable
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import JobRun, now as utcnow
from ..notifications import service as notify
from . import _discover
from .registry import JOBS, JobContext, JobDef

_discover()

DONE = ("ok", "skipped")
LOOKBACK_DAYS = 60
RETRY_AFTER = dt.timedelta(hours=1)
BUSY_FOR = dt.timedelta(minutes=30)
FMT = "%Y-%m-%dT%H"


def local_now(now: dt.datetime | None = None) -> dt.datetime:
    """Naive local time on the shop's clock."""
    tz = ZoneInfo(settings.timezone)
    if now is None:
        return dt.datetime.now(tz).replace(tzinfo=None)
    return now.astimezone(tz).replace(tzinfo=None) if now.tzinfo else now   # a naive time is taken as already local


def slots_until(job: JobDef, now: dt.datetime, days: int = LOOKBACK_DAYS) -> list[dt.datetime]:
    out = []
    for back in range(days, -1, -1):
        day = (now - dt.timedelta(days=back)).date()
        if job.weekday is not None and day.weekday() != job.weekday:
            continue
        out += [dt.datetime.combine(day, dt.time(h)) for h in job.hours if dt.datetime.combine(day, dt.time(h)) <= now]
    return out


def pending_slots(s: Session, job: JobDef, now: dt.datetime) -> list[dt.datetime]:
    """Slots not done yet, oldest first. A job that never ran starts at its latest slot (no deep backfill; ask for one explicitly)."""
    slots = slots_until(job, now)
    if not slots:
        return []
    last = s.scalar(select(JobRun.slot).where(JobRun.job == job.key, JobRun.status.in_(DONE)).order_by(JobRun.slot.desc()).limit(1))
    if last is None:
        return slots[-1:]
    return [x for x in slots if x.strftime(FMT) > last]


def _run(s: Session, job: JobDef, slot: dt.datetime, now: dt.datetime, dry_run: bool, sheet_factory) -> tuple[str, dict]:
    ctx = JobContext(s, slot, now, dry_run, sheet_factory)
    try:
        res = job.run(ctx)
        return res.get("status", "ok"), res
    except Exception as e:  # recorded, never raised: one broken job must not stop the others
        s.rollback()           # drop what the job left half-done; earlier commits stay
        return "failed", {"error": f"{type(e).__name__}: {e}"[:500]}


def tick(s: Session, now: dt.datetime | None = None, only: str | None = None, dry_run: bool = False,
         sheet_factory: Callable | None = None, sleep: Callable[[float], None] = time.sleep) -> list[dict]:
    now = local_now(now)
    out = []
    if dry_run:                                    # show what would run; record and send nothing
        for job in JOBS.values():
            if not only or job.key == only:
                out += [{"job": job.key, "slot": x.strftime(FMT), "would_run": True} for x in pending_slots(s, job, now)]
        return out
    for job in JOBS.values():
        if only and job.key != only:
            continue
        busy = s.scalar(select(JobRun.id).where(JobRun.job == job.key, JobRun.status == "running", JobRun.started > utcnow() - BUSY_FOR))
        if busy:
            out.append({"job": job.key, "status": "busy"})
            continue
        done = []
        for slot in pending_slots(s, job, now):
            key = slot.strftime(FMT)
            last = s.scalar(select(JobRun).where(JobRun.job == job.key, JobRun.slot == key).order_by(JobRun.id.desc()).limit(1))
            if last and last.status == "failed" and last.finished and utcnow() - last.finished.replace(tzinfo=utcnow().tzinfo) < RETRY_AFTER:
                out.append({"job": job.key, "slot": key, "status": "waiting_to_retry"})
                break
            row = last if (last and last.status == "blocked" and last.started.date() == utcnow().date()) else JobRun(job=job.key, slot=key)
            row.status, row.started, row.error = "running", utcnow(), ""
            s.add(row); s.commit()
            status, res = _run(s, job, slot, now, dry_run, sheet_factory)
            row.status, row.finished, row.counts = status, utcnow(), {k: v for k, v in res.items() if k not in ("status", "error")}
            row.error = res.get("error", "")
            s.commit()
            out.append({"job": job.key, "slot": key, "status": status} | {k: v for k, v in res.items() if k != "status"})
            if status == "failed":
                notify.send_alert(s, "job_failed", now.date().isoformat(), sleep=sleep, job=job.key, error=row.error)
                s.commit()
                break
            if status == "blocked":
                notify.send_alert(s, "job_blocked", now.date().isoformat(), sleep=sleep, job=job.key, weeks=", ".join(res.get("missing", [])))
                s.commit()
                break
            done.append({"slot": key} | res)
        if done and job.deliver:
            job.deliver(s, done, now, sleep)
            s.commit()
    return out


def run_now(s: Session, key: str, slot: dt.datetime | None = None, dry_run: bool = False, sheet_factory: Callable | None = None,
            now: dt.datetime | None = None, sleep: Callable[[float], None] = time.sleep) -> dict:
    """Run one job for one slot immediately, whether or not it is due or done (the manual path: CLI, dashboard, MCP)."""
    job = JOBS[key]
    now = local_now(now)
    slot = slot or (slots_until(job, now) or [now])[-1]
    status, res = _run(s, job, slot, now, dry_run, sheet_factory)
    if not dry_run:
        s.add(JobRun(job=key, slot=slot.strftime(FMT), status=status, finished=utcnow(), counts={k: v for k, v in res.items() if k not in ("status", "error")}, error=res.get("error", "")))
        if status == "ok" and job.deliver:
            job.deliver(s, [{"slot": slot.strftime(FMT)} | res], now, sleep)
        s.flush()
    return {"job": key, "slot": slot.strftime(FMT), "status": status} | {k: v for k, v in res.items() if k != "status"}


def list_jobs(s: Session) -> list[dict]:
    out = []
    for j in JOBS.values():
        last = s.scalar(select(JobRun).where(JobRun.job == j.key).order_by(JobRun.id.desc()).limit(1))
        out.append({"job": j.key, "label": j.label, "hours": list(j.hours), "weekday": j.weekday,
                    "last": {"slot": last.slot, "status": last.status, "error": last.error} if last else None})
    return out
