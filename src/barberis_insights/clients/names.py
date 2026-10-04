"""Client names for display. Names are personal data: callers show them only to people allowed to see them."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Client


def names_for(s: Session, ids: list[int]) -> dict[int, str]:
    return {c.altegio_id: c.name or "" for c in s.scalars(select(Client).where(Client.altegio_id.in_(ids)))} if ids else {}
