"""The Context page against a throwaway database."""
import pytest
from conftest import visit
from fastapi.testclient import TestClient
from metric_helpers import shop

from barberis_insights.context import factors
from barberis_insights.db.models import Factor, FactorEvent
from barberis_insights.web.app import app, db


@pytest.fixture
def client(s):
    shop(s)
    s.commit()
    app.dependency_overrides[db] = lambda: s
    yield TestClient(app, base_url="http://127.0.0.1:8765")
    app.dependency_overrides.clear()


FORM = {"title": "Women's Day run-up", "date_from": "2026-03-03", "date_to": "2026-03-09", "kind": "external", "category": "holiday", "treatment": "annotate",
        "recurrence": "yearly", "lead_days": "5", "effect_metric": "visits", "effect_direction": "up", "size_min": "10", "size_max": "30", "scopes": ["shop"]}


def test_the_page_lists_factors_and_lenses(client, s):
    factors.add(s, "Price rise", "2026-03-01"); s.commit()
    r = client.get("/context")
    assert r.status_code == 200 and "Price rise" in r.text and "Clean weeks" in r.text and "припущення" in r.text


def test_adding_a_recurring_holiday_with_a_belief(client, s):
    assert client.post("/context", data=FORM, follow_redirects=False).status_code == 303
    f = s.query(Factor).one()
    assert (f.recurrence, f.lead_days, f.kind, f.category) == ("yearly", 5, "external", "holiday")
    assert f.expected_effects == [{"metric": "visits", "direction": "up", "size_min": 10.0, "size_max": 30.0}]
    page = client.get("/context").text
    assert "Women&#39;s Day run-up" in page and "щороку" in page and "Виміряти вплив" in page and "Перевірити припущення" in page


def test_a_bad_factor_is_refused_with_a_message(client, s):
    r = client.post("/context", data={**FORM, "treatment": "adjust"}, follow_redirects=False)
    assert r.status_code == 303 and "msg=" in r.headers["location"] and s.query(Factor).count() == 0


def test_the_old_note_form_still_works(client, s):
    r = client.post("/context", data={"title": "zz note", "date_from": "2026-03-02", "kind": "observation", "scopes": ["shop"], "body": "hello"}, follow_redirects=False)
    assert r.status_code == 303 and "zz note" in client.get("/context?q=hello").text
    f = s.query(Factor).one()
    assert (f.kind, f.category, f.treatment) == ("internal", "observation", "annotate")


def test_estimating_without_history_says_so_and_deleting_keeps_the_trail(client, s):
    client.post("/context", data=FORM)
    fid = s.query(Factor).one().id
    r = client.post(f"/context/{fid}/estimate", follow_redirects=False)
    assert r.status_code == 303 and "msg=" in r.headers["location"]
    assert client.post(f"/context/{fid}/delete", follow_redirects=False).status_code == 303
    assert s.query(Factor).count() == 0 and [e.kind for e in s.query(FactorEvent).order_by(FactorEvent.id)][-1] == "deleted"


def test_saving_a_lens(client, s):
    assert client.post("/lenses", data={"key": "holidays_out", "label": "Without holidays", "honour": ["exclude"]}, follow_redirects=False).status_code == 303
    assert "Without holidays" in client.get("/context").text
    bad = client.post("/lenses", data={"key": "raw", "label": "x", "honour": []}, follow_redirects=False)
    assert bad.status_code == 303 and "msg=" in bad.headers["location"]
