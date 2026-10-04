import datetime as dt
import types

import pytest
from conftest import visit
from metric_helpers import D, F, T, shop

from barberis_insights.analyses import service
from barberis_insights.analyses.compare import compare_runs, not_comparable
from barberis_insights.db.models import AnalysisRun, Measurement


def test_a_run_is_stored_with_everything_needed_to_reproduce_it(s):
    shop(s)
    r = service.run(s, "barber_scorecard", F, T)
    assert r.id and (r.analysis_key, r.analysis_version, r.scope, r.lens) == ("barber_scorecard", 1, "team", "raw")
    assert r.metric_versions["risk_n"] == 2
    assert r.data_fingerprint["appointments"] == 5
    assert r.lens_resolved == [] and r.created_by == "cli"


def test_runs_are_immutable(s):
    shop(s)
    r = service.run(s, "overdue_regulars", F, T)
    s.flush()
    r.created_by = "someone"
    with pytest.raises(ValueError, match="immutable"):
        s.flush()
    s.rollback()


def test_rerunning_creates_a_new_run(s):
    shop(s)
    a, b = service.run(s, "overdue_regulars", F, T), service.run(s, "overdue_regulars", F, T)
    assert a.id != b.id and len(service.list_runs(s, "overdue_regulars")) == 2


@pytest.mark.parametrize("f,t", [("2026-03-03", "2026-03-15"), ("2026-03-02", "2026-03-14"), ("2026-03-15", "2026-03-02")])
def test_a_window_is_whole_iso_weeks(s, f, t):
    with pytest.raises(ValueError, match="whole ISO weeks"):
        service.run(s, "overdue_regulars", D(f), D(t))


def test_unknown_analysis_and_scope_are_refused(s):
    shop(s)
    with pytest.raises(KeyError):
        service.run(s, "nope", F, T)
    with pytest.raises(ValueError, match="scope"):
        service.run(s, "overdue_regulars", F, T, scope="nobody")


def test_a_measurement_is_stored_only_when_asked_and_only_as_a_projection_of_a_run(s):
    shop(s)
    service.run(s, "barber_scorecard", F, T)
    s.flush()
    assert s.query(Measurement).count() == 0
    r = service.run(s, "barber_scorecard", F, T, label="test")
    s.flush()
    rows = s.query(Measurement).filter_by(scope="a", metric="util").all()
    assert len(rows) == 1 and rows[0].asof == T and rows[0].metric_version == 1 and rows[0].value == r.result["kpis"]["a"]["util"]


def _row(**kw):
    base = dict(id=1, analysis_key="x", analysis_version=1, scope="team", lens="raw", lens_resolved=[], params={}, metric_versions={"util": 1},
                window_from=D("2026-03-02"), window_to=D("2026-03-15"), result={"kpis": {"a": {"util": 50, "lost_pct": 20}}, "directions": {"util": "up", "lost_pct": "down"},
                                                                                "findings": [], "complete": True})
    return types.SimpleNamespace(**(base | kw))


def test_comparison_judges_each_kpi_by_its_direction():
    before = _row()
    after = _row(id=2, result={"kpis": {"a": {"util": 55, "lost_pct": 25}}, "directions": {"util": "up", "lost_pct": "down"},
                               "findings": [{"code": "bad", "severity": "warn", "scope": "a", "evidence": {}}], "complete": True})
    c = compare_runs(before, after)
    assert c["comparable"] and c["changes"]["a"]["util"]["verdict"] == "better" and c["changes"]["a"]["lost_pct"]["verdict"] == "worse"
    assert [f["code"] for f in c["findings"]["new"]] == ["bad"] and c["findings"]["resolved"] == []


@pytest.mark.parametrize("change,reason", [
    ({"analysis_version": 2}, "analysis version"),
    ({"scope": "a"}, "scope differs"),
    ({"lens_resolved": [{"factor": 1}]}, "lens"),
    ({"params": {"lookahead_days": 30}}, "parameters"),
    ({"metric_versions": {"util": 2}}, "metric definitions differ: util"),
    ({"window_to": D("2026-03-22")}, "different lengths"),
])
def test_runs_that_differ_in_definition_are_not_compared(change, reason):
    why = not_comparable(_row(), _row(id=2, **change))
    assert any(reason in w for w in why)
    assert compare_runs(_row(), _row(id=2, **change))["comparable"] is False


def test_an_incomplete_window_is_not_compared():
    incomplete = _row(id=2, result={"kpis": {}, "findings": [], "complete": False})
    assert any("not fully observed" in w for w in not_comparable(_row(), incomplete))
