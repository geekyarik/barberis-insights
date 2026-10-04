"""Client sources: where did a barber's clients come from — returning, another barber of the shop, or new to the shop?

Version 1. Each client the barber saw in the window is typed by what they had done before their first visit to this barber in
the window, over all loaded history: `returning` (visited this barber before), `from_other` (visited the shop but never this
barber) or `new` (first visit to the shop). Team figures count client-barber pairs.
"""
from __future__ import annotations

import collections as C

from ._util import history_note, keep_scope, pct
from .base import AnalysisContext, finding
from .registry import analysis

DIRECTIONS = {"returning_pct": "up"}
UNITS = {"returning_pct": "%", "from_other_pct": "%", "new_pct": "%", "clients": ""}


@analysis("client_sources", "Client sources", "Where did a barber's clients come from: returning, other barbers, or new to the shop?", version=1)
def run(ctx: AnalysisContext) -> dict:
    hist = ctx.ds.shop_history
    kpis, rows, findings, tot = {}, [], [], C.Counter()
    for b in ctx.barbers:
        n = C.Counter()
        for c, vs in hist.items():
            mine = [v for v in vs if v.barber == b.altegio_id and ctx.f <= v.date <= ctx.t]
            if not mine:
                continue
            d0 = mine[0].date
            before = [v for v in vs if v.date < d0]
            kind = "returning" if any(v.barber == b.altegio_id for v in before) else "from_other" if before else "new"
            n[kind] += 1; n["clients"] += 1
        tot.update(n)
        kpis[b.key] = _k(n)
        rows.append({"scope": b.key, **{k: n[k] for k in ("clients", "returning", "from_other", "new")}})
        if n["clients"] >= 20 and kpis[b.key]["new_pct"] >= 40:
            findings.append(finding("depends_on_new_clients", "info", b.key, new_pct=kpis[b.key]["new_pct"], clients=n["clients"]))
    kpis["team"] = _k(tot)
    rows.append({"scope": "team", **{k: tot[k] for k in ("clients", "returning", "from_other", "new")}})
    if (h := history_note(ctx)):
        findings.append(h)
    kpis, rows, findings = keep_scope(ctx.scope, kpis, rows, findings)
    return {"kpis": kpis, "directions": DIRECTIONS, "units": UNITS, "tables": {"sources": rows}, "findings": findings, "complete": True,
            "context": {"history_from": str(ctx.ds.history_from)}}


def _k(n: C.Counter) -> dict:
    return {"clients": n["clients"], "returning_pct": pct(n["returning"], n["clients"]), "from_other_pct": pct(n["from_other"], n["clients"]),
            "new_pct": pct(n["new"], n["clients"])}
