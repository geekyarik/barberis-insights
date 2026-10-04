"""Metric plugin registry.

A metric is one module under `metrics/<family>/` holding a `VERSION`, a business-definition docstring and one function `(ctx: WindowContext, scope: Scope) -> float | None`, registered with metadata.
`scope` is a barber (per-barber value) or the team. Add a metric anywhere that is imported at start-up:

    @metric("util", "Busy share of scheduled time", unit="%", direction="up")
    def util(ctx, scope): ...
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@dataclass(frozen=True)
class MetricDef:
    key: str
    label: str
    unit: str  # "%", "₴" or ""
    direction: str  # "up" = higher is better, "down" = lower is better
    fn: Callable
    scopes: tuple[str, ...] = ("barber", "team")
    help: str = ""
    needs_history: bool = False  # reads client history, so it is not comparable across the start of the loaded history
    version: int = 1  # raised when the definition changes; only equal versions are compared


REGISTRY: dict[str, MetricDef] = {}


def metric(key: str, label: str, unit: str = "", direction: str = "up", scopes: tuple[str, ...] = ("barber", "team"), help: str = "", version: int = 1, needs_history: bool = False):
    def deco(fn):
        REGISTRY[key] = MetricDef(key, label, unit, direction, fn, scopes, help, needs_history, version)
        return fn
    return deco


def catalog() -> list[dict]:
    return [{"key": m.key, "label": m.label, "unit": m.unit, "direction": m.direction, "scopes": list(m.scopes), "help": m.help, "version": m.version} for m in REGISTRY.values()]
