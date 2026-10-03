"""One-time import of the earlier work: the refresh skill's cache and the artifact page's database export."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import default_barbers
from ..db.models import Barber, Goal, Measurement, Tip
from .base import parse_schedule_line, replace_schedule, sync_run, upsert_appointments

from ..config import settings

# Archive of the original refresh skill (appointment cache, schedules, baseline, scripts); private, git-ignored.
SKILL_DIR = settings.data_dir / "legacy-skill"


def ensure_barbers(s: Session) -> int:
    n = 0
    for b in default_barbers():
        if s.get(Barber, b.altegio_id) is None:
            s.add(Barber(altegio_id=b.altegio_id, key=b.key, name=b.name, tier=b.tier, active=True)); n += 1
    s.flush()
    return n


def save_measurement(s: Session, snap: dict, label: str = "") -> int:
    asof = dt.date.fromisoformat(snap["asof"]); wf = dt.date.fromisoformat(snap["window_from"]); wt = dt.date.fromisoformat(snap["window_to"])
    existing = {(m.scope, m.metric): m for m in s.scalars(select(Measurement).where(Measurement.asof == asof))}
    n = 0
    for scope, vals in snap["values"].items():
        for metric, v in vals.items():
            if v is None:
                continue
            m = existing.get((scope, metric)) or Measurement(asof=asof, scope=scope, metric=metric)
            m.window_from, m.window_to, m.value, m.label = wf, wt, float(v), label or snap.get("label", "")
            s.add(m); n += 1
    return n


def _doc_body(p: Path) -> tuple[str, dict]:
    j = json.loads(p.read_text())
    body = j.get("data", j) if isinstance(j, dict) else j
    return j.get("id", p.stem) if isinstance(j, dict) else p.stem, body


def import_artifact_export(s: Session, export_dir: Path) -> dict:
    """Folder written by `ArtifactData list ... out_dir`: goals/*.json, tips/*.json, snapshots/*.json."""
    out = {"goals": 0, "tips": 0, "measurements": 0}
    for p in sorted((export_dir / "goals").glob("*.json")):
        gid, b = _doc_body(p)
        g = s.get(Goal, gid) or Goal(id=gid)
        g.scope, g.title, g.metric = b["barber"], b["title"], b["metric"]
        g.baseline, g.target, g.due = float(b["baseline"]), float(b["target"]), dt.date.fromisoformat(b["due"])
        g.status, g.actions = b.get("status", "active"), b.get("actions", "")
        g.manual_current = b.get("current")
        if b.get("created"):
            g.created = dt.datetime.fromisoformat(b["created"].replace("Z", "+00:00"))
        s.add(g); out["goals"] += 1
    for p in sorted((export_dir / "tips").glob("*.json")):
        tid, b = _doc_body(p)
        t = s.get(Tip, tid) or Tip(id=tid)
        t.title, t.tag, t.body, t.barbers = b["title"], b.get("tag", ""), b.get("body", ""), b.get("barbers", [])
        s.add(t); out["tips"] += 1
    for p in sorted((export_dir / "snapshots").glob("*.json")):
        _, b = _doc_body(p)
        out["measurements"] += save_measurement(s, b)
    return out


def import_legacy(s: Session, skill_dir: Path = SKILL_DIR, artifact_export: Path | None = None) -> dict:
    out: dict = {}
    with sync_run(s, "legacy") as run:
        out["barbers_added"] = ensure_barbers(s)
        rows = [json.loads(l) for l in (skill_dir / "data/appointments.jsonl").read_text().splitlines() if l.strip()]
        out["appointments"] = upsert_appointments(s, rows)
        keys = {b.key: b.altegio_id for b in s.scalars(select(Barber))}
        slots = 0
        for f in sorted((skill_dir / "data/schedules").glob("*.txt")):
            if f.stem not in keys:
                continue
            days = dict(x for x in (parse_schedule_line(l) for l in f.read_text().splitlines()) if x)
            slots += replace_schedule(s, keys[f.stem], days)
        out["schedule_slots"] = slots
        base = skill_dir / "data/baseline_snapshot.json"
        if base.exists():
            out["baseline_values"] = save_measurement(s, json.loads(base.read_text()), "Analysis baseline")
        if artifact_export:
            out["artifact"] = import_artifact_export(s, artifact_export)
        run.counts = {k: v for k, v in out.items() if not isinstance(v, dict)} | {"appointments_added": out["appointments"]["added"]}
    return out
