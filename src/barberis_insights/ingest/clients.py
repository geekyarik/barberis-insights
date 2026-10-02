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
