"""Overdue regulars: clients with 3+ visits to the barber who have been silent longer than max(min_days, factor × their
median gap) and no longer than the lapsed limit (180 days). Beyond that a client is Lapsed, not Overdue.

Measured as of the day after the window. Team: the sum over barbers.

Version 2 (2026-10-04): added the 180-day cap that the glossary always had. Version 1 counted every regular who had ever
gone quiet, which only looked right while the data held 21 months.
"""
from __future__ import annotations

import statistics as st

from ...config import settings
from ..context import WindowContext
from ..registry import metric

VERSION = 2


def overdue_regulars(ctx: WindowContext, barber: int, cap_days: int | None = None) -> list[int]:
    out = []
    for c, ds in ctx.barber_dates(barber).items():
        ds = sorted({d for d in ds if d < ctx.asof})
        if len(ds) < 3:
            continue
        g = st.median([(y - x).days for x, y in zip(ds, ds[1:])])
        silent = (ctx.asof - ds[-1]).days
        if silent > max(settings.overdue_min_days, settings.overdue_gap_factor * g) and (cap_days is None or silent <= cap_days):
            out.append(c)
    return out


def _count(ctx, sc, cap_days):
    ids = [sc.barber_id] if sc.barber_id else ctx.team_barbers()
    return sum(len(overdue_regulars(ctx, b, cap_days)) for b in ids)


@metric("risk_n", "Overdue regulars", "", "down", help="As of the day after the window; silent up to 180 days, then Lapsed. Team: sum over barbers.", version=VERSION)
def risk_n(ctx, sc):
    return _count(ctx, sc, settings.lapsed_after_days)


def risk_n_v1(ctx, sc):
    """The version-1 definition (no cap), kept only to check the 2026-09-27 baseline."""
    return _count(ctx, sc, None)
