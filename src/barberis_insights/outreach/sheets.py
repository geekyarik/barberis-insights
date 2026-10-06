"""Two-way sync of the admin's call list with a Google Sheet.

Tab "call" (Ukrainian: «Обдзвін»): one row per open case, keyed by the case id column. The service owns the info
columns; the admin fills the outcome columns. Tab "done" («Завершені»): closed cases, without phone numbers.

    sync(session, backend, offers, lang)  — pull admin edits → attribute returns → push approved cases → archive closed ones. Idempotent.

Columns, tabs, outcomes, offers and statuses have stable internal keys; what the admin sees comes from the i18n
catalogs in the sheet's language (settings.sheet_lang). Reading accepts the labels of every language, so switching
languages, or an older English sheet, keeps working. A tab with no data rows is renamed and re-headed in the
configured language; a tab already in use keeps its headers.

The backend is an interface so tests use FakeSheet; production uses GspreadSheet (service account or OAuth).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import Barber, Client, ClientProfile, OutreachCase
from ..i18n import LANGUAGES, all_labels, normalize, t
from .service import CLOSED, OUTCOMES, _event, set_status

INFO_COLS = ["case_id", "client", "phone", "usual_barber", "last_visit", "days_since", "visits", "spent", "suggested_offer", "priority"]
ADMIN_COLS = ["call_date", "outcome", "offer_given", "next_call", "admin_note"]
CALL_COLS = INFO_COLS + ADMIN_COLS
DONE_COLS = ["case_id", "client", "status", "contacted", "returned", "revenue", "offer_given", "admin_note"]


class SheetBackend(Protocol):
    def tabs(self) -> list[str]: ...
    def create_tab(self, tab: str, headers: list[str]) -> None: ...
    def rename_tab(self, old: str, new: str) -> None: ...
    def headers(self, tab: str) -> list[str]: ...
    def set_headers(self, tab: str, headers: list[str]) -> None: ...
    def set_dropdown(self, tab: str, col_index: int, values: list[str]) -> None: ...
    def read(self, tab: str) -> list[dict]: ...
    def append(self, tab: str, rows: list[list]) -> None: ...
    def delete_keys(self, tab: str, key_col: str, keys: set[str]) -> None: ...


class FakeSheet:
    """In-memory sheet for tests and dry runs."""
    def __init__(self):
        self.tabs_: dict[str, list[list]] = {}
        self.dropdowns: dict[tuple[str, int], list[str]] = {}

    def tabs(self):
        return list(self.tabs_)

    def create_tab(self, tab, headers):
        self.tabs_[tab] = [list(headers)]

    def rename_tab(self, old, new):
        self.tabs_[new] = self.tabs_.pop(old)

    def headers(self, tab):
        return list(self.tabs_[tab][0])

    def set_headers(self, tab, headers):
        self.tabs_[tab][0] = list(headers)

    def set_dropdown(self, tab, col_index, values):
        self.dropdowns[(tab, col_index)] = list(values)

    def read(self, tab):
        rows = self.tabs_.get(tab, [[]]); h = rows[0]
        return [dict(zip(h, r + [""] * (len(h) - len(r)))) for r in rows[1:]]

    def append(self, tab, rows):
        self.tabs_[tab].extend([[str(x) if x is not None else "" for x in r] for r in rows])

    def delete_keys(self, tab, key_col, keys):
        h = self.tabs_[tab][0]; i = h.index(key_col)
        self.tabs_[tab] = [h] + [r for r in self.tabs_[tab][1:] if str(r[i]) not in keys]

    def edit(self, tab, key, **cols):  # test helper: what the admin does (cols by header text)
        h = self.tabs_[tab][0]
        for r in self.tabs_[tab][1:]:
            if str(r[0]) == str(key):
                for k, v in cols.items():
                    r[h.index(k)] = v


# ---------------------------------------------------------------- labels in every language


def _lookup(prefix: str) -> dict[str, str]:
    """label (any language, case-insensitive) or code → code."""
    out = {}
    for code, langs in all_labels(prefix).items():
        out[code.lower()] = code
        for label in langs.values():
            out[label.strip().lower()] = code
    return out


def tab_name(kind: str, lang: str) -> str:
    return t(f"sheet.tab.{kind}", lang)


def header(col: str, lang: str) -> str:
    return t(f"sheet.col.{col}", lang)


def outcome_code(text: str) -> str | None:
    return _lookup("outcome.").get(str(text).strip().lower()) if str(text).strip() else None


def offer_code(text: str) -> str | None:
    """Offer picked or typed by the admin → offer code; unknown free text is kept as written."""
    text = str(text).strip()
    return _lookup("offer.").get(text.lower(), text) if text else None


def offer_label(code: str | None, lang: str) -> str:
    if not code:
        return ""
    label = t(f"offer.{code}", lang)
    return code if label == f"offer.{code}" else label


@dataclass
class Tab:
    name: str
    headers: list[str]          # as they are in the sheet
    keys: list[str | None]      # column key for each header (None = a column we don't know, left alone)

    def header_for(self, key: str) -> str | None:
        return self.headers[self.keys.index(key)] if key in self.keys else None

    def row(self, values: dict) -> list:
        return [values.get(k, "") if k else "" for k in self.keys]

    def as_keys(self, record: dict) -> dict:
        return {k: str(record.get(h, "")).strip() for h, k in zip(self.headers, self.keys) if k}


def ensure(sheet: SheetBackend, kind: str, cols: list[str], lang: str) -> Tab:
    """Find the tab under its name in any language (create it if missing) and work out its column layout."""
    wanted = tab_name(kind, lang)
    names = [wanted] + [tab_name(kind, other) for other in LANGUAGES if other != lang]
    existing = next((n for n in names if n in sheet.tabs()), None)
    labels = [header(c, lang) for c in cols]
    if existing is None:
        sheet.create_tab(wanted, labels)
        existing = wanted
    elif not sheet.read(existing):  # nothing in it yet: switch it to the configured language (and add new columns)
        if existing != wanted:
            sheet.rename_tab(existing, wanted); existing = wanted
        if sheet.headers(existing) != labels:
            sheet.set_headers(existing, labels)
    found = sheet.headers(existing)
    col_of = {}
    for col, langs in all_labels("sheet.col.").items():
        for label in langs.values():
            col_of[label] = col
    return Tab(existing, found, [col_of.get(h) if col_of.get(h) in cols else None for h in found])


# ---------------------------------------------------------------- sync steps


def pull(s: Session, sheet: SheetBackend, tab: Tab) -> int:
    """Record admin edits since the last sync as case events and status changes."""
    changed = 0
    for record in sheet.read(tab.name):
        row = tab.as_keys(record)
        try:
            case = s.get(OutreachCase, int(row.get("case_id")))
        except (TypeError, ValueError):
            continue
        if case is None:
            continue
        state = {c: row.get(c, "") for c in ADMIN_COLS}
        if state == (case.sheet_state or {}):
            continue
        prev = case.sheet_state or {}
        case.sheet_state = state
        status = OUTCOMES.get(outcome_code(state["outcome"]))
        note = state["admin_note"] if state["admin_note"] != prev.get("admin_note", "") else None
        offer = offer_code(state["offer_given"])
        if status:
            set_status(s, case, status, source="sheet", note=note, offer=offer, on=_parse_date(state["call_date"]))
        elif note or offer:
            _event(case, "note", "sheet", note=note, offer_given=offer)
            if offer:
                case.offer_given = offer
        changed += 1
    return changed


def push(s: Session, sheet: SheetBackend, tab: Tab, lang: str) -> int:
    """Add approved cases to the call list."""
    cases = list(s.scalars(select(OutreachCase).where(OutreachCase.status == "approved").order_by(OutreachCase.priority.desc())))
    if not cases:
        return 0
    ids = [c.client_id for c in cases]
    clients = {c.altegio_id: c for c in s.scalars(select(Client).where(Client.altegio_id.in_(ids)))}
    profiles = {p.client_id: p for p in s.scalars(select(ClientProfile).where(ClientProfile.client_id.in_(ids)))}
    barbers = {b.altegio_id: b.name for b in s.scalars(select(Barber))}
    rows = []
    for c in cases:
        cl, p = clients.get(c.client_id), profiles.get(c.client_id)
        rows.append(tab.row({
            "case_id": c.id, "client": cl.name if cl and cl.name else t("client.fallback", lang, id=c.client_id),
            "phone": cl.phone if cl else "", "usual_barber": barbers.get(p.usual_barber, "") if p else "",
            "last_visit": str(p.last_visit) if p else "", "days_since": p.days_since_last if p else "", "visits": p.visits if p else "",
            "spent": round(p.lifetime_spend) if p else "", "suggested_offer": offer_label(c.suggested_offer, lang), "priority": c.priority}))
        set_status(s, c, "in_sheet", source="auto")
        c.sheet_state = {k: "" for k in ADMIN_COLS}
    sheet.append(tab.name, rows)
    return len(rows)


def archive(s: Session, sheet: SheetBackend, call: Tab, done: Tab, lang: str) -> int:
    """Move closed cases to the done tab without phone numbers (retention: contacts leave the sheet when a case closes)."""
    on_sheet = {tab_row.get("case_id") for tab_row in map(call.as_keys, sheet.read(call.name))}
    closed = [c for c in s.scalars(select(OutreachCase).where(OutreachCase.status.in_(CLOSED))) if str(c.id) in on_sheet]
    if not closed:
        return 0
    clients = {c.altegio_id: c for c in s.scalars(select(Client).where(Client.altegio_id.in_([c.client_id for c in closed])))}
    sheet.append(done.name, [done.row({
        "case_id": c.id, "client": clients[c.client_id].name if c.client_id in clients else t("client.fallback", lang, id=c.client_id),
        "status": t(f"status.{c.status}", lang), "contacted": str(c.contacted_on or ""), "returned": str(c.returned_on or ""),
        "revenue": c.revenue_recovered or "", "offer_given": offer_label(c.offer_given, lang),
        "admin_note": (c.sheet_state or {}).get("admin_note", "")}) for c in closed])
    sheet.delete_keys(call.name, call.header_for("case_id"), {str(c.id) for c in closed})
    return len(closed)


def prepare(sheet: SheetBackend, offers: list[str], lang: str | None = None) -> tuple[Tab, Tab]:
    """Make sure both tabs exist with known columns, and refresh the admin's dropdowns."""
    lang = normalize(lang or settings.sheet_lang)
    call, done = ensure(sheet, "call", CALL_COLS, lang), ensure(sheet, "done", DONE_COLS, lang)
    for key, values in (("outcome", [t(f"outcome.{o}", lang) for o in OUTCOMES]), ("offer_given", [offer_label(o, lang) for o in offers])):
        if key in call.keys:
            sheet.set_dropdown(call.name, call.keys.index(key), values)
    return call, done


