"""Win-back cases: the daily job opens one for each possibly lost client, an administrator processes it, later runs follow it up.

A case opens when a client sits past a risk line and has no case for that line and silence yet (`detect`). Lines, offers and who is
worth calling come from `clients.risk` (docs/OFFERS.md). One client has at most one active case.

  open ──admin: booked──▶ booking_exists ──visit──▶ closed (visited)
   │  ▲                         │
   │  └── booking gone / not found in the CRM
   ├──admin: rejected / no answer──▶ closed (rejected | no_answer)
   ├──visit with no booking seen──▶ closed (visited)
   └──14 days unprocessed──▶ closed (expired)

A case closes as `visited` only when the client really came. `contacted` records whether an administrator had processed it first, so a
return that nobody caused can be told from a win-back.
"""
from __future__ import annotations

import datetime as dt
import math

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..clients import contact
from ..clients.risk import lapsed_line, risk_list, threshold
from ..config import settings
from ..db.models import Appointment, Barber, CaseEvent, Client, ClientProfile, RiskCase, now

ACTIVE = ("open", "booking_exists")
TRIGGER_OF = {"overdue": "overdue", "lapsed": "lapsed", "one_time": "first_timer"}
REJECT_REASONS = contact.REASONS + ("declined_offer", "wrong_number")   # the flag reasons, plus two that concern only this call
FLAGS_THE_CLIENT = contact.REASONS                                     # these also take the client off future lists
BOOKING_STATUSES = ("waiting", "confirmed")


def _event(case: RiskCase, kind: str, by: str = "job", note: str = "") -> None:
    case.events.append(CaseEvent(kind=kind, by=by, note=note))


def _facts(p: ClientProfile):
    from ..clients.profile import Facts
    return Facts(client=p.client_id, first=p.first_visit, last=p.last_visit, visits=p.visits, spend=p.lifetime_spend, usual_barber=p.usual_barber or 0,
                 last_barber=p.last_barber or p.usual_barber or 0, median_gap=p.median_gap_days, days_since=p.days_since_last)


def _line(p: ClientProfile, trigger: str) -> int:
    """The line this client crossed, in days of silence."""
    if trigger == "first_timer":
        return settings.first_timer_days
    f = _facts(p)
    return int(round(lapsed_line(f) if trigger == "lapsed" else threshold(f)))


def active_cases(s: Session, client_ids=None) -> dict[int, RiskCase]:
    q = select(RiskCase).where(RiskCase.status.in_(ACTIVE))
    if client_ids is not None:
        q = q.where(RiskCase.client_id.in_(list(client_ids)))
    return {c.client_id: c for c in s.scalars(q)}


def suggest_barber(s: Session, left: Barber | None, recent_days: int = 90, today: dt.date | None = None) -> int | None:
    """Who to offer a client whose barber left: a current barber of the same level, the least busy lately (so the offer fills free time)."""
    today = today or dt.date.today()
    active = [b for b in s.scalars(select(Barber).where(Barber.active.is_(True)))]
    same = [b for b in active if left is not None and left.tier and b.tier == left.tier] or active
    busy = {b.altegio_id: s.scalar(select(func.count(Appointment.id)).where(Appointment.barber_id == b.altegio_id, Appointment.status == "arrived",
                                                                          Appointment.date >= today - dt.timedelta(days=recent_days))) for b in same}
    return min(same, key=lambda b: busy[b.altegio_id]).altegio_id if same else None


