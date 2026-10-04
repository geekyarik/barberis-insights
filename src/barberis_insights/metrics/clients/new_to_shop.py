"""Clients new to the shop: of the barber's clients in the window, the share whose first visit to the shop was in it."""
from __future__ import annotations

from ..registry import metric

VERSION = 1


@metric("new_share", "Clients new to the shop", "%", "up", scopes=("barber",), version=VERSION)
def new_to_shop(ctx, sc):
    if not sc.barber_id:
        return None
    first = {}
    for a in ctx.visits(sc.barber_id):
        if a.client and a.client not in first:
            first[a.client] = a.date
    return round(100 * sum(1 for c, d in first.items() if not ctx.ds.visited_before(c, d)) / len(first)) if first else None
