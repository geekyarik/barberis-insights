"""Built-in metrics. Definitions match the 2026-09-27 baseline (see tests/test_metrics_baseline.py)."""
from __future__ import annotations

import statistics as st

from .context import Scope, WindowContext, busy_minutes, is_addon
from .registry import DAYS, metric


def _r1(x):
    return None if x is None else round(x, 1)


def _team_visits(ctx: WindowContext):
    return ctx.visits(None)  # whole shop, all barbers


@metric("util", "Busy share of scheduled time", "%", "up", help="Booked minutes inside scheduled slots ÷ scheduled minutes; no-shows count as booked.")
def util(ctx: WindowContext, sc: Scope):
    ids = [sc.barber_id] if sc.barber_id else ctx.team_barbers()
    sm = sum(ctx.sched_minutes(b) for b in ids)
    return _r1(100 * sum(ctx.busy(b) for b in ids) / sm) if sm else None


@metric("rph", "Revenue per scheduled hour", "₴", "up", help="Service revenue on visits ÷ scheduled hours.")
def rph(ctx: WindowContext, sc: Scope):
    ids = [sc.barber_id] if sc.barber_id else ctx.team_barbers()
    sm = sum(ctx.sched_minutes(b) for b in ids)
    rev = sum(a.cost for b in ids for a in ctx.visits(b))
    return round(rev / (sm / 60)) if sm else None


def _visits(ctx, sc):
    return ctx.visits(sc.barber_id) if sc.barber_id else _team_visits(ctx)


@metric("online", "Visits booked online", "%", "up")
def online(ctx, sc):
    v = _visits(ctx, sc)
    return round(100 * sum(1 for a in v if a.online) / len(v)) if v else None


@metric("addon", "Visits with an add-on", "%", "up", help="Massage, camouflage, waxing or brows on the visit.")
def addon(ctx, sc):
    v = _visits(ctx, sc)
    return _r1(100 * sum(1 for a in v if is_addon(a)) / len(v)) if v else None


@metric("check", "Average check", "₴", "up")
def check(ctx, sc):
    v = _visits(ctx, sc)
    return round(sum(a.cost for a in v) / len(v)) if v else None


@metric("visits_wk", "Visits per week", "", "up", help="Barber: visits ÷ weeks actually worked. Team: visits ÷ calendar weeks.")
def visits_wk(ctx, sc):
    v = _visits(ctx, sc)
    if not v:
        return None
    if sc.barber_id:
        wk = len({d.isocalendar()[:2] for d in ctx.sched(sc.barber_id)}) or 1
        return _r1(len(v) / wk)
    return _r1(len(v) / (ctx.length / 7))


@metric("new_share", "Clients new to the shop", "%", "up", scopes=("barber",))
def new_share(ctx, sc):
    if not sc.barber_id:
        return None
    first = {}
    for a in ctx.visits(sc.barber_id):
        if a.client and a.client not in first:
            first[a.client] = a.date
    return round(100 * sum(1 for c, d in first.items() if not ctx.ds.visited_before(c, d)) / len(first)) if first else None


def _weekday_util(i):
    def fn(ctx, sc):
        if not sc.barber_id:
            return None
        sched = {d: v for d, v in ctx.sched(sc.barber_id).items() if d.weekday() == i}
        if len(sched) < 2:
            return None
        sm = sum(e - s for v in sched.values() for s, e in v)
        bm = busy_minutes([a for a in ctx.appts(sc.barber_id) if a.date.weekday() == i], sched)
        return _r1(100 * bm / sm) if sm else None
    return fn


for _i, _d in enumerate(DAYS):
    metric(f"util_d{_i}", f"Busy share on {_d}", "%", "up", scopes=("barber",))(_weekday_util(_i))


@metric("conv_new90", "New clients back within 90 days", "%", "up",
        help="Clients new to the shop whose first visit (to this barber) fell in the cohort window; % with another visit "
             "(to the same barber; team: to the shop) within 90 days. Omitted below 5 clients.")
def conv_new90(ctx, sc):
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


def overdue_regulars(ctx: WindowContext, barber: int) -> list[int]:
    """Clients with 3+ visits to the barber whose silence exceeds max(min_days, factor × their median gap)."""
    from ..config import settings
    out = []
    for c, ds in ctx.barber_dates(barber).items():
        ds = sorted({d for d in ds if d < ctx.asof})
        if len(ds) < 3:
            continue
        g = st.median([(y - x).days for x, y in zip(ds, ds[1:])])
        if (ctx.asof - ds[-1]).days > max(settings.overdue_min_days, settings.overdue_gap_factor * g):
            out.append(c)
    return out


@metric("risk_n", "Overdue regulars", "", "down", help="As of the day after the window. Team: sum over barbers.")
def risk_n(ctx, sc):
    if sc.barber_id:
        return len(overdue_regulars(ctx, sc.barber_id))
    return sum(len(overdue_regulars(ctx, b)) for b in ctx.team_barbers())
