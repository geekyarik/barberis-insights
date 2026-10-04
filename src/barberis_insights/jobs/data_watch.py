"""data_watch: raise an Alert when the newest completed visit is too old or an import failed."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from ..config import settings
from ..db.models import SyncRun, now as utcnow
from ..ingest.status import data_status
from ..notifications import service as notify
from .registry import JobContext, job


@job("data_watch", "Check that the data is fresh", hours=(9,))
def data_watch(ctx: JobContext) -> dict:
    today, st = ctx.slot.date(), data_status(ctx.s)
    age = (today - st["last_visit"]).days if st["last_visit"] else None
    stale = age is None or age > settings.data_stale_days
    failed = list(ctx.s.scalars(select(SyncRun).where(SyncRun.status == "failed", SyncRun.started > utcnow() - dt.timedelta(hours=24))))
    if not ctx.dry_run:
        if stale:
            notify.send_alert(ctx.s, "data_stale", today.isoformat(), date=st["last_visit"] or "—", days=age if age is not None else "—")
        for f in failed:
            notify.send_alert(ctx.s, "job_failed", today.isoformat(), job=f"import {f.source}", error=f.log[:200])
    return {"stale": stale, "age_days": age, "failed_imports": len(failed)}
