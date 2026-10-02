"""Shared ingest helpers: normalise Altegio rows and upsert them, recording a sync run."""
from __future__ import annotations

import datetime as dt
from contextlib import contextmanager
from typing import Iterable, Iterator

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db.models import Appointment, AppointmentService, Barber, ScheduleSlot, SyncRun, now


def _min(t: str) -> int:
    return int(t[:2]) * 60 + int(t[3:5])


def upsert_appointments(s: Session, items: Iterable[dict]) -> dict:
    """Insert or replace appointments (newest copy wins). Accepts curated `appointments_list` items or cache rows."""
    added = updated = 0
    for a in items:
        date = a["date"]  # "YYYY-MM-DD HH:MM:SS"
        row = s.get(Appointment, a["id"])
        if row is None:
            row = Appointment(id=a["id"]); s.add(row); added += 1
        else:
            updated += 1
        row.date = dt.date.fromisoformat(date[:10])
        row.start = date[11:16]
        row.barber_id = a.get("team_member_id")
        row.barber_name = a.get("team_member_name")
        row.client_id = a.get("client_id")
        row.status = a.get("status") or "unknown"
        row.online = bool(a.get("online"))
        row.duration_min = int((a.get("duration_seconds") or 0) // 60)
        row.total_cost = float(a.get("total_cost") or 0)
        row.deleted = bool(a.get("deleted"))
        row.fetched_at = now()
        if row.client_id and a.get("client_name"):  # remember the name Altegio shows for this client
            from ..db.models import Client
            c = s.get(Client, row.client_id)
            if c is None:
                s.add(Client(altegio_id=row.client_id, name=a["client_name"].strip()))
            elif not c.name:
                c.name = a["client_name"].strip()
        row.services = [AppointmentService(title=sv.get("title") or "", cost=float(sv.get("cost") or 0), amount=float(sv.get("amount") or 1))
                        for sv in (a.get("services") or [])]
    return {"added": added, "updated": updated}


def replace_schedule(s: Session, barber_id: int, days: dict[dt.date, list[tuple[int, int]]]) -> int:
    """Replace a barber's slots for the given dates (a day with an empty list means not working)."""
    if not days:
        return 0
    s.execute(delete(ScheduleSlot).where(ScheduleSlot.barber_id == barber_id, ScheduleSlot.date.in_(list(days))))
    n = 0
    for d, slots in days.items():
        for a, b in slots:
            s.add(ScheduleSlot(barber_id=barber_id, date=d, start_min=a, end_min=b)); n += 1
    return n


def parse_schedule_line(line: str) -> tuple[dt.date, list[tuple[int, int]]] | None:
    """`YYYY-MM-DD HH:MM-HH:MM [HH:MM-HH:MM ...]` (the skill's text format)."""
    parts = line.split()
    if not parts:
        return None
    return dt.date.fromisoformat(parts[0]), [(_min(p[:5]), _min(p[6:11])) for p in parts[1:]]


def parse_schedules_get(payload: dict) -> dict[dt.date, list[tuple[int, int]]]:
    """A saved `schedules_get` result: {"items": [{"date", "slots": [{"from","to"}], "is_working"}]}."""
    out = {}
    for it in payload.get("items", []):
        out[dt.date.fromisoformat(it["date"])] = [(_min(sl["from"]), _min(sl["to"])) for sl in it.get("slots", [])] if it.get("is_working") else []
    return out


def barber_by_key(s: Session, key: str) -> Barber:
    b = s.scalar(select(Barber).where(Barber.key == key))
    if b is None:
        raise KeyError(f"unknown barber key {key!r}")
    return b


@contextmanager
def sync_run(s: Session, source: str, window_from: dt.date | None = None, window_to: dt.date | None = None) -> Iterator[SyncRun]:
    run = SyncRun(source=source, window_from=window_from, window_to=window_to, counts={})
    s.add(run); s.flush()
    try:
        yield run
        run.status = "ok"
    except Exception as e:  # recorded, then re-raised
        run.status = "failed"; run.log = f"{type(e).__name__}: {e}"
        raise
    finally:
        run.finished = now()
