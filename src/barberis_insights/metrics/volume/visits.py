"""Visits: arrived appointments in the window. Team: the whole shop."""
from __future__ import annotations

from .._common import visits as _visits
from ..registry import metric

VERSION = 1


@metric("visits", "Visits", "", "up", help="Arrived appointments in the window. Team: the whole shop.", version=VERSION)
def visits(ctx, sc):
    v = _visits(ctx, sc)
    return len(v) if v else None
