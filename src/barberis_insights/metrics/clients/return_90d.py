"""New clients back within 90 days.

Clients new to the shop whose first visit (to this barber) fell in the cohort window; the share with another visit
(to the same barber; team: to the shop) within 90 days. Omitted below 5 clients.
"""
from __future__ import annotations

from ..registry import metric

VERSION = 1


@metric("conv_new90", "New clients back within 90 days", "%", "up",
        help="Clients new to the shop whose first visit (to this barber) fell in the cohort window; % with another visit "
             "(to the same barber; team: to the shop) within 90 days. Omitted below 5 clients.", version=VERSION, needs_history=True)
def return_90d(ctx, sc):
    co_from, co_to = ctx.cohort_window
    if sc.barber_id:
        mine = ctx.barber_dates(sc.barber_id)
        coh = [c for c, ds in mine.items() if co_from <= min(ds) <= co_to and not ctx.ds.visited_before(c, min(ds))]
        if len(coh) < 5:
            return None
        return round(100 * sum(1 for c in coh if any(0 < (d - min(mine[c])).days <= 90 for d in mine[c])) / len(coh))
    hist = ctx.ds.metrics_history
    coh = [c for c, v in hist.items() if co_from <= v[0].date <= co_to]
    if len(coh) < 5:
        return None
    return round(100 * sum(1 for c in coh if any(0 < (a.date - hist[c][0].date).days <= 90 for a in hist[c])) / len(coh))
