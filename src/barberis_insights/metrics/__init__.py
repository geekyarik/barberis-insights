"""Metrics: registry, built-ins and snapshot computation."""
from __future__ import annotations

import datetime as dt

from .context import Dataset, Scope, WindowContext
from .registry import REGISTRY, catalog


def _discover() -> None:
    """Import every module under metrics/<family>/ so its @metric registers itself."""
    import importlib
    import pkgutil
    for fam in pkgutil.iter_modules(__path__):
        if fam.ispkg:
            pkg = importlib.import_module(f"{__name__}.{fam.name}")
            for m in pkgutil.iter_modules(pkg.__path__):
                importlib.import_module(f"{pkg.__name__}.{m.name}")


_discover()


def compute_snapshot(ds: Dataset, f: dt.date, t: dt.date, cohort: tuple[dt.date, dt.date] | None = None) -> dict:
    """Every registered metric for every active barber and the team, over the window f..t."""
    ctx = WindowContext(ds, f, t, cohort)
    values: dict[str, dict] = {}
    for b in ds.barbers:
        sc = Scope(b.key, b.altegio_id)
        values[b.key] = {m.key: v for m in REGISTRY.values() if "barber" in m.scopes and (v := m.fn(ctx, sc)) is not None}
    values["team"] = {m.key: v for m in REGISTRY.values() if "team" in m.scopes and (v := m.fn(ctx, Scope("team"))) is not None}
    co = ctx.cohort_window
    versions = {m.key: m.version for m in REGISTRY.values()}
    return {"asof": str(t), "versions": versions, "window_from": str(f), "window_to": str(t), "cohort_window": [str(co[0]), str(co[1])], "values": values}


__all__ = ["Dataset", "WindowContext", "Scope", "REGISTRY", "catalog", "compute_snapshot"]
