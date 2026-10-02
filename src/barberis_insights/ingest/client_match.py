"""Match rows of an Altegio client export that has no client ID to Altegio client IDs.

The export carries each client's first and last visit (date and time). The database knows which client had an
appointment at each minute, so a row is matched when its visit times point to exactly one client
(names break ties). Rows whose visits are all outside the imported data cannot be matched and are reported.
"""
from __future__ import annotations

import collections as C
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Appointment, Client


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s or "")).lower().replace("ʼ", "'").replace("’", "'")
    return re.sub(r"\s+", " ", s).strip()


def norm_phone(v) -> str | None:
    if v in (None, ""):
        return None
    if isinstance(v, float):
        v = f"{v:.0f}"
    d = re.sub(r"\D", "", str(v))
    if not d:
        return None
    if d.startswith("0") and len(d) == 10:  # 0XXXXXXXXX → +380XXXXXXXXX
        d = "38" + d
    return "+" + d


def build_index(s: Session) -> tuple[dict[tuple[str, str], set[int]], dict[int, str]]:
    by_minute: dict[tuple[str, str], set[int]] = C.defaultdict(set)
    for date, start, cid in s.execute(select(Appointment.date, Appointment.start, Appointment.client_id)
                                      .where(Appointment.client_id.is_not(None), Appointment.deleted.is_(False))):
        by_minute[(str(date), start)].add(cid)
    names = {c.altegio_id: norm_name(c.name) for c in s.scalars(select(Client)) if c.name}
    return by_minute, names


def match_row(row: dict, by_minute, names) -> tuple[int | None, str]:
    def at(dt_str):
        dt_str = str(dt_str or "").strip()
        return by_minute.get((dt_str[:10], dt_str[11:16]), set()) if len(dt_str) >= 16 else set()
    last, first = at(row.get("last_visit")), at(row.get("first_visit"))
    cand = (last & first) if (last and first) else (last or first)
    if not cand:
        return None, "no visit in data"
    n = norm_name(row.get("name"))
    if len(cand) > 1:
        named = {c for c in cand if names.get(c) == n}
        cand = named or cand
    if len(cand) != 1:
        return None, "ambiguous"
    cid = next(iter(cand))
    if names.get(cid) and n and names[cid] != n:  # the visit points to someone with a different name
        return None, "name mismatch"
    return cid, "matched"
