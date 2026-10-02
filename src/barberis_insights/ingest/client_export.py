"""Import the client base exported from the Altegio web interface (Clients → Export, .xlsx or .csv).

Column headers vary by interface language, so they are matched against aliases (case- and space-insensitive).
Run `insights import-clients FILE --dry-run` first: it prints which columns were recognised.
"""
from __future__ import annotations

import collections as C
import csv
import re
from pathlib import Path

from sqlalchemy.orm import Session

from .clients import upsert_clients

ALIASES = {
    "id": ["id", "client id", "id клієнта", "id клиента", "ід", "номер"],
    "name": ["name", "full name", "client", "ім'я", "імя", "ім’я", "піб", "клієнт", "имя", "фио", "клиент"],
    "surname": ["surname", "last name", "прізвище", "фамилия"],
    "phone": ["phone", "phone number", "mobile", "телефон", "номер телефону", "мобільний", "номер телефона"],
    "email": ["email", "e-mail", "пошта", "електронна пошта", "почта"],
    "birthday": ["birthday", "birth date", "date of birth", "дата народження", "день народження", "дата рождения"],
    "consent": ["personal data processing", "consent", "згода на обробку", "згоден на обробку", "згода на обробку персональних даних", "согласие на обработку", "согласен на обработку"],
    "mass_ok": ["згоден отримувати розсилки", "згоден отримувати", "agrees to receive", "согласен получать"],
    "no_mass": ["excluded from campaigns", "no sms", "не надсилати", "виключити з розсилок", "исключить из рассылок"],
    "last_visit": ["останній візит", "last visit", "последний визит"],
    "first_visit": ["перший візит", "first visit", "первый визит"],
    "visits": ["кількість відвідувань", "visits", "количество визитов"],
    "comment": ["коментар", "comment", "комментарий"],
}

# Staff comments that mean "do not contact"
DNC_WORDS = ("не нагад", "не дзвон", "не турб", "не телефон", "не пиш", "do not call", "не звон", "не беспок")


def _norm(h: str) -> str:
    return re.sub(r"\s+", " ", str(h or "").strip().lower().replace("ʼ", "'"))


def map_columns(headers: list[str]) -> dict[str, int]:
    found = {}
    norm = [_norm(h) for h in headers]
    for field, names in ALIASES.items():
        for i, h in enumerate(norm):
            if h in names or any(h.startswith(n) for n in names if len(n) > 4):
                found.setdefault(field, i)
    return found


def _rows(path: Path) -> list[list]:
    if path.suffix.lower() == ".xls":  # legacy Excel, as Altegio exports it (its container trips xlrd's strict check)
        import xlrd
        sh = xlrd.open_workbook(str(path), ignore_workbook_corruption=True, logfile=open("/dev/null", "w")).sheet_by_index(0)
        return [sh.row_values(i) for i in range(sh.nrows)]
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        ws = load_workbook(path, read_only=True, data_only=True).active
        return [list(r) for r in ws.iter_rows(values_only=True)]
    text = path.read_text(encoding="utf-8-sig")
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    return [r for r in csv.reader(text.splitlines(), dialect)]


def _truthy(v) -> bool | None:
    if v is None or str(v).strip() == "":
        return None
    return str(v).strip().lower() in ("1", "true", "yes", "так", "да", "+", "✓")


def _yes(v) -> bool | None:
    s = str(v or "").strip().lower()
    return True if s in ("так", "да", "yes", "1", "true", "+") else False if s in ("ні", "нет", "no", "0", "false", "-") else None


def read_export(path: Path) -> tuple[dict[str, int], list[dict], dict]:
    """Parse the export into client dicts. Returns (recognised columns, rows, notes about the file)."""
    from .client_match import norm_phone
    rows = _rows(path)
    header_idx = next((i for i, r in enumerate(rows[:10]) if len(map_columns([str(c) for c in r])) >= 2), 0)
    cols = map_columns([str(c) for c in rows[header_idx]])
    out, info = [], {}
    body = rows[header_idx + 1:]
    # A consent column where every row says the same thing was never filled in: treat it as "not recorded".
    for f in ("consent", "mass_ok"):
        if f in cols:
            vals = {str(r[cols[f]]).strip() for r in body if cols[f] < len(r)}
            info[f + "_values"] = sorted(vals)
            info[f + "_recorded"] = len(vals) > 1
    for r in body:
        get = lambda f: r[cols[f]] if f in cols and cols[f] < len(r) else None
        cid = get("id")
        try:
            cid = int(float(cid)) if cid not in (None, "") else None
        except ValueError:
            cid = None
        comment = str(get("comment") or "").strip() or None
        out.append({"id": cid, "name": " ".join(str(x).strip() for x in (get("name"), get("surname")) if x),
                    "phone": norm_phone(get("phone")), "email": (str(get("email")).strip() or None) if get("email") else None,
                    "birthday": get("birthday") or None, "first_visit": get("first_visit"), "last_visit": get("last_visit"),
                    "personal_data_processing_allowed": _yes(get("consent")) if info.get("consent_recorded") else None,
                    "mass_notification_allowed": _yes(get("mass_ok")) if info.get("mass_ok_recorded") else None,
                    "comment": comment, "dnc": bool(comment and any(w in comment.lower() for w in DNC_WORDS))})
    return cols, out, info


def import_client_export(s: Session, path: Path) -> dict:
    from sqlalchemy import select

    from ..db.models import Client
    from .client_match import build_index, match_row
    from .base import sync_run
    cols, rows, info = read_export(path)
    stats = {"rows": len(rows), "matched": 0, "by_id": 0, "ambiguous": 0, "name_mismatch": 0, "duplicate_rows": 0, "no_visit_in_data": 0, "do_not_contact": 0}
    with sync_run(s, "client_export") as run:
        index = None if "id" in cols else build_index(s)
        items = []
        for r in rows:
            if r["id"]:
                stats["by_id"] += 1
            else:
                cid, why = match_row(r, *index)
                if not cid:
                    stats[{"ambiguous": "ambiguous", "name mismatch": "name_mismatch"}.get(why, "no_visit_in_data")] += 1
                    continue
                r["id"] = cid; stats["matched"] += 1
            items.append(r)
        # Two export rows on one client (duplicate client cards): keep the one whose name matches, else neither.
        from .client_match import norm_name
        by_id = C.defaultdict(list)
        for r in items:
            by_id[r["id"]].append(r)
        known = index[1] if index else {}
        items = []
        for cid, rs in by_id.items():
            if len(rs) > 1:
                rs = [r for r in rs if known.get(cid) == norm_name(r["name"])][:1] if known.get(cid) else []
                stats["duplicate_rows"] += 1
            items += rs
        upsert_clients(s, items)
        for r in items:  # fields upsert_clients doesn't know
            c = s.get(Client, r["id"])
            c.altegio_comment = r["comment"]
            if r["dnc"]:
                c.do_not_contact = True; stats["do_not_contact"] += 1
        run.counts = stats | {"columns": sorted(cols)}
    return {"columns": cols, "file_notes": info} | stats
