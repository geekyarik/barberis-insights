"""Playbook: shared routines tagged by the barbers they apply to."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Tip


def upsert(s: Session, data: dict, tip_id: str | None = None) -> Tip:
    t = s.get(Tip, tip_id) if tip_id else None
    if t is None:
        t = Tip(id=tip_id or re.sub(r"[^a-z0-9]+", "-", data["title"].lower()).strip("-")[:50] or "tip")
        s.add(t)
    for f in ("title", "tag", "body", "barbers"):
        if f in data and data[f] is not None:
            setattr(t, f, data[f])
    s.flush()
    return t


def listing(s: Session, barber: str | None = None) -> list[Tip]:
    tips = list(s.scalars(select(Tip).order_by(Tip.created)))
    return [t for t in tips if not barber or barber in (t.barbers or [])]


def as_dict(t: Tip) -> dict:
    return {"id": t.id, "title": t.title, "tag": t.tag, "body": t.body, "barbers": t.barbers}
