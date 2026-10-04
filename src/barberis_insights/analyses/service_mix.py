"""Service mix: which services and extras drive revenue?

Version 1. For each barber and the team (tracked barbers together) over the window: revenue and visits per service, its share of
revenue and its average price, with the 15 biggest services listed. Add-ons are the services the `addon` metric recognises.
"""
from __future__ import annotations

import collections as C

from ..config import settings
from ._util import keep_scope, pct
from .base import AnalysisContext, finding
from .registry import analysis

TOP = 15
DIRECTIONS = {"addon_revenue_pct": "up", "services_per_visit": "up", "top_service_pct": None}
UNITS = {"addon_revenue_pct": "%", "services_per_visit": "", "top_service_pct": "%", "revenue": "₴"}


def _addon(title: str) -> bool:
    return any(k in title for k in settings.addon_keywords)


@analysis("service_mix", "Service mix", "Which services and extras drive revenue?", version=1)
def run(ctx: AnalysisContext) -> dict:
    w = ctx.window()
    rev, cnt = C.defaultdict(lambda: C.defaultdict(float)), C.defaultdict(lambda: C.defaultdict(int))
    lines, visits = C.defaultdict(int), C.defaultdict(int)
    for b in ctx.barbers:
        for a in w.visits(b.altegio_id):
            for scope in (b.key, "team"):
                visits[scope] += 1
                lines[scope] += len(a.lines)
                for title, cost in a.lines:
                    rev[scope][title] += cost
                    cnt[scope][title] += 1
    kpis, rows, findings = {}, [], []
    for sc in [b.key for b in ctx.barbers] + ["team"]:
        total = sum(rev[sc].values())
        addon = sum(v for t, v in rev[sc].items() if _addon(t))
        ranked = sorted(rev[sc].items(), key=lambda kv: -kv[1])
        kpis[sc] = {"revenue": round(total), "addon_revenue_pct": pct(addon, total), "services_per_visit": round(lines[sc] / visits[sc], 2) if visits[sc] else None,
                    "top_service_pct": pct(ranked[0][1], total) if ranked else None}
        for t, v in ranked[:TOP]:
            rows.append({"scope": sc, "service": t, "visits": cnt[sc][t], "revenue": round(v), "share_pct": pct(v, total), "avg_price": round(v / cnt[sc][t]), "addon": _addon(t)})
        if sc != "team" and kpis[sc]["top_service_pct"] and kpis[sc]["top_service_pct"] >= 70:
            findings.append(finding("one_service_dominates", "info", sc, service=ranked[0][0], share_pct=kpis[sc]["top_service_pct"]))
    kpis, rows, findings = keep_scope(ctx.scope, kpis, rows, findings)
    return {"kpis": kpis, "directions": {k: v for k, v in DIRECTIONS.items() if v}, "units": UNITS, "tables": {"services": rows}, "findings": findings,
            "complete": True, "context": {"addon_keywords": list(settings.addon_keywords)}}
