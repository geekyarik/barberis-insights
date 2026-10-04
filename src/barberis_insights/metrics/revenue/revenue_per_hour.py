"""Revenue per scheduled hour: service revenue on visits ÷ scheduled hours."""
from __future__ import annotations

from ..context import Scope, WindowContext
from ..registry import metric

VERSION = 1


@metric("rph", "Revenue per scheduled hour", "₴", "up", help="Service revenue on visits ÷ scheduled hours.", version=VERSION)
def revenue_per_hour(ctx: WindowContext, sc: Scope):
    ids = [sc.barber_id] if sc.barber_id else ctx.team_barbers()
    sm = sum(ctx.sched_minutes(b) for b in ids)
    rev = sum(a.cost for b in ids for a in ctx.visits(b))
    return round(rev / (sm / 60)) if sm else None
