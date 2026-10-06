"""Overdue regulars: who is overdue, and how much are they worth?

Version 1. As of the day after the window, the regulars of each barber (3+ visits to that barber) who have been silent
longer than their usual gap allows and no longer than 180 days (then they are Lapsed). Uses the same rule as the `risk_n` metric.
`value_at_stake` is the clients' lifetime spend at the shop. The table lists the 25 highest-priority clients per barber by id only.
"""
from __future__ import annotations

import datetime as dt

from ..clients.profile import build_facts
from ..clients.risk import priority
from ..config import settings
from ..metrics import REGISTRY as METRICS
from ..metrics.clients.overdue_regulars import overdue_regulars
from .base import AnalysisContext, finding
from .registry import analysis

DIRECTIONS = {"overdue": "down", "value_at_stake": "down", "avg_days_silent": "down"}
UNITS = {"overdue": "", "value_at_stake": "₴", "avg_days_silent": ""}
TOP = 25


@analysis("overdue_regulars", "Overdue regulars", "Who is overdue, and how much are they worth?", version=1,
          metrics_used=lambda: {"risk_n": METRICS["risk_n"].version})
def run(ctx: AnalysisContext) -> dict:
    w = ctx.window()
    asof = ctx.t + dt.timedelta(days=1)
    facts = build_facts(ctx.ds, asof)
    kpis, rows, findings = {}, [], []
    all_ids, all_value, all_days = 0, 0.0, 0
    for b in ctx.barbers:
        ids = overdue_regulars(w, b.altegio_id, settings.lapsed_after_days)
        dates = w.barber_dates(b.altegio_id)
        mine = []
        for c in ids:
            f = facts.get(c)
            if f is None:
                continue
            last = max(d for d in dates[c] if d < asof)
            mine.append({"scope": b.key, "client_id": c, "shop_visits": f.visits, "visits_to_barber": len([d for d in dates[c] if d < asof]),
                         "median_gap_days": f.median_gap, "days_silent": (asof - last).days, "lifetime_spend": round(f.spend),
                         "priority": priority(f)[0]})
        mine.sort(key=lambda r: -r["priority"])
        value = sum(r["lifetime_spend"] for r in mine)
        days = sum(r["days_silent"] for r in mine)
        kpis[b.key] = {"overdue": len(mine), "value_at_stake": value, "avg_days_silent": round(days / len(mine)) if mine else None}
        all_ids += len(mine); all_value += value; all_days += days
        rows += mine[:TOP]
        if len(mine) >= 10 and value and sum(r["lifetime_spend"] for r in mine[:10]) > 0.5 * value:
            findings.append(finding("value_concentrated", "info", b.key, top10_share_pct=round(100 * sum(r["lifetime_spend"] for r in mine[:10]) / value)))
    kpis["team"] = {"overdue": all_ids, "value_at_stake": round(all_value), "avg_days_silent": round(all_days / all_ids) if all_ids else None}
    if ctx.scope != "team":
        kpis = {k: v for k, v in kpis.items() if k in (ctx.scope, "team")}
        rows = [r for r in rows if r["scope"] == ctx.scope]
        findings = [f for f in findings if f["scope"] == ctx.scope]
    return {"kpis": kpis, "directions": DIRECTIONS, "units": UNITS, "tables": {"overdue": rows}, "findings": findings, "complete": True,
            "context": {"asof": str(asof), "lapsed_after_days": settings.lapsed_after_days}}
