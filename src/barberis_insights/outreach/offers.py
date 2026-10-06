"""Offer catalog. Codes are referenced by clients/risk.suggest_offer and the sheet's "Offer given" dropdown."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import Offer

DEFAULT_OFFERS = [
    Offer(code="call_only", label="Friendly call, no discount", kind="none", value=0, valid_days=30),
    Offer(code="book_now", label="15% off if booked during the call", kind="percent", value=settings.book_now_pct, valid_days=14),
]
RETIRED = ("pct10", "pct15", "free_addon")   # the first guesses, replaced on 2026-10-06 (docs/OFFERS.md); kept so old cases still read


def seed_offers(s: Session) -> int:
    n = 0
    for o in DEFAULT_OFFERS:
        if s.get(Offer, o.code) is None:
            s.add(Offer(code=o.code, label=o.label, kind=o.kind, value=o.value, valid_days=o.valid_days, active=True)); n += 1
    s.flush()
    for code in RETIRED:
        if (o := s.get(Offer, code)) is not None:
            o.active = False
    return n


def active_offers(s: Session) -> list[Offer]:
    from sqlalchemy import select
    return list(s.scalars(select(Offer).where(Offer.active.is_(True)).order_by(Offer.code)))