def sync(s: Session, sheet: SheetBackend, offers: list[str], lang: str | None = None) -> dict:
    lang = normalize(lang or settings.sheet_lang)
    call, done = prepare(sheet, offers, lang)
    pulled = pull(s, sheet, call)
    from .attribution import attribute
    att = attribute(s)
    pushed = push(s, sheet, call, lang)
    archived = archive(s, sheet, call, done, lang)
    return {"pulled_changes": pulled, "pushed": pushed, "archived": archived, **att}


def _parse_date(v: str) -> dt.date | None:
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(v.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]  # only Sheets, nothing else in the Google account
OAUTH_PORT = 8766  # a Web-type OAuth client must list http://localhost:8766/ as an authorized redirect URI


def google_credentials(interactive: bool = True):
    """Load the saved token, refresh it, or run the one-time browser sign-in."""
    import json

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    client, token = settings.data_dir / "google_oauth_client.json", settings.data_dir / "google_token.json"
    creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not interactive:
            raise RuntimeError("Google sign-in needed: run `insights sheet-auth` once.")
        if not client.exists():
            raise FileNotFoundError(f"Put the Google OAuth client JSON at {client} (README: Admin call sheet setup)")
        cfg = json.loads(client.read_text())
        flow = InstalledAppFlow.from_client_config(cfg, SCOPES)
        creds = flow.run_local_server(host="localhost", port=OAUTH_PORT if "web" in cfg else 0, open_browser=True,
                                      authorization_prompt_message="Opening Google sign-in in your browser: {url}",
                                      success_message="Signed in. You can close this tab and return to the terminal.")
    token.write_text(creds.to_json()); token.chmod(0o600)
    return creds


