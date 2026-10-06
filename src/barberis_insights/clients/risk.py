"""Risk segments, priority and suggested offer for each client (shop level).

Segments (days = days since the last visit, threshold = max(overdue_min_days, factor × median gap)):
  one_time   1 visit and silent longer than first_timer_days — first-timers who never came back
  active     within the usual gap
  slipping   past the usual gap but not yet past the threshold (watch only)
  overdue    past the overdue line (60 days for two visits, else 1.5 usual gaps, at least 45), up to the lapsed line
  lapsed     silent longer than max(120, 2 usual gaps), at most 365 days
  switched   active at the shop but the last visit was with a different barber than usual (information only)
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import Client, ClientProfile
from .contact import active_flags
from .profile import Facts

CALLABLE = ("overdue", "lapsed", "one_time")


def threshold(f: Facts) -> float:
    """The overdue line: a client with two visits has no reliable rhythm (one gap), so one fixed line; otherwise 1.5 of their own usual gaps, at least 45 days."""
    if f.visits == 2:
        return settings.two_visit_line_days
    if f.median_gap:
        return max(settings.overdue_min_days, settings.overdue_gap_factor * f.median_gap)
    return settings.overdue_min_days


def lapsed_line(f: Facts) -> float:
    """Silent beyond this and a client counts as lapsed: two usual gaps, but not before 120 days and not after 365, and always after the overdue line."""
    own = settings.lapsed_gap_factor * f.median_gap if f.median_gap else settings.lapsed_min_days
    return max(threshold(f) + 1, min(max(own, settings.lapsed_min_days), settings.lapsed_max_days))


def segment(f: Facts) -> str:
    d = f.days_since
    if f.visits == 1:
        return "one_time" if d > settings.first_timer_days else "active"
    if d > lapsed_line(f):
        return "lapsed"
    if d > threshold(f):
        return "overdue"
    if d > (f.median_gap or 30):
        return "slipping"
    return "switched" if f.last_barber != f.usual_barber else "active"


def yearly_value(f: Facts) -> float:
    """What a client who stays is worth in a year: their average check times their own visits a year (a first-timer who returns makes about five)."""
    rate = min(15.0, max(1.0, 365 / f.median_gap)) if f.median_gap else 5.0
    return (f.spend / f.visits) * rate


def priority(f: Facts, model=None) -> tuple[float, float]:
    """(priority, chance of returning): the chance to come back within 90 days times a year's value, so the likeliest and most valuable go first."""
    chance = model.chance(f.visits, f.days_since) if model else 0.10
    return round(chance * yearly_value(f), 1), round(chance, 3)


def suggest_offer(f: Facts, seg: str) -> str | None:
    """Two offers, chosen by how likely the client is to come back on their own (docs/OFFERS.md, docs/CASES.md); the admin can override per call.
    - an overdue client with two visits: a call (their value does not carry a discount);
    - an overdue regular up to `early_overdue_days` past their own line: a call, no discount (half return anyway);
    - an overdue regular further past it, or a lapsed regular silent up to `lapsed_max_days`: `book_now` (a discount for booking during the call);
    - a one-time client in the first-timer window: `book_now` (the second visit within 60 days decides who becomes a regular);
    - everyone else: no offer, the data does not justify one."""
    if seg == "overdue":
        if f.visits == 2:
            return "call_only"
        return "call_only" if f.days_since - threshold(f) <= settings.early_overdue_days else "book_now"
    if seg == "lapsed" and f.visits >= 3 and f.days_since <= settings.lapsed_max_days:
        return "book_now"
    lo, hi = settings.book_now_first_timer_days
    if seg == "one_time" and lo <= f.days_since <= hi:
        return "book_now"
    return None


def classify(f: Facts, model=None) -> tuple[str, float, float, str | None]:
    """(segment, priority, chance of returning, offer)."""
    seg = segment(f)
    prio, chance = priority(f, model)
    return seg, prio, chance, suggest_offer(f, seg)


def risk_list(s: Session, segments: tuple[str, ...] = ("overdue", "lapsed"), barber: int | None = None, limit: int = 200,
              include_ineligible: bool = False, min_visits: int = 2) -> list[dict]:
    """Ranked call candidates with eligibility flags. Eligible = consent not refused, not do-not-contact, not flagged, has a phone.
    `ineligible_reasons` are codes (dnc, no_consent, flag_<reason>, no_phone); interfaces translate them (i18n "reason.*").
    """
    q = select(ClientProfile).where(ClientProfile.segment.in_(segments)).order_by(ClientProfile.priority.desc())
    if barber:
        q = q.where(ClientProfile.usual_barber == barber)
    profiles = [p for p in s.scalars(q) if p.visits >= min_visits or p.segment == "one_time"]
    clients = {c.altegio_id: c for c in s.scalars(select(Client).where(Client.altegio_id.in_([p.client_id for p in profiles])))}
    flags = active_flags(s, [p.client_id for p in profiles])
    out = []
    for p in profiles:
        c = clients.get(p.client_id)
        reasons = []
        if c and c.do_not_contact:
            reasons.append("dnc")
        if c and c.data_processing_allowed is False:
            reasons.append("no_consent")
        flag = flags.get(p.client_id)
        if flag:
            reasons.append(f"flag_{flag.reason}")
        if not c or not c.phone:
            reasons.append("no_phone")
        if reasons and not include_ineligible:
            continue
        out.append({"client_id": p.client_id, "name": c.name if c else "", "phone": c.phone if c else None, "flag": ({"reason": flag.reason, "comment": flag.comment, "until": flag.until, "since": flag.created.date()} if flag else None), "segment": p.segment,
                    "visits": p.visits, "lifetime_spend": p.lifetime_spend, "last_visit": str(p.last_visit), "days_since": p.days_since_last,
                    "median_gap": p.median_gap_days, "usual_barber": p.usual_barber, "priority": p.priority, "return_chance": p.return_chance,
                    "suggested_offer": p.suggested_offer, "eligible": not reasons, "ineligible_reasons": reasons})
        if len(out) >= limit:
            break
    return out
