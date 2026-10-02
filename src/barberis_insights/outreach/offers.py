"""Offer catalog. Codes are referenced by clients/risk.suggest_offer and the sheet's "Offer given" dropdown."""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..db.models import Offer

DEFAULT_OFFERS = [
    Offer(code="call_only", label="Friendly call, no discount", kind="none", value=0, valid_days=30),
    Offer(code="pct10", label="10% off the next visit", kind="percent", value=10, valid_days=30),
    Offer(code="pct15", label="15% off the next visit", kind="percent", value=15, valid_days=30),
    Offer(code="free_addon", label="Free head massage with the next haircut", kind="fixed", value=300, valid_days=30),
]


def seed_offers(s: Session) -> int:
    n = 0
    for o in DEFAULT_OFFERS:
        if s.get(Offer, o.code) is None:
            s.add(Offer(code=o.code, label=o.label, kind=o.kind, value=o.value, valid_days=o.valid_days, active=True)); n += 1
    return n


def active_offers(s: Session) -> list[Offer]:
    from sqlalchemy import select
    return list(s.scalars(select(Offer).where(Offer.active.is_(True)).order_by(Offer.code)))
