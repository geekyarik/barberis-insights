"""Import files that Claude saved from the Altegio Pro connector.

Supported shapes (detected automatically):
- appointments_list result: {"items": [{"id", "date", "status", "team_member_id", ...}], "pagination": ...}
- schedules_get result:     {"team_member_id", "items": [{"date", "slots", "is_working"}]}
- client profiles:          {"items": [{"id", "name", "phone"?, ...}]} from clients_list_profiles / segment report
- a plain JSON list of appointment items
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Barber
from .base import parse_schedules_get, replace_schedule, sync_run, upsert_appointments
from .clients import upsert_clients


def detect(payload) -> str:
    if isinstance(payload, list):
        return "appointments"
    items = payload.get("items") or []
    if "team_member_id" in payload and items and "is_working" in items[0]:
        return "schedule"
    if items and "team_member_id" in items[0] and "date" in items[0]:
        return "appointments"
    if items and ("phone" in items[0] or "first_visit_date" in items[0] or "visits_count" in items[0] or "name" in items[0]):
        return "clients"
    return "unknown"


def ingest_files(s: Session, paths: list[str | Path]) -> dict:
    totals: dict[str, int] = {"appointments_added": 0, "appointments_updated": 0, "schedule_slots": 0, "clients": 0, "skipped_files": 0}
    with sync_run(s, "connector_files") as run:
        for p in paths:
            payload = json.loads(Path(p).read_text())
            kind = detect(payload)
            if kind == "appointments":
                items = payload if isinstance(payload, list) else payload["items"]
                r = upsert_appointments(s, items)
                totals["appointments_added"] += r["added"]; totals["appointments_updated"] += r["updated"]
            elif kind == "schedule":
                tid = payload["team_member_id"]
                if s.get(Barber, tid) is None:
                    totals["skipped_files"] += 1; continue
                totals["schedule_slots"] += replace_schedule(s, tid, parse_schedules_get(payload))
            elif kind == "clients":
                totals["clients"] += upsert_clients(s, payload["items"])
            else:
                totals["skipped_files"] += 1
        run.counts = totals
    return totals
