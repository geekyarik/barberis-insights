"""Weekly book: week by week, revenue against last year, busy share, clients by type and the visit ledger.

Version 1. One row per barber per ISO week in the window (and one for the team, the tracked barbers together, so its revenue
can differ from the shop-wide `revenue` metric when former barbers worked). Clients are typed from all loaded history:
new to the shop, coming from another barber of the shop, or returning to this barber. The last-year columns are the same ISO
week of the year before.
"""
from __future__ import annotations

import collections as C

from ..metrics.weekly import weekly_rows
from ._util import keep_scope, pct
from .base import AnalysisContext, finding
from .registry import analysis

SUMS = ("days", "sched_h", "busy_h", "visits", "no_show", "revenue", "visits_ly", "revenue_ly", "clients", "new_to_shop", "from_other", "returning")
DIRECTIONS = {"revenue": "up", "visits": "up", "util": "up", "revenue_vs_ly_pct": "up", "no_show_pct": "down"}
UNITS = {"revenue": "₴", "visits": "", "util": "%", "revenue_vs_ly_pct": "%", "no_show_pct": "%"}


def _week_row(r: dict) -> dict:
    r = dict(r)
    r["util"] = pct(r["busy_h"], r["sched_h"])
    r["avg_check"] = round(r["revenue"] / r["visits"]) if r["visits"] else None
    r["rev_per_sched_h"] = round(r["revenue"] / r["sched_h"]) if r["sched_h"] else None
    return r


@analysis("weekly_book", "Weekly book", "Week by week: revenue against last year, busy share, clients by type, ledger.", version=1)
def run(ctx: AnalysisContext) -> dict:
    rows, per_week = [], C.defaultdict(lambda: dict.fromkeys(SUMS, 0))
    for b in ctx.barbers:
        for r in weekly_rows(ctx.ds, b.altegio_id, ctx.f, ctx.t, full=True):
            rows.append({"scope": b.key} | r)
            tot = per_week[(r["year"], r["week"], r["start"])]
            for k in SUMS:
                tot[k] += r[k] or 0
    team_rows = [_week_row({"scope": "team", "year": y, "week": w, "start": st} | tot) for (y, w, st), tot in sorted(per_week.items(), key=lambda x: x[0][2])]
    kpis, findings = {}, []
    for scope in [b.key for b in ctx.barbers] + ["team"]:
        mine = [r for r in (rows if scope != "team" else team_rows) if r["scope"] == scope]
        tot = {k: sum(r[k] or 0 for r in mine) for k in SUMS}
        kpis[scope] = {"revenue": round(tot["revenue"]), "visits": tot["visits"], "util": pct(tot["busy_h"], tot["sched_h"]),
                       "revenue_vs_ly_pct": round(100 * (tot["revenue"] / tot["revenue_ly"] - 1), 1) if tot["revenue_ly"] else None,
                       "no_show_pct": pct(tot["no_show"], tot["visits"] + tot["no_show"])}
        k = kpis[scope]
        if k["revenue_vs_ly_pct"] is not None and k["revenue_vs_ly_pct"] <= -15:
            findings.append(finding("revenue_below_last_year", "warn", scope, revenue_vs_ly_pct=k["revenue_vs_ly_pct"]))
        if k["no_show_pct"] is not None and k["no_show_pct"] >= 10 and tot["visits"] >= 20:
            findings.append(finding("no_shows_high", "warn", scope, no_show_pct=k["no_show_pct"]))
    all_rows = rows + team_rows
    kpis, all_rows, findings = keep_scope(ctx.scope, kpis, all_rows, findings)
    return {"kpis": kpis, "directions": DIRECTIONS, "units": UNITS, "tables": {"weeks": all_rows}, "findings": findings, "complete": True,
            "context": {"history_from": str(ctx.ds.history_from), "team_means": "the tracked barbers together"}}
