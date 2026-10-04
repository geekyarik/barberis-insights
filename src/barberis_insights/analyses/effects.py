"""A recurring Factor's effect, measured from the shop's own history by the `seasonality` analysis and linked to the factor.
The number is never typed in: with fewer than two earlier years the result says there is not enough history."""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from ..context import factors
from ..db.models import AnalysisRun, Factor
from . import service


def _week_span(a: dt.date, b: dt.date) -> tuple[dt.date, dt.date]:
    return a - dt.timedelta(days=a.weekday()), b + dt.timedelta(days=6 - b.weekday())


def estimate(s: Session, factor_id: int, today: dt.date | None = None, created_by: str = "cli") -> AnalysisRun:
    """Run `seasonality` over the factor's latest finished occurrence (its run-up included, widened to whole weeks) and link the run."""
    f = s.get(Factor, factor_id)
    if f is None:
        raise KeyError(f"unknown factor {factor_id}")
    if f.recurrence != "yearly":
        raise ValueError("only a yearly (recurring) factor gets its effect from the seasonality analysis")
    today = today or dt.date.today()
    done = [o for o in factors.occurrences(f, dt.date(today.year - 1, 1, 1), today) if o[1] < today - dt.timedelta(days=7)]
    if not done:
        raise ValueError("no finished occurrence yet")
    a, b = _week_span(*max(done, key=lambda o: o[1]))
    run = service.run(s, "seasonality", a, b, created_by=created_by)
    factors.link_effect(s, factor_id, run.id)
    return run


def summary(s: Session, f: Factor) -> dict | None:
    """What the linked run says: the seasonal index and how many earlier years it rests on, or why there is no number."""
    run = s.get(AnalysisRun, f.effect_run_id) if f.effect_run_id else None
    if run is None:
        return None
    k = run.result["kpis"]["team"]
    years = k.get("years_observed", 0)
    return {"run": run.id, "years_observed": years, "enough_history": years >= 2,
            "expected_visits_index": k.get("expected_visits_index") if years >= 2 else None,
            "expected_revenue_index": k.get("expected_revenue_index") if years >= 2 else None, "window": [str(run.window_from), str(run.window_to)]}
