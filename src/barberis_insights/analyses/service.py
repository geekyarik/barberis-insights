"""The Analyses service: the only way other modules run, read or compare analyses. It owns the `analysis_runs` table."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..context import factors
from ..db.models import Appointment, AnalysisRun, SyncRun
from ..ingest.status import data_status
from ..metrics import Dataset
from ..metrics.measurements import save_measurement
from . import _discover
from .base import AnalysisContext, validate_window
from .compare import compare_runs, not_comparable
from .registry import REGISTRY, catalog

_discover()  # registers the analysis modules

__all__ = ["run", "get", "list_runs", "latest", "previous_comparable", "compare", "compare_with_previous", "catalog", "REGISTRY"]


def _fingerprint(s: Session) -> dict:
    """What data the run saw: enough to tell whether two runs used the same facts."""
    return {"appointments": s.scalar(select(func.count(Appointment.id))),
            "last_appointment_date": str(s.scalar(select(func.max(Appointment.date)))),
            "last_sync_run": s.scalar(select(func.max(SyncRun.id)).where(SyncRun.status == "ok"))}


def run(s: Session, key: str, f: dt.date, t: dt.date, scope: str = "team", lens: str = "raw", params: dict | None = None,
        created_by: str = "cli", ds: Dataset | None = None, label: str | None = None) -> AnalysisRun:
    """Run an analysis and store the result as a new, immutable run.

    Pass `label` on a barber_scorecard run to also store its metric values as a measurement (what Goals read)."""
    if key not in REGISTRY:
        raise KeyError(f"unknown analysis {key!r}; known: {', '.join(sorted(REGISTRY))}")
    validate_window(f, t)
    a = REGISTRY[key]
    if lens != "raw" and not a.lenses:
        raise ValueError(f"{key} does not honour a lens yet (it runs raw); lens-aware analyses: {', '.join(k for k, x in REGISTRY.items() if x.lenses)}")
    resolved = factors.resolve(s, lens, f, t)
    ds = ds or Dataset.load(s)
    if scope != "team" and scope not in {b.key for b in ds.barbers}:
        raise ValueError(f"scope must be 'team' or the key of a current barber; got {scope!r}")
    p = a.default_params | (params or {})
    result = a.run(AnalysisContext(ds, f, t, scope, lens, p, resolved, lambda x, y: factors.resolve(s, lens, x, y)))
    result.setdefault("context", {}).update({"lens": lens, "factors": [r["factor_id"] for r in resolved]})
    row = AnalysisRun(analysis_key=key, analysis_version=a.version, scope=scope, window_from=f, window_to=t, asof=t, lens=lens, lens_resolved=resolved,
                      params=p, metric_versions=a.metrics_used(), data_fingerprint=_fingerprint(s), created_by=created_by, result=result)
    s.add(row)
    s.flush()
    if label is not None and key == "barber_scorecard":
        if scope != "team":
            raise ValueError("a measurement is stored from a team-scope run")
        save_measurement(s, {"asof": str(t), "window_from": str(f), "window_to": str(t), "values": result["kpis"], "versions": row.metric_versions}, label)
    return row


def get(s: Session, run_id: int) -> AnalysisRun | None:
    return s.get(AnalysisRun, run_id)


def list_runs(s: Session, key: str | None = None, scope: str | None = None, limit: int = 50) -> list[AnalysisRun]:
    q = select(AnalysisRun).order_by(AnalysisRun.window_to.desc(), AnalysisRun.id.desc()).limit(limit)
    if key:
        q = q.where(AnalysisRun.analysis_key == key)
    if scope:
        q = q.where(AnalysisRun.scope == scope)
    return list(s.scalars(q))


def latest(s: Session, key: str, scope: str = "team") -> AnalysisRun | None:
    rows = list_runs(s, key, scope, 1)
    return rows[0] if rows else None


def previous_comparable(s: Session, row: AnalysisRun) -> AnalysisRun | None:
    """The most recent earlier run of the same analysis and scope that can be compared with `row`."""
    q = select(AnalysisRun).where(AnalysisRun.analysis_key == row.analysis_key, AnalysisRun.scope == row.scope,
                                  AnalysisRun.window_to < row.window_to).order_by(AnalysisRun.window_to.desc(), AnalysisRun.id.desc())
    return next((r for r in s.scalars(q) if not not_comparable(r, row)), None)


def compare_with_previous(s: Session, run_id: int) -> dict:
    """Compare a run with the most recent earlier run it can be compared with."""
    after = s.get(AnalysisRun, run_id)
    if after is None:
        raise KeyError("unknown run id")
    before = previous_comparable(s, after)
    if before is None:
        return {"before": None, "after": run_id, "comparable": False, "reasons": ["no earlier comparable run"], "changes": {}, "findings": {"new": [], "resolved": []}}
    return compare_runs(before, after)


def compare(s: Session, before_id: int, after_id: int) -> dict:
    before, after = s.get(AnalysisRun, before_id), s.get(AnalysisRun, after_id)
    if before is None or after is None:
        raise KeyError("unknown run id")
    return compare_runs(before, after)


FOLLOW_UP_DAYS = 90


def followup_window(s: Session, f: dt.date, t: dt.date) -> tuple[dt.date, dt.date]:
    """The latest window of the same length whose 90-day follow-up has fully happened (for retention and return cohorts)."""
    last = data_status(s)["last_visit"] or t
    late = (t + dt.timedelta(days=FOLLOW_UP_DAYS) - last).days
    shift = dt.timedelta(weeks=-(-late // 7)) if late > 0 else dt.timedelta(0)
    return f - shift, t - shift
