"""Business context. Notes are now Factors: the same calls (add, search, as_dict) keep working, backed by the `factors` table.
New code should use `context.factors` for treatments, recurrence, lenses and expected effects."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db.models import Factor, Note  # noqa: F401  (Note: the retired table, kept importable)
from . import factors

KINDS = ("event", "decision", "observation", "external")      # the old note kinds, kept as categories


def seed_notes_file():
    """Business events to seed live in var/seed_notes.json (private, not in git): a list of
    {date_from, date_to, kind, scopes, title, body, tags}."""
    from ..config import settings
    return settings.data_dir / "seed_notes.json"


def add(s: Session, title: str, date_from, body: str = "", kind: str = "observation", scopes: list[str] | None = None,
        tags: list[str] | None = None, date_to=None, source: str = "user", **factor_fields) -> Factor:
    """A note is an annotate-only factor. `kind` takes the old note kinds (external, or event / decision / observation) or a new factor kind."""
    if kind in factors.KINDS:
        factor_fields.setdefault("kind", kind)
    elif kind in KINDS:
        factor_fields.setdefault("kind", "external" if kind == "external" else "internal")
        factor_fields.setdefault("category", kind)
    else:
        raise ValueError(f"kind must be one of {KINDS + factors.KINDS}")
    return factors.add(s, title, date_from, date_to, body=body, scopes=scopes, tags=tags, source=source, **factor_fields)


def seed(s: Session) -> int:
    import json
    path = seed_notes_file()
    if not path.exists():
        return 0
    existing = {f.title for f in s.scalars(select(Factor))}
    k = 0
    for n in json.loads(path.read_text()):
        if n["title"] not in existing:
            add(s, n["title"], n["date_from"], n.get("body", ""), n.get("kind", "event"), n.get("scopes"), n.get("tags"), n.get("date_to"), source="seed"); k += 1
    return k


def search(s: Session, q: str | None = None, scope: str | None = None, date_from: dt.date | None = None, date_to: dt.date | None = None,
           limit: int = 50) -> list[Factor]:
    stmt = select(Factor).where(Factor.active.is_(True)).order_by(Factor.date_from.desc())
    if q:
        for w in q.split():
            like = f"%{w}%"
            stmt = stmt.where(or_(Factor.title.ilike(like), Factor.body.ilike(like), Factor.category.ilike(like)))
    if date_from:
        stmt = stmt.where(or_(Factor.date_to >= date_from, Factor.date_from >= date_from))
    if date_to:
        stmt = stmt.where(Factor.date_from <= date_to)
    found = list(s.scalars(stmt.limit(limit * 3)))
    if scope:
        found = [f for f in found if factors.applies_to(f, scope)]
    return found[:limit]


def as_dict(f: Factor) -> dict:
    """The old note shape (date_from, date_to, kind, scopes, title, body, tags, source) plus the factor's own fields."""
    return {"id": f.id, "date_from": str(f.date_from), "date_to": str(f.date_to) if f.date_to else None, "kind": f.category if f.category in KINDS else f.kind,
            "scopes": f.scopes, "title": f.title, "body": f.body, "tags": f.tags, "source": f.source} | {
        k: v for k, v in factors.as_dict(f).items() if k in ("category", "recurrence", "lead_days", "expected_effects", "treatment", "adjust_factor", "effect_run")}
