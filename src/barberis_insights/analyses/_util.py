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


def data_end(ds) -> dt.date | None:
    return ds.arrived[-1].date if ds.arrived else None


def history_note(ctx, days: int = 180):
    """A finding when the window starts so close to the first loaded day that 'new' clients may only be unseen ones."""
    from .base import finding
    if ctx.f < ctx.ds.history_from + dt.timedelta(days=days):
        return finding("history_too_short", "info", "team", history_from=str(ctx.ds.history_from), window_from=str(ctx.f))
    return None
