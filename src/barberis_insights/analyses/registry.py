"""Analysis registry: a module under analyses/ registers itself with @analysis."""
from __future__ import annotations

from typing import Callable

from .base import AnalysisDef

REGISTRY: dict[str, AnalysisDef] = {}


def analysis(key: str, label: str, question: str, version: int, default_params: dict | None = None,
             metrics_used: Callable[[], dict] | None = None):
    def deco(fn):
        REGISTRY[key] = AnalysisDef(key, label, question, version, fn, default_params or {}, metrics_used or (lambda: {}))
        return fn
    return deco


def catalog() -> list[dict]:
    return [{"key": a.key, "label": a.label, "question": a.question, "version": a.version, "params": a.default_params} for a in REGISTRY.values()]
