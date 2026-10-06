"""What people who know a client tell us: why not to call them."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import ClientFlag, now

REASONS = ("abroad", "mobilised", "moved", "not_interested", "other")


def active_flags(s: Session, client_ids=None, today: dt.date | None = None) -> dict[int, ClientFlag]:
    """The current flag of each flagged client: not lifted and not past its recheck date."""
    today = today or dt.date.today()
    q = select(ClientFlag).where(ClientFlag.lifted.is_(None)).order_by(ClientFlag.id)
    if client_ids is not None:
        q = q.where(ClientFlag.client_id.in_(list(client_ids)))
    return {f.client_id: f for f in s.scalars(q) if f.until is None or f.until >= today}


def add_flag(s: Session, client_id: int, reason: str, comment: str = "", until: dt.date | None = None) -> ClientFlag:
    """Replaces the client's earlier flag: the newest word wins, the old one stays as history."""
    if reason not in REASONS:
        raise ValueError(f"unknown reason {reason!r}; use one of {', '.join(REASONS)}")
    if until and until < dt.date.today():
        raise ValueError("the recheck date is in the past")
    lift_flag(s, client_id)
    f = ClientFlag(client_id=client_id, reason=reason, comment=comment.strip()[:500], until=until)
    s.add(f); s.flush()
    return f


def lift_flag(s: Session, client_id: int) -> int:
    n = 0
    for f in s.scalars(select(ClientFlag).where(ClientFlag.client_id == client_id, ClientFlag.lifted.is_(None))):
        f.lifted = now(); n += 1
    return n


def history(s: Session, client_id: int) -> list[ClientFlag]:
    return list(s.scalars(select(ClientFlag).where(ClientFlag.client_id == client_id).order_by(ClientFlag.id.desc())))
