"""Average check: service revenue on visits ÷ number of visits."""
from __future__ import annotations

from .._common import visits
from ..registry import metric

VERSION = 1


@metric("check", "Average check", "₴", "up", version=VERSION)
def average_check(ctx, sc):
    v = visits(ctx, sc)
    return round(sum(a.cost for a in v) / len(v)) if v else None
