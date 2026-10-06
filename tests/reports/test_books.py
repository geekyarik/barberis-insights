import datetime as dt

import pytest
from conftest import visit
from metric_helpers import D, F, T, shop

from barberis_insights.reports import service as reports


def with_history(s):
    shop(s)
    for d in ("2025-12-01", "2026-01-10"):
        visit(s, 1, d, 1)                              # client 1 is a returning client
    visit(s, 50, "2026-07-01", 2)                      # the data runs on well past the 90-day follow-up
    s.flush()


def test_the_follow_up_window_is_the_latest_one_that_has_happened(s):
    with_history(s)
    # data ends 2026-07-01; a window ending 2026-03-15 needs data to 2026-06-13: already observed
    assert reports.followup_window(s, F, T) == (F, T)
    f, t = reports.followup_window(s, D("2026-06-15"), D("2026-06-28"))
    assert t + dt.timedelta(days=90) <= D("2026-07-01") and (t - f).days == 13 and t.weekday() == 6


def test_a_barber_book_is_composed_from_runs_and_frozen(s):
    with_history(s)
    r = reports.barber_book(s, "a", F, T)
    c = r.content
    assert r.report_key == "barber_book" and len(r.analysis_run_ids) == 9 and c["name"] == "A"
    assert set(c["sections"]) == {"scorecard", "weekly", "weekday", "retention", "cohorts", "sources", "exclusive", "overdue", "services"}
    assert c["sections"]["scorecard"]["kpis"]["revenue"] == 3000 and c["sections"]["retention"]["complete"] is True
    assert all(row["scope"] == "a" for row in c["sections"]["weekly"]["tables"]["weeks"])
    assert not any("phone" in str(c) for _ in [0])
    r.content = {}
    with pytest.raises(ValueError, match="immutable"):
        s.flush()
    s.rollback()


def test_a_book_for_an_unknown_barber_is_refused(s):
    with_history(s)
    with pytest.raises(ValueError):
        reports.barber_book(s, "nobody", F, T)


def test_a_team_comparison_has_every_barber_side_by_side(s):
    with_history(s)
    c = reports.team_comparison(s, F, T).content
    assert c["kind"] == "team_comparison" and set(c["sections"]["scorecard"]["kpis"]) == {"a", "b", "team"}
    assert c["sections"]["retention"]["kpis"]["a"]["clients"] == 3


def test_the_weekly_review_lists_a_client_once_even_if_overdue_with_two_barbers(s):
    for barber in (1, 2):
        for d in ("2026-01-05", "2026-01-12", "2026-01-19"):
            visit(s, 77, d, barber)                    # a regular of both barbers, silent since January
    s.flush()
    top = reports.weekly_review(s, F, T).content["overdue"]["top"]
    assert [r["client_id"] for r in top] == [77]
