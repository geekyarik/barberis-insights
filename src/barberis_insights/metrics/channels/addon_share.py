"""Visits with an add-on: massage, camouflage, waxing or brows on the visit."""
from __future__ import annotations

from .._common import r1, visits
from ..context import is_addon
from ..registry import metric

VERSION = 1


@metric("addon", "Visits with an add-on", "%", "up", help="Massage, camouflage, waxing or brows on the visit.", version=VERSION)
def addon_share(ctx, sc):
    v = visits(ctx, sc)
    return r1(100 * sum(1 for a in v if is_addon(a)) / len(v)) if v else None
