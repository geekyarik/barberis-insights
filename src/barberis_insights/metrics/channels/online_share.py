"""Visits booked online: share of visits with the online flag."""
from __future__ import annotations

from .._common import visits
from ..registry import metric

VERSION = 1


@metric("online", "Visits booked online", "%", "up", version=VERSION)
def online_share(ctx, sc):
    v = visits(ctx, sc)
    return round(100 * sum(1 for a in v if a.online) / len(v)) if v else None
