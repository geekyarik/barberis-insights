"""Metric plugin registry.

A metric is a function `(ctx: WindowContext, scope: Scope) -> float | None`, registered with metadata.
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


REGISTRY: dict[str, MetricDef] = {}


def metric(key: str, label: str, unit: str = "", direction: str = "up", scopes: tuple[str, ...] = ("barber", "team"), help: str = ""):
    def deco(fn):
        REGISTRY[key] = MetricDef(key, label, unit, direction, fn, scopes, help)
        return fn
    return deco


def catalog() -> list[dict]:
    return [{"key": m.key, "label": m.label, "unit": m.unit, "direction": m.direction, "scopes": list(m.scopes), "help": m.help} for m in REGISTRY.values()]
