"""Small helpers shared by analysis modules."""
from __future__ import annotations

import datetime as dt


def pct(n, d, digits: int = 1):
    return round(100 * n / d, digits) if d else None


def keep_scope(scope: str, kpis: dict, rows: list[dict] | None = None, findings: list[dict] | None = None):
    """Cut a team-wide result down to one barber (plus the team column for reference)."""
    if scope == "team":
        return kpis, rows, findings
    return ({k: v for k, v in kpis.items() if k in (scope, "team")},
            [r for r in rows if r.get("scope") in (scope, "team")] if rows is not None else None,
            [f for f in findings if f["scope"] in (scope, "team")] if findings is not None else None)


def mondays(f: dt.date, t: dt.date):
    d = f - dt.timedelta(days=f.weekday())
    while d <= t:
        yield d
        d += dt.timedelta(days=7)
