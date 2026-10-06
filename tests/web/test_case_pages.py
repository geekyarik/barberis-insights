"""The case queue and the case page against a throwaway database."""
import datetime as dt

import pytest
from conftest import client as make_client, sign_in, visit
from fastapi.testclient import TestClient
from metric_helpers import shop

from barberis_insights.cases import service as cases
from barberis_insights.clients.profile import rebuild_profiles
from barberis_insights.db.models import RiskCase
from barberis_insights.metrics import Dataset
from barberis_insights.web.app import app, db

TODAY = dt.date.today()


def regular(s, cid, last, every=28, n=6, cost=800):
    for i in range(n):
        visit(s, cid, last - dt.timedelta(days=every * (n - 1 - i)), 1, cost)


@pytest.fixture
def web(s):
    shop(s)
    regular(s, 10, TODAY - dt.timedelta(days=100), cost=500); make_client(s, 10).name = "Іван"
    regular(s, 11, TODAY - dt.timedelta(days=100), cost=1500); make_client(s, 11).name = "Петро"
    s.flush()
    rebuild_profiles(s, Dataset.load(s), TODAY)
    cases.detect(s, TODAY)
    s.commit()
    app.dependency_overrides[db] = lambda: s
    yield sign_in(TestClient(app, base_url="http://127.0.0.1:8765"))
    app.dependency_overrides.clear()


def test_the_queue_lists_open_cases_most_valuable_first(web, s):
    page = web.get("/risk").text
    assert "Петро" in page and "Іван" in page and page.index("Петро") < page.index("Іван")
    assert "межа 45" in page


def test_the_case_page_shows_the_line_the_offer_and_the_actions(web, s):
    case = s.query(RiskCase).filter_by(client_id=11).one()
    page = web.get(f"/cases/{case.id}").text
    assert "45 дн." in page and "Петро" in page and "Опрацювати кейс" in page and f"/cases/{case.id}/reject" in page
    assert "−15%" in page or "15%" in page


def test_processing_a_case_closes_it_and_opens_the_next(web, s):
    first = s.query(RiskCase).filter_by(client_id=11).one()
    r = web.post(f"/cases/{first.id}/no-answer", data={"note": "не взяв слухавку"}, follow_redirects=False)
    nxt = s.query(RiskCase).filter_by(client_id=10).one()
    assert r.status_code == 303 and r.headers["location"].startswith(f"/cases/{nxt.id}")
    s.refresh(first)
    assert first.status == "closed" and first.outcome == "no_answer" and first.processed_by == "admin"
    assert "Не додзвонилися" in web.get("/risk?tab=processed").text or "не додзвонилися" in web.get("/risk?tab=processed").text


def test_rejecting_with_other_and_no_comment_is_refused_with_a_message(web, s):
    case = s.query(RiskCase).filter_by(client_id=10).one()
    r = web.post(f"/cases/{case.id}/reject", data={"reason": "other", "comment": ""}, follow_redirects=False)
    assert r.status_code == 303 and "msg=" in r.headers["location"] and r.headers["location"].startswith(f"/cases/{case.id}")
    s.refresh(case)
    assert case.status == "open"


def test_a_booking_is_recorded_and_the_case_moves_to_the_booking_tab(web, s):
    case = s.query(RiskCase).filter_by(client_id=10).one()
    web.post(f"/cases/{case.id}/booked", data={"booked_for": str(TODAY + dt.timedelta(days=3)), "note": ""}, follow_redirects=False)
    s.refresh(case)
    assert case.status == "booking_exists" and case.contacted
    assert "Іван" in web.get("/risk?tab=booking").text and "Іван" not in web.get("/risk?tab=open").text


def test_the_results_page_and_the_all_tab_render(web, s):
    assert web.get("/outreach").status_code == 200
    assert web.get("/risk?tab=all").status_code == 200 and web.get("/risk?tab=processed&outcome=visited").status_code == 200
