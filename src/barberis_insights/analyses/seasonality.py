"""Seasonality: how do visits and revenue in recurring periods differ from each year's own average?

Version 1. Shop-wide weekly visits and revenue, for every full ISO week with data. Each week is divided by the mean of its own
year's full weeks (a year needs 40 or more), giving an index: 1.0 is an average week, 1.3 a busy one. For the weeks of the window
the run reports the mean index of the *earlier* years (`expected_*_index`, with how many years that rests on) and, where the current
year has the weeks, the actual one. A year's growth within the year is not removed, so an index is a guide, not a forecast. The current year, which has no full year yet, is measured against the trailing 52 full weeks. With
fewer than two earlier years the result says there is not enough history. This is what gives a recurring Factor its effect.
"""
from __future__ import annotations

import collections as C
import datetime as dt
import statistics as st

from ._util import data_end
from .base import AnalysisContext, finding
from .registry import analysis

MIN_YEAR_WEEKS = 40
HIGH, LOW = 1.10, 0.90
DIRECTIONS: dict = {}
UNITS = {"expected_visits_index": "", "expected_revenue_index": "", "actual_visits_index": "", "actual_revenue_index": "", "years_observed": ""}


def weekly(ds) -> dict[tuple[int, int], tuple[int, float]]:
    """(iso year, iso week) -> (visits, revenue) for full weeks only."""
    if not ds.arrived:
        return {}
    first, last = ds.arrived[0].date, data_end(ds)
    acc = C.defaultdict(lambda: [0, 0.0])
    for a in ds.arrived:
        y, w, _ = a.date.isocalendar()
        acc[(y, w)][0] += 1
        acc[(y, w)][1] += a.cost
    out = {}
    for (y, w), (n, rev) in acc.items():
        monday = dt.date.fromisocalendar(y, w, 1)
        if monday >= first and monday + dt.timedelta(days=6) <= last:
            out[(y, w)] = (n, rev)
    return out


@analysis("seasonality", "Seasonality", "How do visits and revenue in recurring periods differ from each year's own average?", version=1)
def run(ctx: AnalysisContext) -> dict:
    series = weekly(ctx.ds)
    by_year = C.defaultdict(dict)
    for (y, w), v in series.items():
        by_year[y][w] = v
    mean = {y: (st.mean(v[0] for v in ws.values()), st.mean(v[1] for v in ws.values())) for y, ws in by_year.items() if len(ws) >= MIN_YEAR_WEEKS}
    cur_year = ctx.t.isocalendar()[0]
    recent = [series[k] for k in sorted(series)[-52:]]
    if cur_year not in mean and len(recent) == 52:
        mean[cur_year] = (st.mean(v[0] for v in recent), st.mean(v[1] for v in recent))      # trailing 52 full weeks
    weeks = sorted({(m.isocalendar()[1]) for m in [ctx.f + dt.timedelta(days=7 * i) for i in range((ctx.t - ctx.f).days // 7 + 1)]})
    rows, expected, actual = [], {"visits": [], "revenue": []}, {"visits": [], "revenue": []}
    years_seen = set()
    for w in weeks:
        for y in sorted(by_year):
            if y not in mean or w not in by_year[y]:
                continue
            n, rev = by_year[y][w]
            vi, ri = n / mean[y][0], rev / mean[y][1]
            rows.append({"scope": "team", "iso_week": w, "year": y, "visits": n, "revenue": round(rev), "visits_index": round(vi, 2), "revenue_index": round(ri, 2)})
            bucket = actual if y == cur_year else expected
            bucket["visits"].append(vi); bucket["revenue"].append(ri)
            if y != cur_year:
                years_seen.add(y)
    kpis = {"years_observed": len(years_seen)}
    if expected["visits"]:
        kpis |= {"expected_visits_index": round(st.mean(expected["visits"]), 2), "expected_revenue_index": round(st.mean(expected["revenue"]), 2)}
    if actual["visits"]:
        kpis |= {"actual_visits_index": round(st.mean(actual["visits"]), 2), "actual_revenue_index": round(st.mean(actual["revenue"]), 2)}
    findings = []
    if len(years_seen) < 2:
        findings.append(finding("not_enough_history", "info", "team", years_observed=len(years_seen)))
    elif kpis.get("expected_visits_index", 1) >= HIGH:
        findings.append(finding("season_high", "info", "team", expected_visits_index=kpis["expected_visits_index"], years=len(years_seen)))
    elif kpis.get("expected_visits_index", 1) <= LOW:
        findings.append(finding("season_low", "info", "team", expected_visits_index=kpis["expected_visits_index"], years=len(years_seen)))
    return {"kpis": {"team": kpis}, "directions": DIRECTIONS, "units": UNITS, "tables": {"weeks": rows}, "findings": findings, "complete": True,
            "context": {"min_year_weeks": MIN_YEAR_WEEKS, "years_with_a_mean": sorted(mean)}}
