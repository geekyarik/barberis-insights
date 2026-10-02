"""Decide whether contacted clients came back. Run after every ingest (idempotent)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import Appointment, OutreachCase
from .service import set_status

WATCH = ("called", "no_answer", "booked")


def attribute(s: Session, today: dt.date | None = None) -> dict:
    """A contacted case becomes `won_back` at the first completed visit within the win-back window after contact,
    or `not_returned` once the window has passed with no visit. Data freshness is the latest completed visit."""
    window = dt.timedelta(days=settings.winback_window_days)
    latest = s.scalar(select(Appointment.date).where(Appointment.status == "arrived").order_by(Appointment.date.desc()).limit(1))
    today = today or latest or dt.date.today()
    won = lost = 0
    for c in s.scalars(select(OutreachCase).where(OutreachCase.status.in_(WATCH), OutreachCase.contacted_on.is_not(None))):
        visit = s.scalar(select(Appointment).where(Appointment.client_id == c.client_id, Appointment.status == "arrived",
                                                   Appointment.deleted.is_(False), Appointment.date >= c.contacted_on,
                                                   Appointment.date <= c.contacted_on + window).order_by(Appointment.date).limit(1))
        if visit:
            c.returned_on, c.revenue_recovered = visit.date, visit.total_cost
            set_status(s, c, "won_back", source="auto", note=f"visit on {visit.date}, ₴{visit.total_cost:,.0f}")
            won += 1
        elif today > c.contacted_on + window:
            set_status(s, c, "not_returned", source="auto", note=f"no visit within {settings.winback_window_days} days")
            lost += 1
    return {"won_back": won, "not_returned": lost, "as_of": str(today)}
