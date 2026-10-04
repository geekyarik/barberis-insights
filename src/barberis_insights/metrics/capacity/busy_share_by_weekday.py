"""Busy share on one weekday (util_d0 = Monday … util_d6 = Sunday), per barber; omitted with fewer than two scheduled days."""
from __future__ import annotations

from .._common import r1
from ..context import busy_minutes
from ..registry import DAYS, metric

VERSION = 1


def _weekday_util(i):
    def fn(ctx, sc):
        if not sc.barber_id:
            return None
        sched = {d: v for d, v in ctx.sched(sc.barber_id).items() if d.weekday() == i}
        if len(sched) < 2:
            return None
        sm = sum(e - s for v in sched.values() for s, e in v)
        bm = busy_minutes([a for a in ctx.appts(sc.barber_id) if a.date.weekday() == i], sched)
        return r1(100 * bm / sm) if sm else None
    return fn


for _i, _d in enumerate(DAYS):
    metric(f"util_d{_i}", f"Busy share on {_d}", "%", "up", scopes=("barber",), version=VERSION)(_weekday_util(_i))
