"""Shapes a frozen report's content into what its template shows. No database access: a report renders from its own content."""
from __future__ import annotations

ADDITIVE = {"revenue", "visits", "visits_wk", "risk_n"}     # a barber's total against the team's total says nothing; shown without a team column
KEY = ["revenue", "visits", "util", "rph", "check", "online", "addon", "visits_wk", "new_share", "conv_new90", "risk_n"]
WEEK_COLS = ["week", "sched_h", "busy_h", "util", "visits", "no_show", "revenue", "avg_check", "clients", "new_to_shop", "from_other", "returning", "revenue_ly"]


def _diff(a, b):
    return None if a is None or b is None else round(a - b, 2)


def _signed(v, metric: str) -> str:
    """+1.5 for percentages and small numbers, +240 for money and counts."""
    if v is None or round(v, 1) == 0:
        return ""
    from ..metrics.registry import REGISTRY
    big = REGISTRY[metric].unit == "₴" or abs(v) >= 10
    return f"{v:+,.0f}".replace(",", " ") if big else f"{v:+.1f}"


def barber_book(c: dict) -> dict:
    sc = c["sections"]["scorecard"]
    ly = (c.get("last_year") or {}).get("kpis", {}).get(c["barber"], {})
    rows = []
    for m in KEY:
        if m not in sc["kpis"]:
            continue
        v, team = sc["kpis"][m], (None if m in ADDITIVE else sc["team"].get(m))
        rows.append({"metric": m, "value": v, "team": team, "d_team": _signed(_diff(v, team), m), "ly": ly.get(m), "d_ly": _signed(_diff(v, ly.get(m)), m)})
    return {"score_rows": rows, "week_cols": WEEK_COLS}


def team_comparison(c: dict) -> dict:
    return {"people": list(c["sections"]["scorecard"]["kpis"])}


VIEWS = {"barber_book": barber_book, "team_comparison": team_comparison}
