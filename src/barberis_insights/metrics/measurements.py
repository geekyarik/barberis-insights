"""Storing measurements: the queryable copy of a run's metric values. Written only as a side effect of a run."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Measurement


def save_measurement(s: Session, snap: dict, label: str = "") -> int:
    asof = dt.date.fromisoformat(snap["asof"]); wf = dt.date.fromisoformat(snap["window_from"]); wt = dt.date.fromisoformat(snap["window_to"])
    versions = snap.get("versions", {})
    existing = {(m.scope, m.metric, m.metric_version): m for m in s.scalars(select(Measurement).where(Measurement.asof == asof))}
    n = 0
    for scope, vals in snap["values"].items():
        for metric, v in vals.items():
            if v is None:
                continue
            ver = versions.get(metric, 1)
            m = existing.get((scope, metric, ver)) or Measurement(asof=asof, scope=scope, metric=metric, metric_version=ver)
            m.window_from, m.window_to, m.value, m.label = wf, wt, float(v), label or snap.get("label", "")
            s.add(m); n += 1
    return n
