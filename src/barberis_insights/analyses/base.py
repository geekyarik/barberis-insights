"""The analysis contract: what an analysis module provides and what it returns.

An analysis answers one business question for a window, a scope and a lens. It calls Metrics and Clients; it never
queries tables itself. Its result is plain JSON:

    {"kpis":     {scope: {kpi: value}},          scope = a barber key or "team"
     "directions": {kpi: "up" | "down"},         which way is better (omit for neutral figures)
     "units":    {kpi: "%" | "₴" | ""},
     "tables":   {name: [row, ...]},             rows hold ids and aggregates, never contact details
     "findings": [{"code", "severity", "scope", "evidence"}],
     "complete": bool,                           False when the window is not fully observed yet
     "context":  {...}}                          the lens and whatever else was taken into account
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Callable

from ..metrics import Dataset, WindowContext


@dataclass
class AnalysisContext:
    ds: Dataset
    f: dt.date
    t: dt.date
    scope: str = "team"
    lens: str = "raw"
    params: dict = field(default_factory=dict)

    @property
    def asof(self) -> dt.date:
        return self.t

    def window(self, cohort: tuple[dt.date, dt.date] | None = None) -> WindowContext:
        return WindowContext(self.ds, self.f, self.t, cohort)

    @property
    def barbers(self):
        """Currently employed barbers only: per-barber output never includes former ones."""
        return self.ds.barbers

    def wants(self, key: str) -> bool:
        return self.scope in ("team", key)


@dataclass(frozen=True)
class AnalysisDef:
    key: str
    label: str
    question: str
    version: int
    run: Callable[[AnalysisContext], dict]
    default_params: dict = field(default_factory=dict)
    metrics_used: Callable[[], dict] = lambda: {}   # metric key -> version, recorded with every run


def validate_window(f: dt.date, t: dt.date) -> None:
    """A window is whole ISO weeks: a Monday to a Sunday."""
    if f.weekday() != 0 or t.weekday() != 6 or t < f:
        raise ValueError(f"a window is whole ISO weeks (Monday to Sunday); got {f}..{t}")


def finding(code: str, severity: str, scope: str, **evidence) -> dict:
    return {"code": code, "severity": severity, "scope": scope, "evidence": evidence}
