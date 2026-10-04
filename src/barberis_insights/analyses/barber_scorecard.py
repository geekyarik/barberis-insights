"""Barber scorecard: how does each barber do on the key metrics, against last year and against the team?

Version 1. KPIs are every registered metric for each currently employed barber and the team over the window.
`vs_team` compares a barber's key metrics with the team's; `vs_last_year` compares each metric with the same weeks a year
earlier (52 weeks back, so weekdays line up), leaving out metrics that read client history, which does not reach back that far.
"""
from __future__ import annotations

import datetime as dt

from ..metrics import REGISTRY as METRICS
from ..metrics import compute_snapshot
from .base import AnalysisContext, finding
from .registry import analysis

KEY = ("util", "rph", "check", "online", "addon")
YEAR = dt.timedelta(weeks=52)


def _used() -> dict:
    return {k: m.version for k, m in METRICS.items()}


@analysis("barber_scorecard", "Barber scorecard", "How does each barber do on the key metrics, against last year and against the team?",
          version=1, metrics_used=_used, default_params={"cohort": None}, lenses=True)
def run(ctx: AnalysisContext) -> dict:
    cohort = tuple(dt.date.fromisoformat(x) for x in ctx.params["cohort"].split(":")) if ctx.params.get("cohort") else None
    snap = compute_snapshot(ctx.ds, ctx.f, ctx.t, cohort, ctx.lens_resolved)
    keep = lambda values: {k: v for k, v in values.items() if ctx.scope == "team" or k in (ctx.scope, "team")}
    kpis = keep(snap["values"])
    team = snap["values"]["team"]
    tables, findings = {"vs_team": [], "vs_last_year": []}, []

    for sc, vals in kpis.items():
        if sc == "team":
            continue
        for m in KEY:
            if vals.get(m) is not None and team.get(m) is not None:
                tables["vs_team"].append({"scope": sc, "metric": m, "value": vals[m], "team": team[m], "delta": round(vals[m] - team[m], 2)})
        if vals.get("util") is not None and team.get("util") is not None and vals["util"] < team["util"] - 10:
            findings.append(finding("busy_share_below_team", "warn", sc, value=vals["util"], team=team["util"]))
        if vals.get("rph") is not None and team.get("rph") and vals["rph"] < 0.8 * team["rph"]:
            findings.append(finding("revenue_per_hour_below_team", "warn", sc, value=vals["rph"], team=team["rph"]))

    f2, t2 = ctx.f - YEAR, ctx.t - YEAR
    last_year = None
    if any(f2 <= a.date <= t2 for a in ctx.ds.arrived):
        ly = compute_snapshot(ctx.ds, f2, t2, None, ctx.lens_for(f2, t2))["values"]
        last_year = {"window": [str(f2), str(t2)], "kpis": {sc: {k: v for k, v in vals.items() if not METRICS[k].needs_history}
                                                            for sc, vals in keep(ly).items()}}
        for sc, vals in last_year["kpis"].items():
            for m, old in vals.items():
                new = kpis.get(sc, {}).get(m)
                if new is not None:
                    tables["vs_last_year"].append({"scope": sc, "metric": m, "value": new, "last_year": old, "delta": round(new - old, 2)})
                    if m == "rph" and sc != "team" and old and new < 0.85 * old:
                        findings.append(finding("revenue_per_hour_down_vs_last_year", "warn", sc, value=new, last_year=old))

    return {"kpis": kpis, "directions": {k: m.direction for k, m in METRICS.items()}, "units": {k: m.unit for k, m in METRICS.items()},
            "tables": tables, "findings": findings, "complete": True, "last_year": last_year,
            "context": {"cohort_window": snap["cohort_window"], "names": {b.key: b.name for b in ctx.barbers}}}
