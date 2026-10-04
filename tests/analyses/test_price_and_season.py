import datetime as dt

from conftest import visit
from metric_helpers import D, slot

from barberis_insights.analyses import service
from barberis_insights.analyses.price_demand import changes, weekly_price
from barberis_insights.db.models import Barber

MON = D("2026-01-05")


def haircut_weeks(s, barber, first_week, n_weeks, price, per_week, days=4):
    """n_weeks of plain haircuts, `per_week` visits on `days` worked days a week."""
    for w in range(n_weeks):
        monday = MON + dt.timedelta(weeks=first_week + w)
        for d in range(days):
            slot(s, barber, str(monday + dt.timedelta(days=d)))
        for k in range(per_week):
            visit(s, 1000 * barber + 100 * (first_week + w) + k, monday + dt.timedelta(days=k % days), barber, price, titles=("Чоловіча стрижка",))


def test_a_price_change_needs_three_weeks_at_the_new_price(s):
    prices = {MON + dt.timedelta(weeks=i): p for i, p in enumerate([800, 800, 900, 800, 800, 900, 900, 900, 900])}
    assert changes(prices) == [(MON + dt.timedelta(weeks=5), 800, 900)]       # the one-week blip is ignored


def test_weekly_price_is_the_modal_price_of_plain_haircuts(s):
    visit(s, 1, "2026-01-05", 1, 800, titles=("Чоловіча стрижка",)); visit(s, 2, "2026-01-06", 1, 800, titles=("Чоловіча стрижка",))
    visit(s, 3, "2026-01-07", 1, 900, titles=("Чоловіча стрижка",)); visit(s, 4, "2026-01-08", 1, 5000, titles=("Чоловіча стрижка", "Масаж"))
    s.flush()
    from barberis_insights.metrics import Dataset
    assert weekly_price(Dataset.load(s).arrived) == {MON: 800}


def test_demand_after_a_price_rise_is_set_against_the_other_barbers(s):
    haircut_weeks(s, 1, 0, 8, 800, 4); haircut_weeks(s, 1, 8, 8, 900, 3)     # a: 4 visits a week, then 3 after the rise
    haircut_weeks(s, 2, 0, 16, 800, 4)                                        # b: unchanged
    s.add(Barber(altegio_id=3, key="gone", name="Gone", active=False))
    visit(s, 777, "2026-04-26", 3, 800)                                       # a barber who left: the data now reaches the end of the 8 weeks
    s.flush()
    r = service.run(s, "price_demand", D("2026-02-23"), D("2026-03-15"))
    row = r.result["tables"]["price_changes"][0]
    assert (row["scope"], row["change_week"], row["old_price"], row["new_price"], row["price_change_pct"]) == ("a", "2026-03-02", 800, 900, 12.5)
    assert (row["visits_per_day_before"], row["visits_per_day_after"], row["demand_change_pct"], row["others_demand_change_pct"], row["net_demand_change_pct"]) == (1.0, 0.75, -25.0, 0.0, -25.0)
    assert row["observed"] is True and r.result["complete"] is True
    assert ("demand_fell_after_price_rise", "a") in {(f["code"], f["scope"]) for f in r.result["findings"]}
    assert r.result["kpis"]["a"]["avg_net_demand_change_pct"] == -25.0


def test_a_change_whose_eight_weeks_have_not_happened_is_not_judged(s):
    haircut_weeks(s, 1, 0, 8, 800, 4); haircut_weeks(s, 1, 8, 4, 900, 4)
    r = service.run(s, "price_demand", D("2026-02-23"), D("2026-03-15"))
    assert r.result["tables"]["price_changes"][0]["net_demand_change_pct"] is None and r.result["complete"] is False


def season_year(s, year, extra_week=10, base=3, peak=6, last_week=52):
    for w in range(1, last_week + 1):
        n = peak if w == extra_week else base
        for k in range(n):
            visit(s, w * 100 + k + year * 100000, dt.date.fromisocalendar(year, w, 1), 1, 800)


def test_seasonality_indexes_weeks_against_their_own_year(s):
    season_year(s, 2024); season_year(s, 2025)
    season_year(s, 2026, last_week=10)
    visit(s, 888, "2026-03-08", 1, 800)                  # the data reaches the end of week 10, so it counts as a full week
    s.flush()
    r = service.run(s, "seasonality", D("2026-03-02"), D("2026-03-15"))
    k = r.result["kpis"]["team"]
    assert k["years_observed"] == 2 and k["expected_visits_index"] == 1.47 and k["expected_revenue_index"] == 1.47
    assert ("season_high", "team") in {(f["code"], f["scope"]) for f in r.result["findings"]}
    assert {x["year"] for x in r.result["tables"]["weeks"] if x["iso_week"] == 10} == {2024, 2025, 2026}


def test_seasonality_says_so_when_there_is_not_enough_history(s):
    season_year(s, 2025)
    r = service.run(s, "seasonality", D("2026-03-02"), D("2026-03-15"))
    assert ("not_enough_history", "team") in {(f["code"], f["scope"]) for f in r.result["findings"]} and r.result["kpis"]["team"]["years_observed"] == 1
