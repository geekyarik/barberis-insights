import datetime as dt

import pytest
from conftest import visit
from metric_helpers import D, F, T, shop, slot

from barberis_insights.analyses import effects, service
from barberis_insights.context import factors
from barberis_insights.context import service as notes
from barberis_insights.db.models import FactorEvent, Hypothesis
from barberis_insights.experiments import factor_link


def test_a_factor_is_checked_when_it_is_saved(s):
    with pytest.raises(ValueError, match="adjust_factor"):
        factors.add(s, "x", "2026-03-01", treatment="adjust")
    with pytest.raises(ValueError, match="client"):
        factors.add(s, "x", "2026-03-01", treatment="suppress_overdue", scopes=["shop"])
    with pytest.raises(ValueError, match="date_to"):
        factors.add(s, "x", "2026-03-05", "2026-03-01")
    with pytest.raises(ValueError, match="kind"):
        factors.add(s, "x", "2026-03-01", kind="weather")
    with pytest.raises(ValueError, match="direction"):
        factors.add(s, "x", "2026-03-01", expected_effects=[{"metric": "util"}])


def test_changes_leave_an_audit_trail(s):
    f = factors.add(s, "Outage", "2026-03-03")
    factors.update(s, f.id, title="Long outage", date_to="2026-03-04")
    factors.delete(s, f.id)
    s.flush()
    assert [e.kind for e in s.query(FactorEvent).order_by(FactorEvent.id)] == ["created", "updated", "deleted"]
    assert s.query(FactorEvent).filter_by(kind="updated").one().detail["changes"]["title"] == ["Outage", "Long outage"]


def test_a_yearly_factor_recurs_in_every_year_with_its_run_up(s):
    f = factors.add(s, "New Year", "2025-12-31", "2026-01-01", recurrence="yearly", lead_days=5, category="holiday")
    assert factors.occurrences(f, D("2023-12-20"), D("2024-01-03")) == [(D("2023-12-26"), D("2024-01-01"))]       # before the year it was entered for
    assert factors.occurrences(f, D("2026-06-01"), D("2026-06-30")) == []
    assert factors.occurrences(f, D("2025-12-28"), D("2026-01-05")) == [(D("2025-12-26"), D("2026-01-01"))]


def test_a_single_occurrence_and_leap_day(s):
    once = factors.add(s, "Outage", "2026-03-03")
    assert factors.occurrences(once, D("2025-03-01"), D("2025-03-31")) == []
    leap = factors.add(s, "Leap", "2024-02-29", recurrence="yearly")
    assert factors.occurrences(leap, D("2025-02-20"), D("2025-03-05")) == [(D("2025-02-28"), D("2025-02-28"))]


def test_scopes(s):
    shopwide = factors.add(s, "Holiday", "2026-03-08", scopes=["shop"])
    one = factors.add(s, "Olia away", "2026-03-08", scopes=["a"])
    assert factors.applies_to(shopwide, "a") and factors.applies_to(shopwide, "b") and not factors.applies_to(shopwide, "client:5")
    assert factors.applies_to(one, "a") and not factors.applies_to(one, "b")
    assert [x.title for x in factors.in_force(s, D("2026-03-01"), D("2026-03-31"), "b")] == ["Holiday"]


def test_notes_are_factors_and_the_old_calls_still_work(s):
    n = notes.add(s, "Competitor opened nearby", "2026-02-01", "two streets away", "external", ["shop"], ["competition"])
    assert (n.kind, n.category, n.treatment) == ("external", "other", "annotate")
    old = notes.add(s, "Price rise", "2026-03-01", kind="decision")
    assert (old.kind, old.category) == ("internal", "decision")
    assert [x.title for x in notes.search(s, "competitor")] == ["Competitor opened nearby"] and notes.as_dict(n)["kind"] == "external"


