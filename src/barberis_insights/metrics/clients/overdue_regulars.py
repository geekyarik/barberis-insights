"""Overdue regulars: clients with 3+ visits to the barber whose silence exceeds max(min_days, factor × their median gap).

Measured as of the day after the window. Team: the sum over barbers.
"""
from __future__ import annotations

import statistics as st

from ..context import WindowContext
from ..registry import metric

VERSION = 1


def overdue_regulars(ctx: WindowContext, barber: int) -> list[int]:
    from ...config import settings
    out = []
    for c, ds in ctx.barber_dates(barber).items():
        ds = sorted({d for d in ds if d < ctx.asof})
        if len(ds) < 3:
            continue
        g = st.median([(y - x).days for x, y in zip(ds, ds[1:])])
        if (ctx.asof - ds[-1]).days > max(settings.overdue_min_days, settings.overdue_gap_factor * g):
            out.append(c)
    return out


@metric("risk_n", "Overdue regulars", "", "down", help="As of the day after the window. Team: sum over barbers.", version=VERSION)
def risk_n(ctx, sc):
    if sc.barber_id:
        return len(overdue_regulars(ctx, sc.barber_id))
    return sum(len(overdue_regulars(ctx, b)) for b in ctx.team_barbers())
