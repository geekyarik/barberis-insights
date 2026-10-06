"""Win-back cases: propose from the risk list, approve, record calls, close.

Status flow:
  proposed → approved → in_sheet → (called | no_answer | booked) → won_back | not_returned
  any open status → skipped | declined | do_not_contact | wrong_number   (closed by a person)
  no case → handled   (a person dealt with the client outside the tool and flags it; never reaches the sheet)
  handled | skipped | not_returned | declined | wrong_number → released   (a person lifts the hold)

Holds: the client's latest case decides when the risk list may show them again (`holds`).
  open case → until it closes; skipped → hold_skipped_days; handled → hold_handled_days; not_returned → hold_not_returned_days;
  declined → never; wrong_number → until the phone changes; do_not_contact → the client flag; won_back, released → no hold.
"""
from __future__ import annotations

import datetime as dt
import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clients.contact import contact_phone
from ..config import settings
from ..db.models import Client, ClientProfile, OutreachCase, OutreachEvent, now

OPEN = ("proposed", "approved", "in_sheet", "called", "no_answer", "booked")
CLOSED = ("won_back", "not_returned", "skipped", "declined", "do_not_contact", "wrong_number", "handled", "released")
RELEASABLE = ("handled", "skipped", "not_returned", "declined", "wrong_number")
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


def _latest_cases(s: Session, client_ids=None) -> dict[int, OutreachCase]:
    """Each client's newest case. Filtered in Python: the cases table is small."""
    latest = {c.client_id: c for c in s.scalars(select(OutreachCase).order_by(OutreachCase.id))}
    return latest if client_ids is None else {k: v for k, v in latest.items() if k in client_ids}


def _hold(case: OutreachCase, client: Client | None, today: dt.date) -> dict | None:
    st = case.status
    if st in OPEN:
        return {"reason": "in_progress", "until": None, "case_id": case.id}
    if st == "declined":
        return {"reason": "declined", "until": None, "case_id": case.id}
    if st == "wrong_number":
        changed = client and contact_phone(client) and case.phone and contact_phone(client) != case.phone
        return None if changed else {"reason": "wrong_number", "until": None, "case_id": case.id}
    days = {"skipped": settings.hold_skipped_days, "handled": settings.hold_handled_days, "not_returned": settings.hold_not_returned_days}.get(st)
    if days is None:
        return None
    until = (case.closed or case.created).date() + dt.timedelta(days=days)
    return {"reason": st, "until": until, "case_id": case.id} if until > today else None


def holds(s: Session, client_ids=None, today: dt.date | None = None) -> dict[int, dict]:
    """Clients the risk list must not offer now: {client_id: {reason, until (None = no end date), case_id}}."""
    today = today or dt.date.today()
    latest = _latest_cases(s, client_ids)
    clients = {c.altegio_id: c for c in s.scalars(select(Client).where(Client.altegio_id.in_(list(latest))))}
    out = {}
    for cid, case in latest.items():
        h = _hold(case, clients.get(cid), today)
        if h:
            out[cid] = h
    return out


def won_back_history(s: Session, client_ids=None) -> dict[int, dict]:
    """Clients we already won back: {client_id: {n, last}}. A client who shows up in the risk list again carries this."""
    out: dict[int, dict] = {}
    for c in s.scalars(select(OutreachCase).where(OutreachCase.status == "won_back")):
        if client_ids is not None and c.client_id not in client_ids:
            continue
        when = c.returned_on or (c.closed.date() if c.closed else None)
        h = out.setdefault(c.client_id, {"n": 0, "last": None})
        h["n"] += 1
        if when and (h["last"] is None or when > h["last"]):
            h["last"] = when
    return out


def mark_handled(s: Session, client_ids, note: str | None = None) -> int:
    """Flag clients a person already dealt with outside the tool. Clients with a case in progress are left alone."""
    ids = set(client_ids)
    busy = {cid for cid, h in holds(s, ids).items() if h["reason"] == "in_progress"}
    profiles = {p.client_id: p for p in s.scalars(select(ClientProfile).where(ClientProfile.client_id.in_(ids)))}
    clients = {c.altegio_id: c for c in s.scalars(select(Client).where(Client.altegio_id.in_(ids)))}
    n = 0
    for cid in sorted(ids - busy):
        p, cl = profiles.get(cid), clients.get(cid)
        c = OutreachCase(client_id=cid, segment=p.segment if p else "overdue", barber_id=p.usual_barber if p else None,
                         priority=p.priority if p else 0, phone=contact_phone(cl), reason="handled by hand",
                         status="handled", closed=now(), events=[])
        _event(c, "status", "dashboard", outcome="handled", note=note)
        s.add(c); n += 1
    s.flush()
    return n


def release(s: Session, client_ids, note: str | None = None) -> int:
    """Lift the hold: the client's latest case, if a person closed it, becomes `released`."""
    n = 0
    for case in _latest_cases(s, set(client_ids)).values():
        if case.status in RELEASABLE:
            set_status(s, case, "released", note=note); n += 1
    return n


def propose(s: Session, rows: list[dict], arms: list[str] | None = None, seed: int | None = None) -> list[OutreachCase]:
    """Create `proposed` cases for eligible risk-list rows. With `arms`, each case gets a random offer arm (A/B test)."""
    rng = random.Random(seed)
    held = holds(s, {r["client_id"] for r in rows})
    out = []
    for r in rows:
        if not r.get("eligible", True) or r["client_id"] in held:
            continue
        arm = rng.choice(arms) if arms else None
        c = OutreachCase(client_id=r["client_id"], segment=r["segment"], barber_id=r.get("usual_barber"), priority=r["priority"], phone=r.get("phone"),
                         suggested_offer=arm or r.get("suggested_offer"), offer_arm=arm,
                         reason=f"{r['segment']}: {r['days_since']} days since last visit, {r['visits']} visits, ₴{r['lifetime_spend']:,.0f}",
                         status="proposed", due=dt.date.today() + dt.timedelta(days=7), events=[])
        _event(c, "status", "auto", outcome="proposed")
        s.add(c); out.append(c); held[r["client_id"]] = {}
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
        out.append({"case_id": c.id, "client_id": c.client_id, "name": cl.name if cl else "", "phone": contact_phone(cl),
                    "status": c.status, "segment": c.segment, "priority": c.priority, "suggested_offer": c.suggested_offer,
                    "offer_arm": c.offer_arm, "offer_given": c.offer_given, "assigned_to": c.assigned_to, "reason": c.reason,
                    "last_visit": str(pr.last_visit) if pr else None, "days_since": pr.days_since_last if pr else None,
                    "visits": pr.visits if pr else None, "lifetime_spend": pr.lifetime_spend if pr else None,
                    "usual_barber": pr.usual_barber if pr else c.barber_id, "contacted_on": str(c.contacted_on) if c.contacted_on else None,
                    "returned_on": str(c.returned_on) if c.returned_on else None, "revenue_recovered": c.revenue_recovered})
    return out
