"""Exclusive clients: how many regulars see only this barber? That is the risk if the barber leaves.

Version 1. Over the `lookback_days` (default 365) ending with the window, a regular is a client with 3+ visits to the barber and
a visit to the barber in the last 180 days; the regular is exclusive if they visited no other barber of the shop in that time.
`revenue_share_pct` is the exclusive regulars' spend with this barber ÷ all the barber's revenue in the period. The table lists the
25 exclusive regulars with the biggest spend, by client id only.
"""
from __future__ import annotations

import datetime as dt

from ._util import keep_scope, pct
from .base import AnalysisContext, finding
from .registry import analysis

DIRECTIONS = {"exclusive_pct": "down", "revenue_share_pct": "down"}
UNITS = {"exclusive_pct": "%", "revenue_share_pct": "%", "exclusive_revenue": "₴", "regulars": "", "exclusive_regulars": ""}
TOP = 25


@analysis("exclusive_clients", "Exclusive clients", "How many regulars see only this barber (risk if they leave)?", version=1,
          default_params={"lookback_days": 365})
def run(ctx: AnalysisContext) -> dict:
    start = ctx.t - dt.timedelta(days=int(ctx.params["lookback_days"]) - 1)
    recent = ctx.t - dt.timedelta(days=179)
    hist = {c: [v for v in vs if start <= v.date <= ctx.t] for c, vs in ctx.ds.shop_history.items()}
    kpis, rows, findings = {}, [], []
    tot_reg = tot_ex = 0
    tot_rev = tot_exrev = 0.0
    for b in ctx.barbers:
        bid = b.altegio_id
        revenue = sum(v.cost for vs in hist.values() for v in vs if v.barber == bid)
        reg = ex = 0
        exrev = 0.0
        mine = []
        for c, vs in hist.items():
            to_b = [v for v in vs if v.barber == bid]
            if len(to_b) >= 3 and to_b[-1].date >= recent:
                reg += 1
                if all(v.barber == bid for v in vs):
                    ex += 1
                    spend = sum(v.cost for v in to_b)
                    exrev += spend
                    mine.append({"scope": b.key, "client_id": c, "visits": len(to_b), "spend": round(spend), "last_visit": str(to_b[-1].date)})
        mine.sort(key=lambda r: -r["spend"])
        rows += mine[:TOP]
        kpis[b.key] = {"regulars": reg, "exclusive_regulars": ex, "exclusive_pct": pct(ex, reg), "exclusive_revenue": round(exrev),
                       "revenue_share_pct": pct(exrev, revenue)}
        tot_reg += reg; tot_ex += ex; tot_rev += revenue; tot_exrev += exrev
        k = kpis[b.key]
        if reg >= 10 and k["exclusive_pct"] >= 70 and (k["revenue_share_pct"] or 0) >= 40:
            findings.append(finding("exclusive_dependence_high", "warn", b.key, exclusive_pct=k["exclusive_pct"], revenue_share_pct=k["revenue_share_pct"]))
    kpis["team"] = {"regulars": tot_reg, "exclusive_regulars": tot_ex, "exclusive_pct": pct(tot_ex, tot_reg), "exclusive_revenue": round(tot_exrev),
                    "revenue_share_pct": pct(tot_exrev, tot_rev)}
    kpis, rows, findings = keep_scope(ctx.scope, kpis, rows, findings)
    return {"kpis": kpis, "directions": DIRECTIONS, "units": UNITS, "tables": {"exclusive": rows}, "findings": findings, "complete": True,
            "context": {"lookback_from": str(start)}}
