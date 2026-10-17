"""Altegio's REST API: appointments, shifts and client contacts, fetched directly (replaces fetching through a headless Claude).

Authorization is two tokens in one header, `Bearer <partner token>, User <user token>`, and `Accept: application/vnd.api.v2+json` (Altegio support).
The partner token is fixed; the user token is obtained by logging in with the user's login and password (`POST /auth`) and kept in `var/`. When the API
answers 401 or 403 the adapter logs in once more and retries, so a stale token heals itself. Nothing here logs or returns a credential.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path
from typing import Iterator

import httpx

from ..config import settings
from .client_match import norm_phone  # noqa: F401  (re-exported for the client sync)

ATTENDANCE = {1: "arrived", -1: "no_show", 2: "confirmed", 0: "waiting"}     # what Altegio's `attendance` means in our statuses
PAGE = 200
RETRY_AFTER = (1.5, 4.0, 10.0)


class AltegioError(RuntimeError):
    """Something the owner must hear about: missing credentials, a refused login, an API error. Never contains a token or a password."""


class AltegioApi:
    def __init__(self, partner_token: str | None = None, login: str | None = None, password: str | None = None, base_url: str | None = None,
                 client: httpx.Client | None = None, token_file: Path | None = None, sleep=time.sleep):
        self.partner = partner_token or settings.altegio_partner_token
        self.login = login or settings.altegio_login
        self.password = password or settings.altegio_password
        self.base = (base_url or settings.altegio_base_url).rstrip("/")
        if not (self.partner and self.login and self.password):
            raise AltegioError("Altegio credentials are not set (INSIGHTS_ALTEGIO_PARTNER_TOKEN, INSIGHTS_ALTEGIO_LOGIN, INSIGHTS_ALTEGIO_PASSWORD in .env)")
        self.http = client or httpx.Client(timeout=60)
        self.token_file = token_file if token_file is not None else settings.data_dir / "altegio_token.json"
        self.sleep = sleep
        self._token: str | None = self._load_token()

    # ---------------------------------------------------------------- authorization
    def _load_token(self) -> str | None:
        try:
            return json.loads(self.token_file.read_text()).get("user_token")
        except (OSError, ValueError):
            return None

    def _save_token(self, token: str) -> None:
        try:
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            self.token_file.write_text(json.dumps({"user_token": token}))
            self.token_file.chmod(0o600)
        except OSError:
            pass                                                   # a token that cannot be kept is only logged in for again

    def _headers(self, with_user: bool = True) -> dict:
        auth = f"Bearer {self.partner}" + (f", User {self._token}" if with_user and self._token else "")
        return {"Authorization": auth, "Accept": "application/vnd.api.v2+json", "Content-Type": "application/json"}

    def authenticate(self) -> None:
        r = self.http.post(f"{self.base}/auth", headers=self._headers(with_user=False), json={"login": self.login, "password": self.password})
        data = (r.json() or {}).get("data") if r.headers.get("content-type", "").startswith("application/json") else None
        token = data.get("user_token") if isinstance(data, dict) else None
        if r.status_code >= 300 or not token:
            raise AltegioError(f"Altegio login failed (HTTP {r.status_code}): check the partner token, login and password")
        self._token = token
        self._save_token(token)

    # ---------------------------------------------------------------- requests
    def get(self, path: str, **params) -> dict:
        """GET and return the JSON body. Logs in first if there is no token, again on 401/403, and retries rate limits and server errors."""
        if not self._token:
            self.authenticate()
        reauthed = False
        for attempt in range(len(RETRY_AFTER) + 1):
            r = self.http.get(f"{self.base}{path}", headers=self._headers(), params={k: v for k, v in params.items() if v is not None})
            if r.status_code in (401, 403) and not reauthed:
                reauthed = True
                self.authenticate()
                continue
            if r.status_code in (429, 500, 502, 503, 504) and attempt < len(RETRY_AFTER):
                self.sleep(RETRY_AFTER[attempt])
                continue
            break
        try:
            body = r.json()
        except ValueError:
            raise AltegioError(f"Altegio answered {path} with HTTP {r.status_code} and no JSON")
        if r.status_code != 200 or body.get("success") is False:
            meta = body.get("meta") or {}
            raise AltegioError(f"Altegio refused {path} (HTTP {r.status_code}): {meta.get('message', 'no reason given') if isinstance(meta, dict) else meta}")
        return body

    def pages(self, path: str, **params) -> Iterator[dict]:
        """Every item of a paged list (`count` per page until the reported total is reached)."""
        page, seen = 1, 0
        while True:
            body = self.get(path, count=PAGE, page=page, **params)
            batch = body.get("data") or []
            yield from batch
            seen += len(batch)
            total = (body.get("meta") or {}).get("total_count")
            if not batch or (total is not None and seen >= total) or len(batch) < PAGE and total is None:
                return
            page += 1

    # ---------------------------------------------------------------- what we read
    def records(self, date_from: dt.date, date_to: dt.date) -> list[dict]:
        return list(self.pages(f"/records/{settings.location_id}", start_date=str(date_from), end_date=str(date_to)))

    def clients(self) -> list[dict]:
        """Every client card of the location (name, phone, email, comment, flags)."""
        return list(self.pages(f"/clients/{settings.location_id}"))

    def schedule(self, staff_id: int, date_from: dt.date, date_to: dt.date) -> list[dict]:
        return self.get(f"/schedule/{settings.location_id}/{staff_id}/{date_from}/{date_to}").get("data") or []

    def check(self) -> dict:
        """A harmless proof the credentials work: how many locations and staff the user can see."""
        return {"locations": len(self.get("/companies", my=1).get("data") or []), "staff": len(self.get(f"/company/{settings.location_id}/staff").get("data") or [])}


# -------------------------------------------------------------------- Altegio's shape -> ours
def to_appointment(rec: dict) -> dict:
    """An Altegio record in the shape `ingest.base.upsert_appointments` takes (the same as the old connector files)."""
    client = rec.get("client") or {}
    return {"id": rec["id"], "date": rec["date"], "status": ATTENDANCE.get(rec.get("attendance"), "unknown"),
            "team_member_id": rec.get("staff_id"), "team_member_name": (rec.get("staff") or {}).get("name"),
            "client_id": client.get("id") or None, "client_name": (client.get("display_name") or client.get("name") or "").strip(),
            "online": bool(rec.get("online")), "duration_seconds": rec.get("length") or 0,
            "total_cost": sum((sv.get("cost") or 0) for sv in rec.get("services") or []), "deleted": bool(rec.get("deleted")),
            "services": [{"title": sv.get("title") or "", "cost": sv.get("cost") or 0, "amount": sv.get("amount") or 1} for sv in rec.get("services") or []]}


def to_client_contact(rec: dict) -> dict | None:
    """What an appointment says about its client that we keep: id, phone and email (the name stays as first seen)."""
    c = rec.get("client") or {}
    if not c.get("id"):
        return None
    return {"id": c["id"], "phone": norm_phone(c.get("phone")), "email": (c.get("email") or "").strip() or None}


def to_schedule_payload(staff_id: int, days: list[dict]) -> dict:
    return {"team_member_id": staff_id, "items": [{"date": d["date"], "slots": d.get("slots") or [], "is_working": bool(d.get("is_working"))} for d in days]}
