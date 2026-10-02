"""Business context: dated notes (events, decisions, observations) with full-text search."""
from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from ..db.models import Note

KINDS = ("event", "decision", "observation", "external")

def seed_notes_file():
    """Business events to seed live in var/seed_notes.json (private, not in git): a list of
    {date_from, date_to, kind, scopes, title, body, tags}."""
    from ..config import settings
    return settings.data_dir / "seed_notes.json"


def add(s: Session, title: str, date_from: str | dt.date, body: str = "", kind: str = "observation", scopes: list[str] | None = None,
        tags: list[str] | None = None, date_to: str | dt.date | None = None, source: str = "user") -> Note:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    d = lambda x: dt.date.fromisoformat(x) if isinstance(x, str) else x
    n = Note(title=title, body=body, kind=kind, scopes=scopes or ["shop"], tags=tags or [], date_from=d(date_from), date_to=d(date_to) if date_to else None, source=source)
    s.add(n); s.flush()
    return n


def seed(s: Session) -> int:
    import json
    path = seed_notes_file()
    if not path.exists():
        return 0
    existing = {n.title for n in s.scalars(select(Note))}
    k = 0
    for n in json.loads(path.read_text()):
        if n["title"] not in existing:
            add(s, n["title"], n["date_from"], n.get("body", ""), n.get("kind", "event"), n.get("scopes"), n.get("tags"), n.get("date_to"), source="seed"); k += 1
    return k


def search(s: Session, q: str | None = None, scope: str | None = None, date_from: dt.date | None = None, date_to: dt.date | None = None,
           limit: int = 50) -> list[Note]:
    stmt = select(Note).order_by(Note.date_from.desc())
    if q:
        terms = " ".join(f'"{w}"*' for w in re.findall(r"\w+", q))
        ids = [r[0] for r in s.execute(text("SELECT rowid FROM notes_fts WHERE notes_fts MATCH :q"), {"q": terms})] if terms else []
        stmt = stmt.where(Note.id.in_(ids))
    if date_from:
        stmt = stmt.where(or_(Note.date_to >= date_from, Note.date_from >= date_from))
    if date_to:
        stmt = stmt.where(Note.date_from <= date_to)
    notes = list(s.scalars(stmt.limit(limit * 3)))
    if scope:
        notes = [n for n in notes if scope in (n.scopes or []) or "shop" in (n.scopes or [])]
    return notes[:limit]


def as_dict(n: Note) -> dict:
    return {"id": n.id, "date_from": str(n.date_from), "date_to": str(n.date_to) if n.date_to else None, "kind": n.kind,
            "scopes": n.scopes, "title": n.title, "body": n.body, "tags": n.tags, "source": n.source}
