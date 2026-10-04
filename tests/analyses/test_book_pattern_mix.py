from conftest import visit
from metric_helpers import F, T, shop, slot

from barberis_insights.analyses import service


def test_weekly_book_totals_and_last_year(s):
    shop(s)
    visit(s, 8, "2025-03-04", 1, 1500)                  # the same ISO week (W10) a year earlier
    r = service.run(s, "weekly_book", F, T)
    a = r.result["kpis"]["a"]
    assert (a["revenue"], a["visits"], a["util"], a["revenue_vs_ly_pct"], a["no_show_pct"]) == (3000, 4, 41.7, 100.0, 20.0)
    rows = [x for x in r.result["tables"]["weeks"] if x["scope"] == "a"]
    assert [x["week"] for x in rows] == ["W10", "W11"] and rows[0]["revenue_ly"] == 1500 and rows[1]["revenue_ly"] == 0


def test_weekly_book_types_clients_from_all_history(s):
    shop(s)
    visit(s, 3, "2022-06-01", 2)                        # client 3 came to barber b long before the metric history window
    rows = [x for x in service.run(s, "weekly_book", F, T).result["tables"]["weeks"] if x["scope"] == "a" and x["week"] == "W11"]
    assert rows[0]["clients"] == 1 and rows[0]["from_other"] == 1 and rows[0]["new_to_shop"] == 0


def test_weekly_book_team_is_the_tracked_barbers_together(s):
    shop(s)
    visit(s, 9, "2026-03-04", 2, 400)
    r = service.run(s, "weekly_book", F, T)
    assert r.result["kpis"]["team"]["revenue"] == 3400 and r.result["kpis"]["b"]["revenue"] == 400


def test_weekly_book_flags_a_big_drop_on_last_year(s):
    shop(s)
    visit(s, 8, "2025-03-04", 1, 9000)
    codes = {(f["code"], f["scope"]) for f in service.run(s, "weekly_book", F, T).result["findings"]}
    assert ("revenue_below_last_year", "a") in codes
    assert ("no_shows_high", "a") not in codes           # 1 no-show in 4 visits is too small a sample to judge


def test_weekday_pattern_by_weekday_and_hour(s):
    shop(s)
    r = service.run(s, "weekday_pattern", F, T)
    assert r.result["kpis"]["a"]["util_mon"] == 50.0 and "util_tue" not in r.result["kpis"]["a"]   # one Tuesday: not judged
    hours = {x["hour"]: x for x in r.result["tables"]["hour"] if x["scope"] == "a"}
    assert (hours[10]["util"], hours[11]["util"], hours[12]["util"]) == (100.0, 66.7, 0.0)
    mon = [x for x in r.result["tables"]["weekday"] if x["scope"] == "a" and x["weekday"] == 0][0]
    assert (mon["days_worked"], mon["sched_h"], mon["busy_h"], mon["visits"], mon["revenue"]) == (2, 8.0, 4.0, 3, 2100)


def test_an_empty_weekday_is_flagged(s):
    shop(s)
    for day in ("2026-03-04", "2026-03-11"):
        slot(s, 2, day)                                  # barber b is scheduled on two Wednesdays and nobody books
    codes = {(f["code"], f["scope"], f["evidence"]["weekday"]) for f in service.run(s, "weekday_pattern", F, T).result["findings"]}
    assert ("weekday_empty", "b", "wed") in codes


def test_service_mix_shares_and_addons(s):
    shop(s)
    r = service.run(s, "service_mix", F, T)
    a = r.result["kpis"]["a"]
    assert (a["revenue"], a["addon_revenue_pct"], a["services_per_visit"]) == (3600, 16.7, 1.25)
    rows = {x["service"]: x for x in r.result["tables"]["services"] if x["scope"] == "a"}
    assert rows["Чоловіча стрижка"]["visits"] == 4 and rows["Масаж"]["addon"] is True and rows["Масаж"]["share_pct"] == 16.7
