"""Is the opening floor right? Compares what the model expected with what happened to the clients an administrator really called.

The return model predicts the chance a client comes back within 90 days with no contact. For every case an administrator processed at least 90 days
ago we look at whether the client visited within 90 days of the call. Observed minus expected is the effect of calling (assuming the model holds
for them). Times a year's value and the shop's margin, less the cost of a call, it says whether a band of cases is worth calling, and so where the
floor on `case_min_priority` belongs.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import Appointment, RiskCase

FOLLOW_UP_DAYS = 90
BANDS = ((0, 500), (500, 1000), (1000, 2000), (2000, 10 ** 9))
MIN_N = 30


def calibration(s: Session, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    cases = [c for c in s.scalars(select(RiskCase).where(RiskCase.status == "closed", RiskCase.contacted.is_(True))) if c.closed and c.snapshot.get("return_chance") is not None]
    ripe = [c for c in cases if c.closed.date() + dt.timedelta(days=FOLLOW_UP_DAYS) <= today]
    bands = []
    for lo, hi in BANDS:
        rows = [c for c in ripe if lo <= c.priority < hi]
        n = len(rows)
        came = 0
        for c in rows:
            day = c.closed.date()
            came += bool(s.scalar(select(Appointment.id).where(Appointment.client_id == c.client_id, Appointment.status == "arrived", Appointment.deleted.is_(False),
                                                              Appointment.date > day, Appointment.date <= day + dt.timedelta(days=FOLLOW_UP_DAYS)).limit(1)))
        expected = sum(c.snapshot["return_chance"] for c in rows) / n if n else None
        observed = came / n if n else None
        uplift = (observed - expected) if n >= MIN_N else None
        value = sum(c.snapshot["return_chance"] and c.priority / c.snapshot["return_chance"] for c in rows) / n if n else None      # average yearly value
        gain = uplift * value * settings.case_margin_ratio if uplift is not None and value else None
        bands.append({"lo": lo, "hi": hi if hi < 10 ** 9 else None, "n": n, "expected": expected, "observed": observed, "uplift": uplift, "yearly_value": value,
                      "gain_per_call": gain, "worth": (gain > settings.case_call_cost) if gain is not None else None})
    first = min((c.closed.date() for c in cases), default=None)
    return {"bands": bands, "contacted": len(cases), "ripe": len(ripe), "first_ripe_on": (first + dt.timedelta(days=FOLLOW_UP_DAYS)) if first else None,
            "floor": settings.case_min_priority, "call_cost": settings.case_call_cost, "margin": settings.case_margin_ratio, "min_n": MIN_N}