def detect(s: Session, today: dt.date | None = None) -> dict:
    """Open a case for every client past a line who has none for it. Returns what was opened and what was left out, and why.
    The very first run opens only the highest-priority tenth of those who qualify (nobody can work hundreds of old cases); after that a case
    opens only for a client who crossed the line within the case term, so the list stays about what is new."""
    today = today or dt.date.today()
    profiles = {p.client_id: p for p in s.scalars(select(ClientProfile))}
    rows = risk_list(s, tuple(TRIGGER_OF), None, 10 ** 6, include_ineligible=True)
    have = {(c.client_id, c.trigger, c.last_visit) for c in s.scalars(select(RiskCase))}
    first_run = s.scalar(select(RiskCase.id).limit(1)) is None
    active = active_cases(s)
    barbers = {b.altegio_id: b for b in s.scalars(select(Barber))}
    left_out = {"no_offer": 0, "blocked": 0, "no_phone": 0, "has_case": 0, "crossed_long_ago": 0, "first_run_cap": 0}
    cands = []
    for r in rows:
        if not r["suggested_offer"]:
            left_out["no_offer"] += 1; continue
        if set(r["ineligible_reasons"]) - {"no_phone"}:
            left_out["blocked"] += 1; continue
        if "no_phone" in r["ineligible_reasons"]:
            left_out["no_phone"] += 1; continue
        p = profiles[r["client_id"]]
        trigger = TRIGGER_OF[r["segment"]]
        if r["client_id"] in active or (r["client_id"], trigger, p.last_visit) in have:
            left_out["has_case"] += 1; continue
        line = _line(p, trigger)
        crossed = p.last_visit + dt.timedelta(days=line)
        if not first_run and crossed < today - dt.timedelta(days=settings.case_expire_days):
            left_out["crossed_long_ago"] += 1; continue
        cands.append((p, r, trigger, line, crossed))
    if first_run and cands:
        cands.sort(key=lambda c: -c[0].priority)
        keep = max(settings.case_first_run_min, math.ceil(settings.case_first_run_share * len(cands)))
        left_out["first_run_cap"] = max(0, len(cands) - keep)
        cands = cands[:keep]
    opened = []
    for p, r, trigger, line, crossed in cands:
        usual = barbers.get(p.usual_barber)
        left = usual is None or not usual.active
        snapshot = {"segment": p.segment, "visits": p.visits, "lifetime_spend": p.lifetime_spend, "days_since": p.days_since_last, "median_gap": p.median_gap_days,
                    "first_visit": str(p.first_visit), "last_visit": str(p.last_visit), "priority": p.priority, "return_chance": p.return_chance,
                    "phone": r["phone"], "name": r["name"], "asof": str(p.asof)}
        if left:
            snapshot |= {"barber_left": True, "suggested_barber_id": suggest_barber(s, usual, today=today)}
        case = RiskCase(client_id=p.client_id, trigger=trigger, trigger_days=line, crossed_on=crossed, last_visit=p.last_visit,
                        expires_on=today + dt.timedelta(days=settings.case_expire_days), offer=r["suggested_offer"],
                        barber_id=p.usual_barber if usual is not None else None, priority=p.priority, snapshot=snapshot)
        _event(case, "opened", "job", f"{trigger} line {line} d crossed on {crossed}" + (" (barber left)" if left else ""))
        s.add(case); opened.append(case)
    s.flush()
    return {"opened": len(opened), "left_out": left_out, "first_run": first_run, "ids": [c.id for c in opened]}


def _close(case: RiskCase, outcome: str, by: str, reason: str | None = None, comment: str = "") -> None:
    case.status, case.outcome, case.reason, case.closed = "closed", outcome, reason, now()
    case.processed_by = by if by != "job" else case.processed_by
    if comment:
        case.comment = comment


def refresh(s: Session, today: dt.date | None = None) -> dict:
    """Follow the active cases up against the appointments: a visit closes a case, a future booking marks it, silence expires it."""
    today = today or dt.date.today()
    visited = booked = lost = expired = 0
    for case in list(s.scalars(select(RiskCase).where(RiskCase.status.in_(ACTIVE)))):
        appts = list(s.scalars(select(Appointment).where(Appointment.client_id == case.client_id, Appointment.deleted.is_(False),
                                                         Appointment.date > case.last_visit).order_by(Appointment.date)))
        visit = next((a for a in appts if a.status == "arrived"), None)
        if visit:
            case.visited_on, case.visit_revenue = visit.date, visit.total_cost
            _close(case, "visited", "job")
            _event(case, "visited", "job", f"{visit.date}, ₴{visit.total_cost or 0:,.0f}" + ("" if case.contacted else " (before anyone called)"))
            visited += 1
            continue
        future = next((a for a in appts if a.status in BOOKING_STATUSES and a.date >= today), None)
        if future:
            if case.status != "booking_exists" or case.appointment_id != future.id:
                if case.status != "booking_exists":
                    _event(case, "booking_seen", "job", f"{future.date}")
                    booked += 1
                case.status, case.booked_for, case.appointment_id = "booking_exists", future.date, future.id
            continue
        if case.status == "booking_exists":
            reported_late = case.appointment_id is None and case.admin_booked_on and today <= case.admin_booked_on + dt.timedelta(days=settings.case_booking_grace_days)
            planned_ahead = case.appointment_id is None and case.booked_for and case.booked_for >= today
            if reported_late or planned_ahead:
                continue                                              # the CRM may not show it yet
            case.status, case.booked_for, case.appointment_id = "open", None, None
            _event(case, "booking_lost", "job", "the booking is gone or was never seen in the CRM")
            lost += 1
        if case.status == "open" and today > case.expires_on:
            _close(case, "expired", "job")
            _event(case, "expired", "job", f"not processed by {case.expires_on}")
            expired += 1
    s.flush()
    return {"visited": visited, "booking_exists": booked, "booking_lost": lost, "expired": expired}


