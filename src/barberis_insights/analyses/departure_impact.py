"""Departure impact: when a barber left, how many of their regulars stayed with the shop, and with whom?

Version 1. Needs `barber`, the key of a barber who has left (the only analysis that reports on a former barber, because that is
its question). Their regulars are the clients with 3+ visits to them in the year before they left. The window is the
observation period after the departure: a regular `stayed` if they visited the shop in it, with the barber they saw most;
otherwise `lost`. The run is incomplete until the window has fully happened and starts after the departure.
"""
from __future__ import annotations

import collections as C
import datetime as dt

from ._util import data_end, pct
from .base import AnalysisContext, finding
from .registry import analysis

DIRECTIONS = {"stayed_pct": "up", "lost_pct": "down"}
UNITS = {"stayed_pct": "%", "lost_pct": "%", "regulars": ""}


@analysis("departure_impact", "Departure impact", "When a barber left, how many of their regulars stayed with the shop, and with whom?", version=1,
          default_params={"barber": None})
def run(ctx: AnalysisContext) -> dict:
    key = ctx.params.get("barber")
    gone = next((b for b in ctx.ds.former if b.key == key), None)
    if gone is None:
        raise ValueError(f"param 'barber' must be the key of a barber who has left; got {key!r}")
    names = {b.altegio_id: b.name for b in [*ctx.ds.barbers, *ctx.ds.former]}
    left = gone.left or max((a.date for a in ctx.ds.arrived if a.barber == gone.altegio_id), default=ctx.f)
    start = left - dt.timedelta(days=365)
    regulars = [c for c, vs in ctx.ds.shop_history.items() if sum(1 for v in vs if v.barber == gone.altegio_id and start <= v.date <= left) >= 3]
    stayed, receiving = 0, C.Counter()
    for c in regulars:
        after = [v for v in ctx.ds.shop_history[c] if ctx.f <= v.date <= ctx.t and v.barber != gone.altegio_id]
        if after:
            stayed += 1
            receiving[C.Counter(v.barber for v in after).most_common(1)[0][0]] += 1
    n = len(regulars)
    end = data_end(ctx.ds) or ctx.t
    complete = end >= ctx.t and ctx.f > left
    findings = [] if complete else [finding("window_incomplete", "info", "team", left=str(left), data_ends=str(end))]
    rows = [{"scope": "team", "receiving_barber": names.get(b, str(b)), "current": b in {x.altegio_id for x in ctx.ds.barbers}, "clients": c, "pct": pct(c, n)}
            for b, c in receiving.most_common()]
    return {"kpis": {"team": {"regulars": n, "stayed_pct": pct(stayed, n), "lost_pct": pct(n - stayed, n)}}, "directions": DIRECTIONS, "units": UNITS,
            "tables": {"receiving": rows}, "findings": findings, "complete": complete,
            "context": {"barber": gone.key, "name": gone.name, "left": str(left), "regulars_from": str(start)}}
