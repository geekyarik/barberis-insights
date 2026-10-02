"""Two-way sync of the admin's call list with a Google Sheet.

Tab "Call list": one row per open case (key: Case ID). The service owns the info columns; the admin fills
the outcome columns. Tab "Done": closed cases, without phone numbers.

    sync(session, backend)  — pull admin edits → push approved cases → archive closed cases. Idempotent.

The backend is an interface so tests use FakeSheet; production uses GspreadSheet (OAuth desktop flow).
"""
from __future__ import annotations

import datetime as dt
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import Barber, Client, ClientProfile, OutreachCase
from .service import CLOSED, OUTCOMES, set_status

CALL_TAB, DONE_TAB = "Call list", "Done"
INFO_COLS = ["Case ID", "Client", "Phone", "Usual barber", "Last visit", "Days since", "Visits", "Spent ₴", "Suggested offer", "Priority"]
ADMIN_COLS = ["Call date", "Outcome", "Offer given", "Next call", "Admin note"]
DONE_COLS = ["Case ID", "Client", "Status", "Contacted", "Returned", "Revenue ₴", "Offer given", "Admin note"]


class SheetBackend(Protocol):
    def ensure_tab(self, tab: str, headers: list[str], dropdowns: dict[str, list[str]] | None = None) -> None: ...
    def read(self, tab: str) -> list[dict]: ...
    def append(self, tab: str, rows: list[list]) -> None: ...
    def delete_keys(self, tab: str, key_col: str, keys: set[str]) -> None: ...


class FakeSheet:
    """In-memory sheet for tests and dry runs."""
    def __init__(self):
        self.tabs: dict[str, list[list]] = {}

    def ensure_tab(self, tab, headers, dropdowns=None):
        self.tabs.setdefault(tab, [list(headers)])

    def read(self, tab):
        rows = self.tabs.get(tab, [[]]); h = rows[0]
        return [dict(zip(h, r + [""] * (len(h) - len(r)))) for r in rows[1:]]

    def append(self, tab, rows):
        self.tabs[tab].extend([[str(x) if x is not None else "" for x in r] for r in rows])

    def delete_keys(self, tab, key_col, keys):
        h = self.tabs[tab][0]; i = h.index(key_col)
        self.tabs[tab] = [h] + [r for r in self.tabs[tab][1:] if str(r[i]) not in keys]

    def edit(self, tab, key, **cols):  # test helper: what the admin does
        h = self.tabs[tab][0]; i = h.index("Case ID")
        for r in self.tabs[tab][1:]:
            if str(r[i]) == str(key):
                for k, v in cols.items():
                    r[h.index(k)] = v


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


class GspreadSheet:
    """Google Sheets via gspread, using the stored OAuth token (see google_credentials)."""
    def __init__(self, sheet_id: str, interactive: bool = False):
        import gspread
        self.sh = gspread.authorize(google_credentials(interactive)).open_by_key(sheet_id)

    def _ws(self, tab):
        import gspread
        try:
            return self.sh.worksheet(tab)
        except gspread.WorksheetNotFound:
            return None

    def ensure_tab(self, tab, headers, dropdowns=None):
        ws = self._ws(tab)
        if ws is None:
            ws = self.sh.add_worksheet(tab, rows=1000, cols=len(headers))
            ws.update([headers], "A1")
            ws.freeze(rows=1)
        for col, values in (dropdowns or {}).items():
            idx = headers.index(col)
            self.sh.batch_update({"requests": [{"setDataValidation": {
                "range": {"sheetId": ws.id, "startRowIndex": 1, "startColumnIndex": idx, "endColumnIndex": idx + 1},
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


def _admin_state(row: dict) -> dict:
    return {c: str(row.get(c, "")).strip() for c in ADMIN_COLS}


def _parse_date(v: str) -> dt.date | None:
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(v.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def pull(s: Session, sheet: SheetBackend) -> int:
    """Record admin edits since the last sync as case events and status changes."""
    changed = 0
    for row in sheet.read(CALL_TAB):
        try:
            case = s.get(OutreachCase, int(row.get("Case ID")))
        except (TypeError, ValueError):
            continue
        if case is None:
            continue
        state = _admin_state(row)
        if state == (case.sheet_state or {}):
            continue
        prev = case.sheet_state or {}
        case.sheet_state = state
        outcome = state["Outcome"]
        status = OUTCOMES.get(outcome)
        note = state["Admin note"] if state["Admin note"] != prev.get("Admin note", "") else None
        offer = state["Offer given"] or None
        if status:
            set_status(s, case, status, source="sheet", note=note, offer=offer, on=_parse_date(state["Call date"]))
        elif note or offer:
            from .service import _event
            _event(case, "note", "sheet", note=note, offer_given=offer)
            if offer:
                case.offer_given = offer
        changed += 1
    return changed


def push(s: Session, sheet: SheetBackend) -> int:
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
        rows.append([c.id, cl.name if cl else f"client {c.client_id}", cl.phone if cl else "", barbers.get(p.usual_barber, "") if p else "",
                     str(p.last_visit) if p else "", p.days_since_last if p else "", p.visits if p else "", round(p.lifetime_spend) if p else "",
                     c.suggested_offer or "", c.priority] + [""] * len(ADMIN_COLS))
        set_status(s, c, "in_sheet", source="auto")
        c.sheet_state = {k: "" for k in ADMIN_COLS}
    sheet.append(CALL_TAB, rows)
    return len(rows)


def archive(s: Session, sheet: SheetBackend) -> int:
    """Move closed cases to the Done tab without phone numbers (retention: contacts leave the sheet when a case closes)."""
    on_sheet = {str(r.get("Case ID")) for r in sheet.read(CALL_TAB)}
    closed = [c for c in s.scalars(select(OutreachCase).where(OutreachCase.status.in_(CLOSED))) if str(c.id) in on_sheet]
    if not closed:
        return 0
    clients = {c.altegio_id: c for c in s.scalars(select(Client).where(Client.altegio_id.in_([c.client_id for c in closed])))}
    sheet.append(DONE_TAB, [[c.id, clients[c.client_id].name if c.client_id in clients else f"client {c.client_id}", c.status,
                             str(c.contacted_on or ""), str(c.returned_on or ""), c.revenue_recovered or "", c.offer_given or "",
                             (c.sheet_state or {}).get("Admin note", "")] for c in closed])
    sheet.delete_keys(CALL_TAB, "Case ID", {str(c.id) for c in closed})
    return len(closed)


def sync(s: Session, sheet: SheetBackend, offers: list[str]) -> dict:
    sheet.ensure_tab(CALL_TAB, INFO_COLS + ADMIN_COLS, {"Outcome": list(OUTCOMES), "Offer given": offers})
    sheet.ensure_tab(DONE_TAB, DONE_COLS)
    pulled = pull(s, sheet)
    from .attribution import attribute
    att = attribute(s)
    pushed = push(s, sheet)
    archived = archive(s, sheet)
    return {"pulled_changes": pulled, "pushed": pushed, "archived": archived, **att}
