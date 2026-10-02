"""Metrics: registry, built-ins and snapshot computation."""
from __future__ import annotations

import datetime as dt

from . import core  # noqa: F401  (registers built-in metrics)
from .context import Dataset, Scope, WindowContext
from .registry import REGISTRY, catalog


def compute_snapshot(ds: Dataset, f: dt.date, t: dt.date, cohort: tuple[dt.date, dt.date] | None = None) -> dict:
    """Every registered metric for every active barber and the team, over the window f..t."""
    ctx = WindowContext(ds, f, t, cohort)
    values: dict[str, dict] = {}
    for b in ds.barbers:
        sc = Scope(b.key, b.altegio_id)
        values[b.key] = {m.key: v for m in REGISTRY.values() if "barber" in m.scopes and (v := m.fn(ctx, sc)) is not None}
    values["team"] = {m.key: v for m in REGISTRY.values() if "team" in m.scopes and (v := m.fn(ctx, Scope("team"))) is not None}
    co = ctx.cohort_window
    return {"asof": str(t), "window_from": str(f), "window_to": str(t), "cohort_window": [str(co[0]), str(co[1])], "values": values}


__all__ = ["Dataset", "WindowContext", "Scope", "REGISTRY", "catalog", "compute_snapshot"]
