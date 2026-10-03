"""Win-back cases: propose from the risk list, approve, record calls, close.

Status flow:
  proposed → approved → in_sheet → (called | no_answer | booked) → won_back | not_returned
  any open status → skipped | declined | do_not_contact | wrong_number   (closed by a person)
"""
from __future__ import annotations

import datetime as dt
import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import Client, ClientProfile, OutreachCase, OutreachEvent, now

OPEN = ("proposed", "approved", "in_sheet", "called", "no_answer", "booked")
CLOSED = ("won_back", "not_returned", "skipped", "declined", "do_not_contact", "wrong_number")
CONTACTED = ("called", "no_answer", "booked", "declined", "won_back", "not_returned")

# Call outcomes the admin picks in the sheet (code → case status). Labels come from the i18n catalogs ("outcome.<code>").
OUTCOMES = {
    "no_answer": "no_answer",
    "call_back": "called",
    "booked": "booked",
    "declined": "declined",
    "do_not_contact": "do_not_contact",
    "wrong_number": "wrong_number",
}


def _event(case: OutreachCase, kind: str, source: str, **kw) -> None:
    case.events.append(OutreachEvent(kind=kind, source=source, **kw))


def propose(s: Session, rows: list[dict], arms: list[str] | None = None, seed: int | None = None) -> list[OutreachCase]:
    """Create `proposed` cases for eligible risk-list rows. With `arms`, each case gets a random offer arm (A/B test)."""
    rng = random.Random(seed)
    open_clients = {c for (c,) in s.execute(select(OutreachCase.client_id).where(OutreachCase.status.in_(OPEN)))}
    out = []
    for r in rows:
        if not r.get("eligible", True) or r["client_id"] in open_clients:
            continue
        arm = rng.choice(arms) if arms else None
        c = OutreachCase(client_id=r["client_id"], segment=r["segment"], barber_id=r.get("usual_barber"), priority=r["priority"],
                         suggested_offer=arm or r.get("suggested_offer"), offer_arm=arm,
                         reason=f"{r['segment']}: {r['days_since']} days since last visit, {r['visits']} visits, ₴{r['lifetime_spend']:,.0f}",
                         status="proposed", due=dt.date.today() + dt.timedelta(days=7), events=[])
        _event(c, "status", "auto", outcome="proposed")
        s.add(c); out.append(c)
    s.flush()
    return out


def set_status(s: Session, case: OutreachCase, status: str, source: str = "dashboard", note: str | None = None, offer: str | None = None,
               on: dt.date | None = None) -> None:
    if status == case.status and not note and not offer:
        return
    case.status = status
    if offer:
        case.offer_given = offer
    if status in CONTACTED and case.contacted_on is None:
        case.contacted_on = on or dt.date.today()
    if status in CLOSED:
        case.closed = case.closed or now()
    if status == "do_not_contact":
        client = s.get(Client, case.client_id)
        if client:
            client.do_not_contact = True
    _event(case, "status", source, outcome=status, offer_given=offer, note=note)


def approve(s: Session, case_ids: list[int], assigned_to: str | None = None) -> int:
    n = 0
    for c in s.scalars(select(OutreachCase).where(OutreachCase.id.in_(case_ids), OutreachCase.status == "proposed")):
        c.assigned_to = assigned_to or c.assigned_to
        set_status(s, c, "approved"); n += 1
    return n


def skip(s: Session, case_ids: list[int], note: str | None = None) -> int:
    n = 0
    for c in s.scalars(select(OutreachCase).where(OutreachCase.id.in_(case_ids), OutreachCase.status.in_(OPEN))):
        set_status(s, c, "skipped", note=note); n += 1
    return n


def case_rows(s: Session, statuses: tuple[str, ...] = OPEN) -> list[dict]:
    cases = list(s.scalars(select(OutreachCase).where(OutreachCase.status.in_(statuses)).order_by(OutreachCase.priority.desc())))
    clients = {c.altegio_id: c for c in s.scalars(select(Client).where(Client.altegio_id.in_([c.client_id for c in cases])))}
    profiles = {p.client_id: p for p in s.scalars(select(ClientProfile).where(ClientProfile.client_id.in_([c.client_id for c in cases])))}
    out = []
    for c in cases:
        cl, pr = clients.get(c.client_id), profiles.get(c.client_id)
        out.append({"case_id": c.id, "client_id": c.client_id, "name": cl.name if cl else "", "phone": cl.phone if cl else None,
                    "status": c.status, "segment": c.segment, "priority": c.priority, "suggested_offer": c.suggested_offer,
                    "offer_arm": c.offer_arm, "offer_given": c.offer_given, "assigned_to": c.assigned_to, "reason": c.reason,
                    "last_visit": str(pr.last_visit) if pr else None, "days_since": pr.days_since_last if pr else None,
                    "visits": pr.visits if pr else None, "lifetime_spend": pr.lifetime_spend if pr else None,
                    "usual_barber": pr.usual_barber if pr else c.barber_id, "contacted_on": str(c.contacted_on) if c.contacted_on else None,
                    "returned_on": str(c.returned_on) if c.returned_on else None, "revenue_recovered": c.revenue_recovered})
    return out
