"""New clients: how many new clients per day and per month, and what share of all clients?

Version 1. A new client is one whose first visit to the shop, in all loaded history, falls in the window; they are credited to
the barber of that first visit. The share is new clients ÷ the clients the barber saw in the window. Team = the tracked barbers
together; `shop_new_clients` also counts those whose first barber has left.
"""
from __future__ import annotations

import collections as C
import datetime as dt

from ._util import history_note, keep_scope, mondays, pct
from .base import AnalysisContext
from .registry import analysis

DIRECTIONS = {"new_clients": "up", "new_per_day": "up"}
UNITS = {"new_clients": "", "new_per_day": "", "new_share_pct": "%", "clients": ""}


@analysis("new_clients", "New clients", "How many new clients per day and month, and what share of all clients?", version=1)
def run(ctx: AnalysisContext) -> dict:
    hist, days = ctx.ds.shop_history, (ctx.t - ctx.f).days + 1
    tracked = {b.altegio_id: b.key for b in ctx.barbers}
    seen: dict[int, set] = C.defaultdict(set)
    new_by: dict[int, set] = C.defaultdict(set)
    shop_new, weekly, monthly = set(), C.defaultdict(lambda: C.defaultdict(int)), C.defaultdict(int)
    for c, vs in hist.items():
        for v in vs:
            if ctx.f <= v.date <= ctx.t:
                seen[v.barber].add(c)
        first = vs[0]
        if ctx.f <= first.date <= ctx.t:
            shop_new.add(c)
            monthly[first.date.strftime("%Y-%m")] += 1
            if first.barber in tracked:
                new_by[first.barber].add(c)
                weekly[tracked[first.barber]][first.date - dt.timedelta(days=first.date.weekday())] += 1
    kpis, rows = {}, []
    team_new = team_seen = 0
    for bid, key in tracked.items():
        n, m = len(new_by[bid]), len(seen[bid])
        team_new += n; team_seen += m
        kpis[key] = {"new_clients": n, "new_per_day": round(n / days, 2), "clients": m, "new_share_pct": pct(n, m)}
        for mon in mondays(ctx.f, ctx.t):
            rows.append({"scope": key, "week_start": str(mon), "new_clients": weekly[key][mon]})
    kpis["team"] = {"new_clients": team_new, "new_per_day": round(team_new / days, 2), "clients": team_seen, "new_share_pct": pct(team_new, team_seen),
                    "shop_new_clients": len(shop_new)}
    findings = [f for f in [history_note(ctx)] if f]
    kpis, rows, findings = keep_scope(ctx.scope, kpis, rows, findings)
    return {"kpis": kpis, "directions": DIRECTIONS, "units": UNITS, "tables": {"weeks": rows, "months": [{"month": m, "new_clients": n} for m, n in sorted(monthly.items())]},
            "findings": findings, "complete": True, "context": {"history_from": str(ctx.ds.history_from)}}
