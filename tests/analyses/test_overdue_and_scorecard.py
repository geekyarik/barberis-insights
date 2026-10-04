from conftest import visit
from metric_helpers import D, F, T, shop

from barberis_insights.analyses import service
from barberis_insights.metrics import REGISTRY, Dataset, Scope, WindowContext, compute_snapshot


def test_overdue_regulars_lists_ids_value_and_days(s):
    for d in ("2026-01-05", "2026-01-12", "2026-01-19"):
        visit(s, 21, d, 1, cost=1000)                   # silent 56 days at 2026-03-16
    for d in ("2026-01-05", "2026-01-12", "2026-01-19", "2026-03-09"):
        visit(s, 22, d, 1)                              # came back
    r = service.run(s, "overdue_regulars", F, T)
    assert r.result["kpis"]["a"] == {"overdue": 1, "value_at_stake": 3000, "avg_days_silent": 56}
    row = r.result["tables"]["overdue"][0]
    assert (row["client_id"], row["shop_visits"], row["visits_to_barber"], row["days_silent"], row["median_gap_days"]) == (21, 3, 3, 56, 7.0)
    assert not {"name", "phone"} & set(row)


def test_overdue_stops_at_the_lapsed_limit(s):
    for d in ("2025-06-01", "2025-06-08", "2025-06-15"):
        visit(s, 31, d, 1)
    assert service.run(s, "overdue_regulars", F, T).result["kpis"]["team"]["overdue"] == 0


def test_overdue_team_total_matches_the_risk_n_metric(s):
    for c in (21, 23):
        for d in ("2026-01-05", "2026-01-12", "2026-01-19"):
            visit(s, c, d, 1)
    r = service.run(s, "overdue_regulars", F, T)
    s.flush()
    assert r.result["kpis"]["team"]["overdue"] == REGISTRY["risk_n"].fn(WindowContext(Dataset.load(s), F, T), Scope("team")) == 2


def test_scorecard_kpis_are_the_metric_snapshot(s):
    shop(s)
    r = service.run(s, "barber_scorecard", F, T)
    s.flush()
    assert r.result["kpis"] == compute_snapshot(Dataset.load(s), F, T)["values"]
    assert r.result["kpis"]["a"]["util"] == 41.7 and r.result["units"]["rph"] == "₴" and r.result["directions"]["risk_n"] == "down"


def test_scorecard_compares_with_last_year_without_history_metrics(s):
    shop(s)
    visit(s, 8, "2025-03-03", 1, 700)                   # same weekday, 52 weeks earlier
    visit(s, 9, "2025-03-10", 1, 500)
    r = service.run(s, "barber_scorecard", F, T)
    ly = r.result["last_year"]
    assert ly["window"] == ["2025-03-03", "2025-03-16"]
    assert "check" in ly["kpis"]["a"] and "new_share" not in ly["kpis"]["a"] and "risk_n" not in ly["kpis"]["a"]
    assert any(row["metric"] == "check" and row["last_year"] == 600 for row in r.result["tables"]["vs_last_year"])


def test_scorecard_has_no_last_year_when_there_is_no_data_then(s):
    assert service.run(shop(s), "barber_scorecard", F, T).result["last_year"] is None


def test_scorecard_flags_a_barber_far_below_the_team(s):
    from metric_helpers import slot
    shop(s)
    for day in ("2026-03-02", "2026-03-03", "2026-03-09"):
        slot(s, 2, day)                                 # barber b works as many hours as a but has no visits
    codes = {(f["code"], f["scope"]) for f in service.run(s, "barber_scorecard", F, T).result["findings"]}
    assert ("busy_share_below_team", "b") in codes


def test_two_comparable_runs_compare_end_to_end(s):
    shop(s)
    a = service.run(s, "overdue_regulars", D("2026-03-02"), D("2026-03-15"))
    b = service.run(s, "overdue_regulars", D("2026-03-09"), D("2026-03-22"))
    s.flush()
    out = service.compare(s, a.id, b.id)
    assert out["comparable"] and "team" in out["changes"]
    assert service.compare_with_previous(s, b.id)["before"] == a.id
    assert service.compare_with_previous(s, a.id)["comparable"] is False
