"""Report pages against a throwaway database (not the real one)."""
import pytest
from conftest import visit
from fastapi.testclient import TestClient
from metric_helpers import shop

from barberis_insights.db.models import AnalysisRun, Measurement, ReportRun
from barberis_insights.web.app import app, db


@pytest.fixture
def client(s):
    shop(s)
    visit(s, 50, "2026-07-01", 2)
    s.commit()
    app.dependency_overrides[db] = lambda: s
    yield TestClient(app, base_url="http://127.0.0.1:8765")
    app.dependency_overrides.clear()


BUILD = {"kind": "barber_book", "barber": "a", "date_from": "2026-03-02", "date_to": "2026-03-15"}


def test_the_reports_page_lists_and_offers_to_build(client):
    r = client.get("/reports")
    assert r.status_code == 200 and "Книга барбера" in r.text and 'action="/reports/build"' in r.text


def test_building_a_barber_book_freezes_a_report_and_opens_it(client, s):
    r = client.post("/reports/build", data=BUILD, follow_redirects=False)
    assert r.status_code == 303
    page = client.get(r.headers["location"])
    assert page.status_code == 200 and "A · Книга барбера" in page.text and "Показники" in page.text and "Прострочені постійні клієнти" in page.text
    assert s.query(ReportRun).count() == 1 and s.query(AnalysisRun).count() == 9
    assert "/reports" in client.get("/reports").text and "Відкрити" in client.get("/reports").text


def test_a_team_comparison_page_renders(client):
    r = client.post("/reports/build", data={**BUILD, "kind": "team_comparison"}, follow_redirects=False)
    page = client.get(r.headers["location"])
    assert page.status_code == 200 and "Порівняння команди" in page.text
    assert "<th>A</th>" in page.text and "<th>B</th>" in page.text


def test_the_export_is_one_file_without_navigation_or_scripts(client):
    rid = client.post("/reports/build", data=BUILD, follow_redirects=False).headers["location"].split("/")[-1]
    r = client.get(f"/reports/{rid}/export")
    assert r.status_code == 200 and f"barberis-report-{rid}.html" in r.headers["content-disposition"]
    assert "<nav>" not in r.text and "<script" not in r.text and "Показники" in r.text


def test_the_report_language_follows_the_viewer(client):
    rid = client.post("/reports/build", data=BUILD, follow_redirects=False).headers["location"].split("/")[-1]
    client.cookies.set("lang", "en")
    assert "Barber book" in client.get(f"/reports/{rid}").text and "Overdue regulars" in client.get(f"/reports/{rid}").text


@pytest.mark.parametrize("data", [{**BUILD, "date_from": "2026-03-03"}, {**BUILD, "date_to": "2026-03-14"}, {**BUILD, "barber": "nobody"}])
def test_a_bad_window_or_barber_builds_nothing(client, s, data):
    r = client.post("/reports/build", data=data, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/reports?msg=")
    assert s.query(ReportRun).count() == 0


def test_an_unknown_report_is_a_404(client):
    assert client.get("/reports/999").status_code == 404 and client.get("/reports/999/export").status_code == 404


def test_the_snapshot_button_stores_a_run_and_its_measurement(client, s):
    r = client.post("/data/snapshot", data={"date_from": "2026-03-02", "date_to": "2026-03-15"}, follow_redirects=False)
    assert r.status_code == 303 and s.query(AnalysisRun).filter_by(analysis_key="barber_scorecard", created_by="dashboard").count() == 1
    assert s.query(Measurement).filter_by(scope="a", metric="util").count() == 1
    bad = client.post("/data/snapshot", data={"date_from": "2026-03-03", "date_to": "2026-03-16"}, follow_redirects=False)
    assert bad.status_code == 303 and s.query(AnalysisRun).count() == 1
