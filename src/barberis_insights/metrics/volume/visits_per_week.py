"""Visits per week. Barber: visits ÷ weeks actually worked. Team: visits ÷ calendar weeks."""
from __future__ import annotations

from .._common import r1, visits
from ..registry import metric

VERSION = 1


@metric("visits_wk", "Visits per week", "", "up", help="Barber: visits ÷ weeks actually worked. Team: visits ÷ calendar weeks.", version=VERSION)
def visits_per_week(ctx, sc):
    v = visits(ctx, sc)
    if not v:
        return None
    if sc.barber_id:
        wk = len({d.isocalendar()[:2] for d in ctx.sched(sc.barber_id)}) or 1
        return r1(len(v) / wk)
    return r1(len(v) / (ctx.length / 7))