# ---------------------------------------------------------------- what an administrator does
def _check(case: RiskCase) -> None:
    if case.status == "closed":
        raise ValueError("the case is already closed")


def record_booking(s: Session, case: RiskCase, by: str, booked_for: dt.date | None = None, note: str = "", today: dt.date | None = None) -> RiskCase:
    """The client agreed and was booked. The case stays open for follow-up until the visit really happens."""
    _check(case)
    today = today or dt.date.today()
    if booked_for and booked_for < today:
        raise ValueError("the booking date is in the past")
    case.status, case.contacted, case.booked_for, case.admin_booked_on = "booking_exists", True, booked_for, today
    case.processed_by = by
    _event(case, "admin_booked", by, (f"{booked_for}. " if booked_for else "") + note)
    s.flush()
    return case


def reject(s: Session, case: RiskCase, by: str, reason: str, comment: str = "", until: dt.date | None = None) -> RiskCase:
    """The client will not come (or cannot be reached for good). Reasons that describe the client also flag them, so no case reopens."""
    _check(case)
    if reason not in REJECT_REASONS:
        raise ValueError(f"unknown reason {reason!r}")
    if reason in FLAGS_THE_CLIENT:
        contact.add_flag(s, case.client_id, reason, comment, until)
    elif reason == "wrong_number":
        pass                                         # the number is wrong, not the client: nothing to flag
    case.contacted = True
    _close(case, "rejected", by, reason, comment)
    _event(case, "rejected", by, f"{reason}. {comment}".strip())
    s.flush()
    return case


def no_answer(s: Session, case: RiskCase, by: str, note: str = "") -> RiskCase:
    """One try only: an unanswered call closes the case."""
    _check(case)
    case.contacted = True
    _close(case, "no_answer", by, None, note)
    _event(case, "no_answer", by, note)
    s.flush()
    return case


# ---------------------------------------------------------------- reading
TABS = {"open": ("open",), "booking": ("booking_exists",), "processed": ("closed",)}


def case_rows(s: Session, tab: str = "open", barber: int | None = None, limit: int = 500) -> list[dict]:
    q = select(RiskCase).where(RiskCase.status.in_(TABS[tab]))
    if barber:
        q = q.where(RiskCase.barber_id == barber)
    q = q.order_by(RiskCase.closed.desc() if tab == "processed" else RiskCase.priority.desc()).limit(limit)
    cases = list(s.scalars(q))
    clients = {c.altegio_id: c for c in s.scalars(select(Client).where(Client.altegio_id.in_([c.client_id for c in cases])))}
    flags = contact.active_flags(s, [c.client_id for c in cases])
    today = dt.date.today()
    out = []
    for c in cases:
        cl = clients.get(c.client_id)
        snap = c.snapshot or {}
        out.append({"case": c, "id": c.id, "client_id": c.client_id, "name": (cl.name if cl else "") or snap.get("name", ""), "phone": cl.phone if cl and cl.phone else snap.get("phone"),
                    "trigger": c.trigger, "trigger_days": c.trigger_days, "crossed_on": c.crossed_on, "status": c.status, "outcome": c.outcome, "reason": c.reason,
                    "offer": c.offer, "barber_id": c.barber_id, "priority": c.priority, "chance": snap.get("return_chance"), "barber_left": bool(snap.get("barber_left")),
                    "suggested_barber_id": snap.get("suggested_barber_id"), "snapshot": snap, "flag": flags.get(c.client_id),
                    "days_left": (c.expires_on - today).days if c.status == "open" else None, "booked_for": c.booked_for, "processed_by": c.processed_by,
                    "days_since": (today - c.last_visit).days, "lifetime_spend": snap.get("lifetime_spend", 0), "median_gap": snap.get("median_gap"), "visits": snap.get("visits"),
                    "closed": c.closed, "contacted": c.contacted, "visited_on": c.visited_on, "visit_revenue": c.visit_revenue, "comment": c.comment})
    return out


def counts(s: Session) -> dict[str, int]:
    from collections import Counter
    c = Counter(st for (st,) in s.execute(select(RiskCase.status)))
    return {"open": c.get("open", 0), "booking": c.get("booking_exists", 0), "processed": c.get("closed", 0)}


def next_open(s: Session, after_id: int | None = None) -> RiskCase | None:
    """The next case to work on: the highest priority open one other than the one just done."""
    q = select(RiskCase).where(RiskCase.status == "open").order_by(RiskCase.priority.desc(), RiskCase.id)
    if after_id:
        q = q.where(RiskCase.id != after_id)
    return s.scalars(q.limit(1)).first()
