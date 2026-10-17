"""The fresh-data step: fetch the latest appointments (and shifts) straight from Altegio's REST API and import them.

The jobs use it before they work (`weekly_review`, `client_cases`). It never raises: a failed fetch is a result (`ok: False`, with a reason that holds no
credential), and a fetch counts as successful only when the database really received an import.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import Appointment, Barber, Client, SyncRun, now as utcnow
from ..ingest import altegio_api
from ..ingest.base import parse_schedules_get, replace_schedule, sync_run, upsert_appointments
from ..ingest.clients import sync_client_list, upsert_clients
from ..ingest.status import data_status


def window(s: Session, through: dt.date, ahead_days: int = 0) -> tuple[dt.date, dt.date]:
    """From two weeks before the newest imported visit (late status changes) to `through`, never more than two months back from it.
    `ahead_days` reaches into the future, to see bookings."""
    last = data_status(s)["last_visit"]
    start = (last - dt.timedelta(days=14)) if last else through - dt.timedelta(days=28)
    return max(start, through - dt.timedelta(days=60)), through + dt.timedelta(days=ahead_days)


def _fetch(f: dt.date, t: dt.date, staff_ids: list[int], clients: bool = False) -> dict:
    """Ask Altegio. Replaced in tests."""
    try:
        api = altegio_api.AltegioApi()
        records = api.records(f, t)
        schedules = {sid: api.schedule(sid, f, t) for sid in staff_ids}
        client_list = api.clients() if clients else None
    except altegio_api.AltegioError as e:
        return {"ok": False, "error": str(e)[:300]}
    except Exception as e:                                # a network failure, a timeout: say what, never include a request
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}
    return {"ok": True, "records": records, "schedules": schedules, "client_list": client_list}


def fetch_fresh(s: Session, through: dt.date, now: dt.datetime | None = None, ahead_days: int = 0, schedules: bool = True, clients: bool = False) -> dict:
    """Pull fresh data and say what changed in the database. Never raises: a failed fetch is a result.
    The daily cases job asks for appointments only, reaching `ahead_days` into the future for bookings; the weekly job also refreshes the whole client list."""
    f, t = window(s, through, ahead_days)
    s.commit()
    started = utcnow()
    before = (data_status(s), s.scalar(select(func.count(Appointment.id))), s.scalar(select(func.count(Client.altegio_id))))
    staff = [b.altegio_id for b in s.scalars(select(Barber).where(Barber.active.is_(True)))] if schedules else []
    res = _fetch(f, t, staff, clients)
    if res.get("ok") and "records" in res:                # the real fetch returns what Altegio said; import it here, in this process
        try:
            with sync_run(s, "altegio_api", f, t) as run:
                res["import"] = {"appointments": upsert_appointments(s, [altegio_api.to_appointment(r) for r in res["records"]]),
                                 "clients": upsert_clients(s, [c for c in (altegio_api.to_client_contact(r) for r in res["records"]) if c]),
                                 "schedule_slots": sum(replace_schedule(s, sid, parse_schedules_get(altegio_api.to_schedule_payload(sid, days))) for sid, days in res["schedules"].items())}
                if res.get("client_list") is not None:
                    res["import"]["client_list"] = sync_client_list(s, res["client_list"])
                run.counts = res["import"]
        except Exception as e:
            s.rollback()
            res = {"ok": False, "error": f"import failed: {type(e).__name__}: {e}"[:300]}
    for k in ("records", "schedules", "client_list"):
        res.pop(k, None)
    s.commit()
    imported = s.scalar(select(func.count(SyncRun.id)).where(SyncRun.source.in_(("altegio_api", "connector_files")), SyncRun.status == "ok", SyncRun.started >= started))
    after = (data_status(s), s.scalar(select(func.count(Appointment.id))), s.scalar(select(func.count(Client.altegio_id))))
    res |= {"started_at": started.isoformat(), "window": [str(f), str(t)], "last_visit": str(after[0]["last_visit"]), "last_schedule": str(after[0]["last_schedule"]),
            "appointments_added": after[1] - before[1], "clients_added": after[2] - before[2], "imported": bool(imported)}
    if res.get("ok") and not imported:
        res["ok"], res["error"] = False, "the fetch finished but nothing was imported"
    return res


def reconcile_future(s: Session, fetch_result: dict, today: dt.date, ahead_days: int) -> int:
    """Altegio drops a cancelled appointment from its list instead of marking it, so a booking we no longer see is gone.
    Only after a fetch that really imported something, and only inside the window the fetch covered."""
    if not fetch_result.get("ok"):
        return 0
    since = dt.datetime.fromisoformat(fetch_result["started_at"])
    imported = s.scalar(select(func.count(SyncRun.id)).where(SyncRun.source.in_(("altegio_api", "connector_files")), SyncRun.status == "ok", SyncRun.started >= since))
    if not imported:
        return 0
    gone = list(s.scalars(select(Appointment).where(Appointment.date >= today, Appointment.date <= today + dt.timedelta(days=ahead_days), Appointment.deleted.is_(False),
                                                     Appointment.status.in_(("waiting", "confirmed")), Appointment.fetched_at < since)))
    for a in gone:
        a.deleted = True
    s.flush()
    return len(gone)
