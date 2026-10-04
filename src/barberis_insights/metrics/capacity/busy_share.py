"""Busy share of scheduled time: booked minutes inside scheduled slots ÷ scheduled minutes; no-shows count as booked."""
from __future__ import annotations

from .._common import r1
from ..context import Scope, WindowContext
from ..registry import metric

VERSION = 1


@metric("util", "Busy share of scheduled time", "%", "up", help="Booked minutes inside scheduled slots ÷ scheduled minutes; no-shows count as booked.", version=VERSION)
def busy_share(ctx: WindowContext, sc: Scope):
    ids = [sc.barber_id] if sc.barber_id else ctx.team_barbers()
    sm = sum(ctx.sched_minutes(b) for b in ids)
    return r1(100 * sum(ctx.busy(b) for b in ids) / sm) if sm else None
