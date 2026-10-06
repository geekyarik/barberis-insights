"""The Notifications service: who gets what, through which channel. Every delivery is recorded, retried a few times, and never repeated."""
from __future__ import annotations

import time
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clients.names import names_for
from ..config import settings
from ..db.models import Delivery, Recipient, Subscription
from . import render
from .channels import ChannelError, get as get_channel

KINDS = ("weekly_review", "alert")
ATTEMPTS = 3


def ensure_owner(s: Session) -> Recipient | None:
    """The owner as the one recipient: the Telegram chat from the settings, subscribed to the weekly review and to alerts."""
    if not settings.telegram_owner_chat_id:
        return None
    r = s.scalar(select(Recipient).where(Recipient.name == "Owner"))
    if r is None:
        r = Recipient(name="Owner", lang=settings.owner_lang, telegram_chat_id=settings.telegram_owner_chat_id, active=True)
        s.add(r); s.flush()
    r.telegram_chat_id, r.lang = settings.telegram_owner_chat_id, settings.owner_lang
    for kind in KINDS:
        if not s.scalar(select(Subscription).where(Subscription.recipient_id == r.id, Subscription.kind == kind, Subscription.channel == "telegram")):
            s.add(Subscription(recipient_id=r.id, kind=kind, channel="telegram"))
    s.flush()
    return r


def _subs(s: Session, kind: str, only_channel: str | None = None):
    q = select(Subscription, Recipient).join(Recipient, Recipient.id == Subscription.recipient_id).where(Subscription.kind == kind, Recipient.active.is_(True))
    if only_channel:
        q = q.where(Subscription.channel == only_channel)
    return s.execute(q).all()


def _deliver(s: Session, sub: Subscription, rcp: Recipient, text: str, dedupe: str, sleep: Callable[[float], None]) -> Delivery | None:
    done = s.scalar(select(Delivery).where(Delivery.subscription_id == sub.id, Delivery.dedupe_key == dedupe))
    if done is not None and done.status == "sent":
        return None                                     # never twice for the same thing and recipient
    d = done or Delivery(subscription_id=sub.id, dedupe_key=dedupe, channel=sub.channel, status="failed", attempts=0)
    err = ""
    for attempt in range(1, ATTEMPTS + 1):
        d.attempts += 1
        try:
            d.external_id, d.status, err = get_channel(sub.channel).send(rcp, text), "sent", ""
            break
        except ChannelError as e:
            d.status, err = "failed", str(e)
            if attempt < ATTEMPTS:
                sleep(1.5 * attempt)
    d.error = err
    s.add(d); s.flush()
    return d


def send_weekly(s: Session, content: dict, catchup: list[dict] | None = None, sleep: Callable[[float], None] = time.sleep) -> list[Delivery]:
    """The weekly message for one week; sent once per week and recipient."""
    out = []
    for sub, rcp in _subs(s, "weekly_review"):
        names = names_for(s, [r["client_id"] for r in content.get("overdue", {}).get("top", [])])
        text = render.weekly_review(content, rcp.lang, names, catchup)
        d = _deliver(s, sub, rcp, text, f"weekly:{content['week']}", sleep)
        if d:
            out.append(d)
    return out


def send_alert(s: Session, code: str, day: str, sleep: Callable[[float], None] = time.sleep, **params) -> list[Delivery]:
    """An alert goes out at most once per code, subject and day."""
    subject = str(params.get("job") or params.get("title") or "")
    out = []
    for sub, rcp in _subs(s, "alert"):
        d = _deliver(s, sub, rcp, render.alert(code, rcp.lang, **params), f"alert:{code}:{subject}:{day}"[:80], sleep)
        if d:
            out.append(d)
    return out


def send_test(s: Session, channel: str | None = None) -> list[Delivery]:
    from ..i18n import t
    out = []
    for sub, rcp in _subs(s, "alert", channel):
        d = _deliver(s, sub, rcp, t("msg.test", rcp.lang), f"test:{time.time_ns()}", time.sleep)
        if d:
            out.append(d)
    return out
