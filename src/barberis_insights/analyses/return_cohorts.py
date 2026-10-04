"""Return cohorts: of first-time clients by month, how many came back?

Version 1. The clients whose first visit to the shop (all loaded history) falls in the window, grouped by the month of that
visit and credited to the barber of the first visit. `back_N_pct` is the share with another visit to the shop within N days
(30, 60, 90); `same_barber_90_pct` counts only a return to the same barber. A client counts toward a horizon only once that many
days have passed in the data, and the run is incomplete until every cohort has been observed for 90 days.
"""
from __future__ import annotations

import collections as C
import datetime as dt

from ._util import data_end, history_note, keep_scope, pct
from .base import AnalysisContext, finding
from .registry import analysis

DIRECTIONS = {"back_30_pct": "up", "back_60_pct": "up", "back_90_pct": "up", "same_barber_90_pct": "up"}
UNITS = {k: "%" for k in DIRECTIONS} | {"new_clients": ""}


@analysis("return_cohorts", "Return cohorts", "Of first-time clients by month, how many came back?", version=1)
def run(ctx: AnalysisContext) -> dict:
    end = data_end(ctx.ds) or ctx.t
    tracked = {b.altegio_id: b.key for b in ctx.barbers}
    groups = C.defaultdict(list)           # (scope, month) -> [(first visit, later visits)]
    for c, vs in ctx.ds.shop_history.items():
        first = vs[0]
        if ctx.f <= first.date <= ctx.t and first.barber in tracked:
            for scope in (tracked[first.barber], "team"):
                groups[(scope, first.date.strftime("%Y-%m"))].append((first, vs[1:]))
    rows, totals = [], C.defaultdict(lambda: C.Counter())
    for (scope, month), members in sorted(groups.items()):
        row = {"scope": scope, "month": month, "new_clients": len(members)}
        for n in (30, 60, 90):
            ok = [(f, later) for f, later in members if f.date + dt.timedelta(days=n) <= end]
            back = sum(1 for f, later in ok if any(0 < (v.date - f.date).days <= n for v in later))
            row[f"back_{n}_pct"] = pct(back, len(ok))
            totals[scope][f"ok{n}"] += len(ok); totals[scope][f"back{n}"] += back
        ok = [(f, later) for f, later in members if f.date + dt.timedelta(days=90) <= end]
        same = sum(1 for f, later in ok if any(0 < (v.date - f.date).days <= 90 and v.barber == f.barber for v in later))
        row["same_barber_90_pct"] = pct(same, len(ok)); totals[scope]["oks"] += len(ok); totals[scope]["same"] += same
        totals[scope]["new"] += len(members)
        rows.append(row)
    kpis = {sc: {"new_clients": c["new"], **{f"back_{n}_pct": pct(c[f"back{n}"], c[f"ok{n}"]) for n in (30, 60, 90)},
                 "same_barber_90_pct": pct(c["same"], c["oks"])} for sc, c in totals.items()}
    for b in ctx.barbers:
        kpis.setdefault(b.key, {"new_clients": 0})
    kpis.setdefault("team", {"new_clients": 0})
    complete = end >= ctx.t + dt.timedelta(days=90)
    findings = [f for f in [history_note(ctx)] if f]
    if not complete:
        findings.append(finding("window_incomplete", "info", "team", observed_until=str(end)))
    kpis, rows, findings = keep_scope(ctx.scope, kpis, rows, findings)
    return {"kpis": kpis, "directions": DIRECTIONS, "units": UNITS, "tables": {"cohorts": rows}, "findings": findings, "complete": complete,
            "context": {"observed_until": str(end), "history_from": str(ctx.ds.history_from)}}