def test_raw_lens_resolves_to_nothing_and_clean_honours_exclude_and_adjust(s):
    ex = factors.add(s, "Closed", "2026-03-09", treatment="exclude", kind="external")
    adj = factors.add(s, "Late start", "2026-03-03", treatment="adjust", adjust_factor=0.5, scopes=["a"])
    factors.add(s, "Just a note", "2026-03-04")
    factors.add(s, "Away", "2026-03-04", treatment="suppress_overdue", scopes=["client:5"])
    assert factors.resolve(s, "raw", F, T) == []
    got = factors.resolve(s, "clean", F, T)
    assert [(r["factor_id"], r["treatment"]) for r in got] == [(ex.id, "exclude"), (adj.id, "adjust")]
    assert got[0]["periods"] == [["2026-03-09", "2026-03-09"]] and got[1]["adjust_factor"] == 0.5
    assert factors.resolve(s, "clean", D("2026-06-01"), D("2026-06-14")) == []
    with pytest.raises(ValueError, match="unknown lens"):
        factors.resolve(s, "nope", F, T)


def test_a_custom_lens_can_pick_a_category(s):
    factors.create_lens(s, "holidays_out", "Without holidays", ["exclude"], categories=["holiday"])
    h = factors.add(s, "Holiday", "2026-03-08", treatment="exclude", category="holiday")
    factors.add(s, "Closed", "2026-03-09", treatment="exclude", category="other")
    assert [r["factor_id"] for r in factors.resolve(s, "holidays_out", F, T)] == [h.id]
    with pytest.raises(ValueError):
        factors.create_lens(s, "raw", "x", [])


def test_an_excluded_day_leaves_the_numbers(s):
    shop(s)                                             # a's visits: 3/2 x2, 3/3, 3/9; no-show 3/9; 12 scheduled hours
    factors.add(s, "Closed", "2026-03-09", treatment="exclude", kind="external")
    raw = service.run(s, "barber_scorecard", F, T).result["kpis"]["a"]
    clean = service.run(s, "barber_scorecard", F, T, lens="clean").result["kpis"]["a"]
    assert (raw["revenue"], raw["visits"], raw["util"]) == (3000, 4, 41.7)
    assert (clean["revenue"], clean["visits"], clean["util"]) == (2300, 3, 37.5)    # 3 of 8 scheduled hours, 3/9 gone


def test_adjusted_capacity_shrinks_scheduled_time(s):
    shop(s)
    factors.add(s, "Late start", "2026-03-03", treatment="adjust", adjust_factor=0.5, scopes=["a"])
    util = service.run(s, "barber_scorecard", F, T, lens="clean").result["kpis"]["a"]["util"]
    assert util == round(100 * 300 / (720 - 120), 1)                               # Tuesday 4 h counts as 2 h


def test_a_run_stores_the_factors_its_lens_resolved_to(s):
    shop(s)
    f = factors.add(s, "Closed", "2026-03-09", treatment="exclude")
    r = service.run(s, "barber_scorecard", F, T, lens="clean")
    assert r.lens == "clean" and r.lens_resolved[0]["factor_id"] == f.id and r.result["context"]["factors"] == [f.id]


def test_runs_under_different_lenses_are_not_compared(s):
    shop(s)
    a, b = service.run(s, "barber_scorecard", F, T), service.run(s, "barber_scorecard", F, T, lens="clean")
    s.flush()
    assert service.compare(s, a.id, b.id)["comparable"] is False


def test_the_same_lens_resolving_to_different_factors_is_not_compared(s):
    shop(s)
    first = service.run(s, "barber_scorecard", D("2026-03-02"), D("2026-03-15"), lens="clean")
    factors.add(s, "Closed", "2026-03-20", treatment="exclude")
    second = service.run(s, "barber_scorecard", D("2026-03-09"), D("2026-03-22"), lens="clean")
    s.flush()
    out = service.compare(s, first.id, second.id)
    assert out["comparable"] is False and any("lens" in r for r in out["reasons"])


