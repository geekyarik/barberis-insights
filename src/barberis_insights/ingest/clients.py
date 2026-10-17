"""Client records from Altegio (clients_list_profiles / clients_get_segment_report / clients_search)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from ..db.models import Client, now


def _bool(v):
    return None if v is None else bool(v)


def upsert_clients(s: Session, items: list[dict]) -> int:
    n = 0
    for it in items:
        cid = it.get("id") or it.get("client_id")
        if not cid:
            continue
        c = s.get(Client, cid) or Client(altegio_id=cid)
        s.add(c)
        if it.get("name") or it.get("display_name"):
            c.name = (it.get("display_name") or it.get("name") or "").strip()
        for src, dst in (("phone", "phone"), ("email", "email")):
            if it.get(src):
                setattr(c, dst, str(it[src]).strip())
        if it.get("birthday") or it.get("birth_date"):
            try:
                c.birthday = dt.date.fromisoformat(str(it.get("birthday") or it.get("birth_date"))[:10])
            except ValueError:
                pass
        consent = it.get("personal_data_processing_allowed", it.get("data_processing_allowed"))
        if consent is not None:
            c.data_processing_allowed = _bool(consent)
        mass = it.get("mass_notification_allowed")
        if mass is None and "sms_excluded_from_campaigns" in it:
            mass = not it["sms_excluded_from_campaigns"]
        if mass is not None:
            c.mass_notification_allowed = _bool(mass)
        if it.get("tags") or it.get("client_tags"):
            c.tags = [t.get("title", t) if isinstance(t, dict) else t for t in (it.get("tags") or it.get("client_tags"))]
        c.updated_from_altegio_at = now()
        n += 1
    return n


def sync_client_list(s: Session, items: list[dict]) -> dict:
    """Refresh the clients we already know from Altegio's full client list: phone, email, the staff comment, the do-not-send-SMS flag, and the
    do-not-contact mark when the comment says so (words in `client_export.DNC_WORDS`). Clients with no visit in our data are not added.
    A do-not-contact mark is set only when the comment changed, so lifting it by hand lasts until someone edits the comment again."""
    from sqlalchemy import select

    from .altegio_api import norm_phone
    from .client_export import DNC_WORDS
    known = {c.altegio_id: c for c in s.scalars(select(Client))}
    out = {"seen": len(items), "known": 0, "skipped_unknown": 0, "phones_added": 0, "phones_changed": 0, "comments_changed": 0, "do_not_contact_set": 0}
    for it in items:
        c = known.get(it.get("id"))
        if c is None:
            out["skipped_unknown"] += 1
            continue
        out["known"] += 1
        phone = norm_phone(it.get("phone"))
        if phone and phone != c.phone:
            out["phones_added" if not c.phone else "phones_changed"] += 1
            c.phone = phone
        if (it.get("email") or "").strip():
            c.email = it["email"].strip()
        comment = (it.get("comment") or "").strip() or None
        if comment != c.altegio_comment:
            out["comments_changed"] += 1
            if comment and any(w in comment.lower() for w in DNC_WORDS) and not c.do_not_contact:
                c.do_not_contact = True
                out["do_not_contact_set"] += 1
            c.altegio_comment = comment
        c.mass_notification_allowed = not bool(it.get("sms_not"))
        c.updated_from_altegio_at = now()
    return out

