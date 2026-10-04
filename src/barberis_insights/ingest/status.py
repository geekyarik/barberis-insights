"""How fresh the imported Altegio data is."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Appointment, ScheduleSlot


def data_status(s: Session) -> dict:
    """`last_visit`: the newest completed visit. `last_schedule`: the newest imported shift."""
    return {"last_visit": s.scalar(select(func.max(Appointment.date)).where(Appointment.status == "arrived", Appointment.deleted.is_(False))),
            "last_schedule": s.scalar(select(func.max(ScheduleSlot.date)))}


def complete_through(s: Session, day: dt.date) -> bool:
    """True when both completed visits and shifts are imported up to `day`."""
    st = data_status(s)
    return bool(st["last_visit"] and st["last_visit"] >= day and st["last_schedule"] and st["last_schedule"] >= day)
