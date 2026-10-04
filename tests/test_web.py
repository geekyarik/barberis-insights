"""Smoke-test every page and the main forms against the local database (skipped without imported data).
Writes made here are removed at the end."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from barberis_insights.config import settings

pytestmark = pytest.mark.skipif(not (settings.data_dir / "insights.sqlite").exists(), reason="local data not imported")


@pytest.fixture(scope="module")
def client():
    from barberis_insights.web.app import app
    return TestClient(app, base_url="http://127.0.0.1:8765")


@pytest.mark.parametrize("path", ["/", "/barber/olia", "/barber/kseniia?weeks=52", "/goals", "/reports", "/risk", "/risk?segment=lapsed&segment=one_time&show_all=true",
                                  "/outreach", "/context", "/context?q=price", "/hypotheses", "/playbook", "/data", "/api/metrics",
                                  "/api/goals?scope=team", "/api/weekly/tina", "/api/risk?limit=3", "/api/notes?q=price", "/api/measurements?scope=team&metric=util"])
def test_pages_render(client, path):
    r = client.get(path)
    assert r.status_code == 200, r.text[:500]


def test_client_page(client):
    from barberis_insights.db.models import ClientProfile
    from barberis_insights.db.session import session_scope
    with session_scope() as s:
        cid = s.scalar(select(ClientProfile.client_id).where(ClientProfile.segment == "overdue").limit(1))
    assert client.get(f"/client/{cid}").status_code == 200


def test_goal_and_note_round_trip(client):
    from barberis_insights.db.models import Goal, Note
    from barberis_insights.db.session import session_scope
    r = client.post("/goals", data={"scope": "olia", "title": "zz test goal", "metric": "online", "target": "70", "due": "2026-12-31", "next_url": "/goals"},
                    follow_redirects=False)
    assert r.status_code == 303
    with session_scope() as s:
        g = s.scalar(select(Goal).where(Goal.title == "zz test goal"))
        assert g and g.baseline == 54  # latest measured online share
        gid = g.id
    assert client.post(f"/goals/{gid}/delete", data={"confirm": "yes", "next_url": "/goals"}, follow_redirects=False).status_code == 303
    r = client.post("/context", data={"title": "zz test note", "date_from": "2026-10-02", "kind": "observation", "scopes": ["shop"], "body": "hello"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert "zz test note" in client.get("/context?q=hello").text
    with session_scope() as s:
        for n in s.scalars(select(Note).where(Note.title == "zz test note")):
            s.delete(n)


def test_cross_site_post_blocked(client):
    r = client.post("/goals/x/delete", data={"confirm": "yes"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
