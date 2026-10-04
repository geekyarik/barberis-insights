"""Small helpers shared by metric modules."""
from __future__ import annotations

from .context import Scope, WindowContext


def r1(x):
    return None if x is None else round(x, 1)


def visits(ctx: WindowContext, sc: Scope):
    """Arrived visits for the scope: the barber's, or the whole shop's for the team."""
    return ctx.visits(sc.barber_id) if sc.barber_id else ctx.visits(None)
