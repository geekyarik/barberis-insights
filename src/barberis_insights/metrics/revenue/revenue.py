"""Revenue: the service price after discounts on the visits in the window. Not cash received (payments are not recorded in the CRM)."""
from __future__ import annotations

from .._common import visits
from ..registry import metric

VERSION = 1


@metric("revenue", "Revenue", "₴", "up", help="Service price after discounts on visits in the window. Team: the whole shop.", version=VERSION)
def revenue(ctx, sc):
    v = visits(ctx, sc)
    return round(sum(a.cost for a in v)) if v else None