SERVICE_ACCOUNT_FILE = "google_service_account.json"  # preferred: no browser sign-in, no expiry, sees only sheets shared with it


def service_account_email() -> str | None:
    import json
    p = settings.data_dir / SERVICE_ACCOUNT_FILE
    return json.loads(p.read_text()).get("client_email") if p.exists() else None


def _explain(e: Exception) -> str:
    """Turn gspread's wrapped Google error into an actionable message."""
    cause = e if getattr(e, "response", None) is not None else (e.__cause__ or e.__context__)
    resp = getattr(cause, "response", None)
    info = {}
    try:
        info = resp.json().get("error", {}) if resp is not None else {}
    except ValueError:
        pass
    reasons = {d.get("reason") for d in info.get("details", [])}
    if "SERVICE_DISABLED" in reasons:
        return ("Google Sheets API is not enabled in the Google Cloud project of this key. Enable “Google Sheets API” "
                "(APIs & Services → Library), wait a few minutes, then retry.")
    if (resp is not None and resp.status_code in (403, 404)) or isinstance(e, gspread_not_found()):
        return f"The service account can't open the sheet. Share it with {service_account_email()} as Editor. ({info.get('message', e)})"
    return f"Google Sheets error: {info.get('message') or e}"


def gspread_not_found():
    import gspread
    return gspread.exceptions.SpreadsheetNotFound


