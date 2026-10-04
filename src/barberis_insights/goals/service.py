"""Goals: CRUD with an audit trail, and progress/status from the latest measurement (rules ported from the old page)."""
from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import Goal, GoalEvent, Measurement
from ..metrics.registry import REGISTRY

FIELDS = ("scope", "title", "metric", "baseline", "target", "due", "status", "actions", "manual_current")


def series(s: Session, scope: str, metric: str, version: int = 1) -> list[tuple[dt.date, float]]:
    """Measurements of one metric version only: values from different definitions are never compared."""
    return [(m.asof, m.value) for m in s.scalars(select(Measurement).where(Measurement.scope == scope, Measurement.metric == metric,
                                                                          Measurement.metric_version == version).order_by(Measurement.asof))]


def current(s: Session, g: Goal) -> tuple[float | None, dt.date | None]:
    if g.metric == "custom":
        return g.manual_current, g.updated.date() if g.updated else None
    ser = series(s, g.scope, g.metric, g.metric_version)
    return (ser[-1][1], ser[-1][0]) if ser else (None, None)


def progress(g: Goal, cur: float | None) -> float:
    span = g.target - g.baseline
    if cur is None or not span:
        return 0.0
    return max(0.0, min(1.0, (cur - g.baseline) / span))


def assess(s: Session, g: Goal) -> dict:
    cur, asof = current(s, g)
    base_date = dt.date.fromisoformat(settings.baseline_date)
    p = progress(g, cur)
    if g.status in ("done", "dropped"):
        state, label, key = g.status, g.status.capitalize(), g.status
    elif g.metric in REGISTRY and g.metric_version != REGISTRY[g.metric].version:
        state, label, key = "new", "Metric definition changed: set a new baseline and target", "redefined"
    elif cur is None or not (g.target - g.baseline):
        state, label, key = "new", "No data yet", "no_data"
    elif p >= 1:
        state, label, key = "ok", "Target reached", "reached"
    elif not asof or asof <= base_date:
        state, label, key = "new", "Waiting for first measurement", "waiting"
    else:
        elapsed = max(0.0, min(1.0, (asof - base_date).days / max(1, (g.due - base_date).days)))
        state, label, key = ("ok", "On track", "on_track") if p + 0.1 >= elapsed else ("behind", "Behind", "behind")
    return {"id": g.id, "scope": g.scope, "title": g.title, "metric": g.metric, "baseline": g.baseline, "target": g.target,
            "due": str(g.due), "status": g.status, "actions": g.actions, "current": cur, "measured": str(asof) if asof else None,
            "progress": round(p, 3), "state": state, "label": label, "label_key": "goal.state." + key, "metric_version": g.metric_version, "trend": series(s, g.scope, g.metric, g.metric_version) if g.metric != "custom" else []}


def _slug(scope: str, title: str) -> str:
    return f"{scope}-{re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:30] or 'goal'}-{dt.datetime.now().strftime('%H%M%S')}"


def upsert(s: Session, data: dict, goal_id: str | None = None, source: str = "dashboard") -> Goal:
    s.flush()  # make pending measurements visible before the goal itself is pending
    g = s.get(Goal, goal_id) if goal_id else None
    created = g is None
    if created:
        g = Goal(id=goal_id or _slug(data["scope"], data["title"]))
        s.add(g)
        if data.get("metric") in REGISTRY:
            g.metric_version = REGISTRY[data["metric"]].version  # a new goal uses the current definition
    before = {f: getattr(g, f) for f in FIELDS} if not created else {}
    for f in FIELDS:
        if f in data and data[f] is not None:
            v = data[f]
            if f == "due" and isinstance(v, str):
                v = dt.date.fromisoformat(v)
            if f in ("baseline", "target", "manual_current") and v != "":
                v = float(v)
            setattr(g, f, v)
    if g.baseline is None:
        with s.no_autoflush:  # don't insert the half-built goal while looking up its baseline
            ser = series(s, g.scope, g.metric, g.metric_version or 1) if g.metric != "custom" else []
        g.baseline = ser[-1][1] if ser else (g.manual_current or 0.0)
    s.flush()
    changes = {f: [str(before.get(f)), str(getattr(g, f))] for f in FIELDS if str(before.get(f)) != str(getattr(g, f))} if not created else None
    s.add(GoalEvent(goal_id=g.id, kind="created" if created else "updated", detail={"source": source, "changes": changes}))
    return g


def delete(s: Session, goal_id: str, source: str = "dashboard") -> bool:
    g = s.get(Goal, goal_id)
    if not g:
        return False
    s.add(GoalEvent(goal_id=goal_id, kind="deleted", detail={"source": source, "title": g.title}))
    s.delete(g)
    return True


def board(s: Session, scope: str | None = None) -> list[dict]:
    q = select(Goal).order_by(Goal.scope, Goal.created)
    if scope:
        q = q.where(Goal.scope == scope)
    return [assess(s, g) for g in s.scalars(q)]