def test_analyses_that_ignore_lenses_refuse_one(s):
    shop(s)
    with pytest.raises(ValueError, match="does not honour a lens"):
        service.run(s, "weekly_book", F, T, lens="clean")


def season_year(s, year, last_week=52):
    for w in range(1, last_week + 1):
        for k in range(6 if w == 10 else 3):
            visit(s, w * 100 + k + year * 100000, dt.date.fromisocalendar(year, w, 1), 1, 800)


def test_a_recurring_factors_effect_comes_from_the_seasonality_analysis(s):
    season_year(s, 2024); season_year(s, 2025); season_year(s, 2026, last_week=12)
    f = factors.add(s, "Women's Day run-up", "2025-03-03", "2025-03-09", recurrence="yearly", category="holiday")
    run = effects.estimate(s, f.id, today=D("2026-06-01"))
    assert run.analysis_key == "seasonality" and f.effect_run_id == run.id
    e = effects.summary(s, f)
    assert e["enough_history"] is True and e["years_observed"] == 2 and e["expected_visits_index"] > 1.4
    assert s.query(FactorEvent).filter_by(kind="effect_estimated").count() == 1


def test_one_year_of_history_is_not_enough(s):
    season_year(s, 2025); season_year(s, 2026, last_week=12)
    f = factors.add(s, "Women's Day run-up", "2025-03-03", "2025-03-09", recurrence="yearly")
    effects.estimate(s, f.id, today=D("2026-06-01"))
    e = effects.summary(s, f)
    assert e["enough_history"] is False and e["expected_visits_index"] is None


def test_only_recurring_factors_get_an_effect(s):
    f = factors.add(s, "Outage", "2026-03-03")
    with pytest.raises(ValueError, match="yearly"):
        effects.estimate(s, f.id)


def test_belief_status_comes_from_the_linked_hypotheses(s):
    f = factors.add(s, "Price rise", "2026-03-02", expected_effects=[{"metric": "check", "direction": "up"}])
    assert factor_link.status(s, f.id) == "belief"
    h = Hypothesis(title="t", metric="check", kind="prepost", expected="up", factor_id=f.id, status="supported")
    s.add(h); s.flush()
    assert factor_link.status(s, f.id) == "supported"
    h.status = "rejected"
    s.flush()
    assert factor_link.status(s, f.id) == "refuted"


def test_testing_a_belief_makes_a_linked_hypothesis(s):
    shop(s)
    f = factors.add(s, "Price rise", "2026-03-09", expected_effects=[{"metric": "check", "direction": "up"}])
    h = factor_link.test_belief(s, f.id)
    assert h.factor_id == f.id and h.kind == "prepost" and h.metric == "check" and h.treatment == ["a", "b"]
    assert factor_link.status(s, f.id) in ("supported", "refuted", "inconclusive", "belief")
    with pytest.raises(ValueError, match="no expected effect"):
        factor_link.test_belief(s, factors.add(s, "Plain", "2026-03-01").id)


def test_the_holiday_seed_is_idempotent_and_recurs_every_year(s):
    from barberis_insights.context import holidays
    assert holidays.seed(s) == 9 and holidays.seed(s) == 0
    ny = next(f for f in factors.in_force(s, D("2024-12-20"), D("2025-01-02")) if f.title == "New Year")
    assert (ny.kind, ny.category, ny.recurrence, ny.treatment, ny.source) == ("external", "holiday", "yearly", "annotate", "research:holidays")
    assert factors.occurrences(ny, D("2023-12-20"), D("2024-01-03")) == [(D("2023-12-24"), D("2024-01-01"))]
    assert ny.expected_effects == []                                # no belief is put in the owner's mouth
    womens = next(f for f in factors.in_force(s, D("2023-03-01"), D("2023-03-10")) if "Women" in f.title)
    assert factors.occurrences(womens, D("2023-03-01"), D("2023-03-10")) == [(D("2023-03-05"), D("2023-03-08"))]