class GspreadSheet:
    """Google Sheets via gspread. Uses a service-account key (var/google_service_account.json) when present,
    otherwise the OAuth sign-in token (see google_credentials)."""
    def __init__(self, sheet_id: str, interactive: bool = False):
        import gspread
        sa = settings.data_dir / SERVICE_ACCOUNT_FILE
        if sa.exists():
            gc = gspread.service_account(filename=str(sa), scopes=SCOPES)
            try:
                self.sh = gc.open_by_key(sheet_id)
            except (gspread.exceptions.SpreadsheetNotFound, gspread.exceptions.APIError, PermissionError) as e:
                raise RuntimeError(_explain(e)) from e
        else:
            self.sh = gspread.authorize(google_credentials(interactive)).open_by_key(sheet_id)

    def _ws(self, tab):
        import gspread
        try:
            return self.sh.worksheet(tab)
        except gspread.WorksheetNotFound:
            return None

    def tabs(self):
        return [w.title for w in self.sh.worksheets()]

    def create_tab(self, tab, headers):
        ws = self.sh.add_worksheet(tab, rows=1000, cols=max(len(headers), 1))
        ws.update([headers], "A1")
        ws.freeze(rows=1)

    def rename_tab(self, old, new):
        self._ws(old).update_title(new)

    def headers(self, tab):
        return self._ws(tab).row_values(1)

    def set_headers(self, tab, headers):
        ws = self._ws(tab)
        if ws.col_count < len(headers):
            ws.add_cols(len(headers) - ws.col_count)
        ws.update([headers], "A1")

    def set_dropdown(self, tab, col_index, values):
        ws = self._ws(tab)
        self.sh.batch_update({"requests": [{"setDataValidation": {
            "range": {"sheetId": ws.id, "startRowIndex": 1, "startColumnIndex": col_index, "endColumnIndex": col_index + 1},
            "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in values]}, "showCustomUi": True, "strict": False}}}]})

    def read(self, tab):
        ws = self._ws(tab)
        return ws.get_all_records(default_blank="") if ws else []

    def append(self, tab, rows):
        if rows:
            self._ws(tab).append_rows([[("" if x is None else x) for x in r] for r in rows], value_input_option="USER_ENTERED")

    def delete_keys(self, tab, key_col, keys):
        ws = self._ws(tab)
        col = ws.row_values(1).index(key_col) + 1
        vals = ws.col_values(col)
        for i in sorted([i + 1 for i, v in enumerate(vals) if i > 0 and str(v) in keys], reverse=True):
            ws.delete_rows(i)
