"""Price and demand: did price changes reduce visits per work day?

Version 1. A barber's price is the weekly modal price of a plain "Чоловіча стрижка" visit (a single-service visit, 3+ a week). A
change is confirmed when a different price (5% or more away) holds for three weeks in a row; it is reported when its first week
falls in the window. Demand is visits per worked day (a day with a shift) in the 8 weeks before and the 8 weeks from the change.
Demand moves for many reasons, so each change is set against the other barbers over the same weeks: `net_demand_change_pct` is the
barber's change minus theirs. A change is `observed` once its 8 weeks after have happened.
"""
from __future__ import annotations

import collections as C
import datetime as dt
import statistics as st

from ._util import data_end, keep_scope, pct
from .base import AnalysisContext, finding
from .registry import analysis

BASE = "Чоловіча стрижка"
SPAN = 8                      # weeks either side of a change
MIN_PER_WEEK, MIN_STEP, HOLD = 3, 0.05, 3
MIN_DAYS = 10                 # worked days needed on each side
DIRECTIONS = {"changes": None, "avg_price_change_pct": None, "avg_net_demand_change_pct": "up"}
UNITS = {"avg_price_change_pct": "%", "avg_net_demand_change_pct": "%", "changes": ""}


def _monday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def weekly_price(visits) -> dict[dt.date, float]:
    by = C.defaultdict(list)
    for a in visits:
        if len(a.lines) == 1 and BASE in a.lines[0][0]:
            by[_monday(a.date)].append(a.lines[0][1])
    return {w: C.Counter(p).most_common(1)[0][0] for w, p in by.items() if len(p) >= MIN_PER_WEEK}


def changes(prices: dict[dt.date, float]) -> list[tuple[dt.date, float, float]]:
    """(first week of the new price, old price, new price)."""
    weeks, out = sorted(prices), []
    if not weeks:
        return out
    cur, i = prices[weeks[0]], 1
    while i < len(weeks):
        p = prices[weeks[i]]
        if abs(p / cur - 1) >= MIN_STEP:
            run = weeks[i:i + HOLD]
            if len(run) == HOLD and all(prices[w] == p for w in run) and all((b - a).days == 7 for a, b in zip(run, run[1:])):
                out.append((weeks[i], cur, p)); cur = p; i += HOLD
                continue
        i += 1
    return out


def _vpd(ctx: AnalysisContext, barbers: list[int], f: dt.date, t: dt.date):
    """(visits per worked day, worked days) for the barbers over f..t."""
    days = sum(1 for b in barbers for d, v in ctx.ds.slots.get(b, {}).items() if f <= d <= t and v)
    visits = sum(1 for a in ctx.ds.arrived if a.barber in barbers and f <= a.date <= t)
    return (visits / days if days else None), days


@analysis("price_demand", "Price and demand", "Did price changes reduce visits per work day?", version=1)
def run(ctx: AnalysisContext) -> dict:
    end = data_end(ctx.ds) or ctx.t
    tracked = {b.altegio_id: b.key for b in ctx.barbers}
    rows, findings, complete = [], [], True
    for bid, key in tracked.items():
        mine = [a for a in ctx.ds.arrived if a.barber == bid]
        for week, old, new in changes(weekly_price(mine)):
            if not (ctx.f <= week <= ctx.t):
                continue
            before = (week - dt.timedelta(weeks=SPAN), week - dt.timedelta(days=1))
            after = (week, week + dt.timedelta(weeks=SPAN) - dt.timedelta(days=1))
            observed = after[1] <= end
            others = [b for b in tracked if b != bid]
            v0, d0 = _vpd(ctx, [bid], *before)
            v1, d1 = _vpd(ctx, [bid], *after)
            o0, _ = _vpd(ctx, others, *before)
            o1, _ = _vpd(ctx, others, *after)
            ok = observed and v0 and v1 is not None and d0 >= MIN_DAYS and d1 >= MIN_DAYS
            demand = round(100 * (v1 / v0 - 1), 1) if ok else None
            theirs = round(100 * (o1 / o0 - 1), 1) if ok and o0 and o1 is not None else None
            row = {"scope": key, "change_week": str(week), "old_price": old, "new_price": new, "price_change_pct": round(100 * (new / old - 1), 1),
                   "visits_per_day_before": round(v0, 2) if v0 else None, "visits_per_day_after": round(v1, 2) if v1 is not None else None,
                   "days_before": d0, "days_after": d1, "demand_change_pct": demand, "others_demand_change_pct": theirs,
                   "net_demand_change_pct": round(demand - theirs, 1) if demand is not None and theirs is not None else None, "observed": bool(ok)}
            rows.append(row)
            complete &= observed
            if row["net_demand_change_pct"] is not None and row["price_change_pct"] > 0 and row["net_demand_change_pct"] <= -10:
                findings.append(finding("demand_fell_after_price_rise", "warn", key, change_week=row["change_week"], price_change_pct=row["price_change_pct"],
                                        net_demand_change_pct=row["net_demand_change_pct"]))
    kpis = {}
    for sc in [*tracked.values(), "team"]:
        mine = [r for r in rows if sc == "team" or r["scope"] == sc]
        net = [r["net_demand_change_pct"] for r in mine if r["net_demand_change_pct"] is not None]
        kpis[sc] = {"changes": len(mine), "avg_price_change_pct": round(st.mean(r["price_change_pct"] for r in mine), 1) if mine else None,
                    "avg_net_demand_change_pct": round(st.mean(net), 1) if net else None}
    kpis, rows, findings = keep_scope(ctx.scope, kpis, rows, findings)
    if not complete:
        findings.append(finding("window_incomplete", "info", "team", observed_until=str(end)))
    return {"kpis": kpis, "directions": {k: v for k, v in DIRECTIONS.items() if v}, "units": UNITS, "tables": {"price_changes": rows}, "findings": findings,
            "complete": complete, "context": {"service": BASE, "span_weeks": SPAN}}
