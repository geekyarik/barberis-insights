"""Weekday pattern: which days and hours are full or empty, per barber?

Version 1. Busy share (booked minutes inside scheduled slots, no-shows counted as booked, like the `util` metric) by weekday
and by hour of the day, from the barber's shifts and bookings in the window. A weekday with fewer than two scheduled days is
not judged.
"""
from __future__ import annotations

import collections as C

from ._util import keep_scope, pct
from .base import AnalysisContext, finding
from .registry import analysis

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
EMPTY, FULL = 30.0, 90.0


def _split(lo: int, hi: int):
    """Minutes of [lo, hi) per clock hour."""
    h = lo // 60
    while h * 60 < hi:
        yield h, min(hi, (h + 1) * 60) - max(lo, h * 60)
        h += 1


@analysis("weekday_pattern", "Weekday pattern", "Which days and hours are full or empty, per barber?", version=1)
def run(ctx: AnalysisContext) -> dict:
    w = ctx.window()
    sched = C.defaultdict(lambda: C.defaultdict(float))     # scope -> weekday -> minutes
    busy = C.defaultdict(lambda: C.defaultdict(float))
    days = C.defaultdict(lambda: C.defaultdict(int))
    hsched = C.defaultdict(lambda: C.defaultdict(float))    # scope -> hour -> minutes
    hbusy = C.defaultdict(lambda: C.defaultdict(float))
    visits = C.defaultdict(lambda: C.defaultdict(int))
    revenue = C.defaultdict(lambda: C.defaultdict(float))
    for b in ctx.barbers:
        for scope in (b.key, "team"):
            for d, slots in w.sched(b.altegio_id).items():
                days[scope][d.weekday()] += 1
                for x, y in slots:
                    sched[scope][d.weekday()] += y - x
                    for h, m in _split(x, y):
                        hsched[scope][h] += m
            for a in w.appts(b.altegio_id):
                for x, y in w.sched(b.altegio_id).get(a.date, ()):
                    lo, hi = max(a.start, x), min(a.start + a.duration, y)
                    if hi > lo:
                        busy[scope][a.date.weekday()] += hi - lo
                        for h, m in _split(lo, hi):
                            hbusy[scope][h] += m
                if a.status == "arrived":
                    visits[scope][a.date.weekday()] += 1
                    revenue[scope][a.date.weekday()] += a.cost
    scopes = [b.key for b in ctx.barbers] + ["team"]
    kpis, rows, findings = {}, [], []
    for sc in scopes:
        kpis[sc] = {}
        for i, name in enumerate(DAYS):
            u = pct(busy[sc][i], sched[sc][i])
            if days[sc][i] >= 2:
                kpis[sc][f"util_{name}"] = u
            rows.append({"scope": sc, "table": "weekday", "weekday": i, "days_worked": days[sc][i], "sched_h": round(sched[sc][i] / 60, 1),
                         "busy_h": round(busy[sc][i] / 60, 1), "util": u, "visits": visits[sc][i], "revenue": round(revenue[sc][i])})
            if sc != "team" and u is not None and days[sc][i] >= 2:
                if u < EMPTY:
                    findings.append(finding("weekday_empty", "warn", sc, weekday=name, util=u, days_worked=days[sc][i]))
                elif u >= FULL:
                    findings.append(finding("weekday_full", "info", sc, weekday=name, util=u))
        for h in sorted(hsched[sc]):
            rows.append({"scope": sc, "table": "hour", "hour": h, "sched_h": round(hsched[sc][h] / 60, 1), "busy_h": round(hbusy[sc][h] / 60, 1),
                         "util": pct(hbusy[sc][h], hsched[sc][h])})
    kpis, rows, findings = keep_scope(ctx.scope, kpis, rows, findings)
    return {"kpis": kpis, "directions": {f"util_{d}": "up" for d in DAYS}, "units": {f"util_{d}": "%" for d in DAYS},
            "tables": {"weekday": [r for r in rows if r["table"] == "weekday"], "hour": [r for r in rows if r["table"] == "hour"]},
            "findings": findings, "complete": True, "context": {"empty_below": EMPTY, "full_from": FULL}}
