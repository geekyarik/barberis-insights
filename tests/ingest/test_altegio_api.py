"""The Altegio REST adapter against a simulated Altegio (httpx MockTransport): no network, no credentials."""
import datetime as dt
import json

import httpx
import pytest

from barberis_insights.ingest import altegio_api as api

PARTNER, LOGIN, PASSWORD = "partner-secret", "owner@example.test", "pw-secret"
BASE = "https://altegio.test/api/v1"


class Fake:
    """An Altegio that accepts one user token, hands out a new one on login, and pages its records."""
    def __init__(self, records=0):
        self.seen, self.token, self.records, self.logins = [], "tok-1", records, 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.replace("/api/v1", "")
        self.seen.append((request.method, path, dict(request.url.params), request.headers.get("authorization", "")))
        assert request.headers["accept"] == "application/vnd.api.v2+json"
        if path == "/auth":
            if json.loads(request.content) != {"login": LOGIN, "password": PASSWORD}:
                return httpx.Response(401, json={"success": False, "meta": {"message": "bad login"}})
            self.logins += 1
            self.token = f"tok-{self.logins + 1}"
            return httpx.Response(201, json={"success": True, "data": {"user_token": self.token}})
        if f", User {self.token}" not in request.headers.get("authorization", ""):
            return httpx.Response(403, json={"success": False, "data": None, "meta": {"message": "Insufficient rights"}})
        if path.startswith("/records/"):
            page, count = int(request.url.params["page"]), int(request.url.params["count"])
            lo = (page - 1) * count
            items = [{"id": i} for i in range(lo, min(lo + count, self.records))]
            return httpx.Response(200, json={"success": True, "data": items, "meta": {"page": page, "total_count": self.records}})
        if path.startswith("/schedule/"):
            return httpx.Response(200, json={"success": True, "data": [{"date": "2026-10-20", "is_working": 1, "slots": [{"from": "10:00", "to": "20:00"}]}], "meta": []})
        if path == "/companies":
            return httpx.Response(200, json={"success": True, "data": [{"id": 1}], "meta": []})
        return httpx.Response(200, json={"success": True, "data": [{"id": 1}, {"id": 2}], "meta": []})


def make(tmp_path, fake=None, password=PASSWORD):
    fake = fake or Fake()
    a = api.AltegioApi(PARTNER, LOGIN, password, BASE, httpx.Client(transport=httpx.MockTransport(fake.handler)), tmp_path / "tok.json", sleep=lambda _: None)
    return a, fake


def test_it_logs_in_once_and_sends_the_two_tokens_in_one_header(tmp_path):
    a, fake = make(tmp_path)
    assert a.check() == {"locations": 1, "staff": 2}
    auth = [x for x in fake.seen if x[1] == "/auth"]
    assert len(auth) == 1 and auth[0][3] == f"Bearer {PARTNER}"                       # logging in uses only the partner token
    assert all(x[3] == f"Bearer {PARTNER}, User tok-2" for x in fake.seen if x[1] != "/auth")


def test_a_stale_saved_token_heals_itself_with_one_new_login(tmp_path):
    (tmp_path / "tok.json").write_text(json.dumps({"user_token": "stale"}))
    a, fake = make(tmp_path)
    assert a.check()["staff"] == 2 and fake.logins == 1
    assert json.loads((tmp_path / "tok.json").read_text())["user_token"] == "tok-2"          # and it keeps the new one for next time
    assert (tmp_path / "tok.json").stat().st_mode & 0o077 == 0                                # readable by the owner only


def test_a_refused_login_says_so_and_never_shows_a_credential(tmp_path):
    a, _ = make(tmp_path, password="wrong")
    with pytest.raises(api.AltegioError) as e:
        a.check()
    assert "login failed" in str(e.value) and PARTNER not in str(e.value) and "wrong" not in str(e.value)


def test_missing_credentials_are_reported_before_any_request(tmp_path, monkeypatch):
    from barberis_insights.config import settings
    for name in ("altegio_partner_token", "altegio_login", "altegio_password"):
        monkeypatch.setattr(settings, name, None)             # the developer's own .env must not leak into the test
    with pytest.raises(api.AltegioError, match="credentials are not set"):
        api.AltegioApi("", "", "", "https://x.test", httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))), tmp_path / "t.json")


def test_records_are_paged_until_the_reported_total(tmp_path):
    a, fake = make(tmp_path, Fake(records=450))
    got = a.records(dt.date(2026, 10, 1), dt.date(2026, 10, 7))
    assert [r["id"] for r in got] == list(range(450))
    pages = [x[2]["page"] for x in fake.seen if x[1].startswith("/records/")]
    assert pages == ["1", "2", "3"] and [x for x in fake.seen if x[1].startswith("/records/")][0][2]["start_date"] == "2026-10-01"


def test_rate_limits_are_retried_then_succeed(tmp_path):
    calls = {"n": 0}
    base = Fake()

    def handler(request):
        if request.url.path.endswith("/companies") and calls["n"] < 2:
            calls["n"] += 1
            return httpx.Response(429, json={})
        return base.handler(request)
    a = api.AltegioApi(PARTNER, LOGIN, PASSWORD, BASE, httpx.Client(transport=httpx.MockTransport(handler)), tmp_path / "t.json", sleep=lambda _: None)
    assert a.check()["locations"] == 1 and calls["n"] == 2


def test_an_altegio_record_becomes_the_shape_the_importer_takes():
    rec = {"id": 5, "date": "2026-10-13 18:20:00", "attendance": -1, "confirmed": 1, "deleted": False, "online": True, "length": 1200, "staff_id": 9, "staff": {"name": "Оля"},
           "services": [{"title": "Cut", "cost": 850, "amount": 1}, {"title": "Beard", "cost": 400, "amount": 2}],
           "client": {"id": 77, "name": "Іван", "display_name": "Іван К.", "phone": "380501112233", "email": " a@b.test "}}
    a = api.to_appointment(rec)
    assert a["status"] == "no_show" and a["total_cost"] == 1250 and a["team_member_id"] == 9 and a["client_id"] == 77 and a["duration_seconds"] == 1200
    assert api.to_client_contact(rec) == {"id": 77, "phone": "+380501112233", "email": "a@b.test"}
    assert [api.to_appointment({**rec, "attendance": n})["status"] for n in (1, 2, 0)] == ["arrived", "confirmed", "waiting"]
    assert api.to_client_contact({"client": {}}) is None
    assert api.to_schedule_payload(9, [{"date": "2026-10-20", "is_working": 0, "slots": []}]) == {"team_member_id": 9, "items": [{"date": "2026-10-20", "slots": [], "is_working": False}]}
