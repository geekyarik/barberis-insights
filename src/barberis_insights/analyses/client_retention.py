"""Client retention: of last period's clients, how many stayed, switched to another barber, or were lost?

Version 1. The base is every client with a visit to the barber in the window. They are followed for `lookahead_days`
after the window (default 90):
  stayed    visited the same barber again
  switched  did not, but visited another barber of the shop
  lost      did not come back to the shop at all
Clients are split into new (their first visit to the shop is in the window) and returning. Team figures count
client-barber pairs, like `risk_n`; `shop_retained_pct` counts each client once. Rows hold client ids only.
Windows whose follow-up has not fully happened are marked incomplete and are not compared.
"""
from __future__ import annotations

import collections as C
import datetime as dt

from .base import AnalysisContext, finding
from .registry import analysis

DIRECTIONS = {"stayed_pct": "up", "switched_pct": "down", "lost_pct": "down", "new_stayed_pct": "up", "returning_stayed_pct": "up",
              "shop_retained_pct": "up"}
UNITS = {k: "%" for k in DIRECTIONS} | {"clients": "", "new_clients": "", "returning_clients": ""}


def _pct(n: int, d: int):
    return round(100 * n / d, 1) if d else None


@analysis("client_retention", "Client retention", "Of last period's clients, how many stayed, switched to another barber, or were lost?",
          version=1, default_params={"lookahead_days": 90})
def run(ctx: AnalysisContext) -> dict:
    look = int(ctx.params["lookahead_days"])
    end = ctx.t + dt.timedelta(days=look)
    hist = ctx.ds.shop_history
    data_end = ctx.ds.arrived[-1].date if ctx.ds.arrived else ctx.t
    complete = data_end >= end

    base: dict[int, set] = C.defaultdict(set)           # barber id -> clients seen in the window
    for c, visits in hist.items():
        for v in visits:
            if ctx.f <= v.date <= ctx.t:
                base[v.barber].add(c)
    after = {c: [v for v in vs if ctx.t < v.date <= end] for c, vs in hist.items()}
    is_new = {c: hist[c][0].date >= ctx.f for c in hist}

    kpis, lost_rows, tracked = {}, [], {b.altegio_id: b.key for b in ctx.barbers}
    tot = C.Counter()
    shop_seen, shop_back = set(), set()
    for bid, key in tracked.items():
        n = C.Counter()
        for c in base.get(bid, ()):
            back = after.get(c, [])
            outcome = "stayed" if any(v.barber == bid for v in back) else "switched" if back else "lost"
            kind = "new" if is_new[c] else "returning"
            n["clients"] += 1; n[outcome] += 1; n[kind] += 1; n[f"{kind}_stayed"] += outcome == "stayed"
            shop_seen.add(c)
            if back:
                shop_back.add(c)
            if outcome == "lost":
                lost_rows.append({"scope": key, "client_id": c, "shop_visits": len(hist[c]), "last_visit": str(hist[c][-1].date)})
        tot.update(n)
        kpis[key] = _kpis(n)
    kpis["team"] = _kpis(tot) | {"shop_retained_pct": _pct(len(shop_back), len(shop_seen))}
    lost_rows.sort(key=lambda r: (r["scope"], -r["shop_visits"]))
    per_barber, capped = C.Counter(), []
    for r in lost_rows:                                  # the most loyal lost clients first, 50 per barber
        per_barber[r["scope"]] += 1
        if per_barber[r["scope"]] <= 50:
            capped.append(r)

    findings = []
    if not complete:
        findings.append(finding("window_incomplete", "info", "team", follow_up_ends=str(end), data_ends=str(data_end)))
    team_stay = kpis["team"]["stayed_pct"]
    for key, k in kpis.items():
        if key == "team":
            continue
        if k["clients"] >= 20 and k["stayed_pct"] is not None and team_stay is not None and k["stayed_pct"] < team_stay - 10:
            findings.append(finding("retention_below_team", "warn", key, stayed_pct=k["stayed_pct"], team=team_stay, clients=k["clients"]))
        if k["new_clients"] >= 10 and k["new_stayed_pct"] is not None and k["new_stayed_pct"] < 35:
            findings.append(finding("new_client_retention_low", "warn", key, new_stayed_pct=k["new_stayed_pct"], new_clients=k["new_clients"]))
    if ctx.scope != "team":
        kpis = {k: v for k, v in kpis.items() if k in (ctx.scope, "team")}
        findings = [f for f in findings if f["scope"] in (ctx.scope, "team")]
        capped = [r for r in capped if r["scope"] == ctx.scope]
    return {"kpis": kpis, "directions": DIRECTIONS, "units": UNITS, "tables": {"lost_clients": capped}, "findings": findings,
            "complete": complete, "context": {"lookahead_days": look, "follow_up_ends": str(end), "history_from": str(ctx.ds.history_from)}}


def _kpis(n: C.Counter) -> dict:
    return {"clients": n["clients"], "stayed_pct": _pct(n["stayed"], n["clients"]), "switched_pct": _pct(n["switched"], n["clients"]),
            "lost_pct": _pct(n["lost"], n["clients"]), "new_clients": n["new"], "new_stayed_pct": _pct(n["new_stayed"], n["new"]),
            "returning_clients": n["returning"], "returning_stayed_pct": _pct(n["returning_stayed"], n["returning"])}
