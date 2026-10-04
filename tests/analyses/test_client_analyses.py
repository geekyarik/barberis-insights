import datetime as dt

import pytest
from conftest import visit
from metric_helpers import D, F, T

from barberis_insights.analyses import service
from barberis_insights.db.models import Barber


def run(s, key, **kw):
    s.flush()
    return service.run(s, key, kw.pop("f", F), kw.pop("t", T), **kw)


def test_new_clients_are_credited_to_the_first_barber(s):
    s.add(Barber(altegio_id=3, key="gone", name="Gone", active=False)); s.flush()
    visit(s, 1, "2026-03-04", 1); visit(s, 2, "2026-03-05", 1)
    visit(s, 3, "2025-12-01", 1); visit(s, 3, "2026-03-06", 1)          # a returning client
    visit(s, 4, "2026-03-10", 2)
    visit(s, 5, "2026-03-07", 3)                                         # new, but to a barber who has left
    k = run(s, "new_clients").result["kpis"]
    assert k["a"] == {"new_clients": 2, "new_per_day": 0.14, "clients": 3, "new_share_pct": 66.7}
    assert k["b"]["new_clients"] == 1 and k["team"]["new_clients"] == 3 and k["team"]["shop_new_clients"] == 4


def test_new_clients_months_table_is_shop_wide(s):
    visit(s, 1, "2026-03-04", 1); visit(s, 2, "2026-03-20", 1)
    assert run(s, "new_clients", t=D("2026-03-29")).result["tables"]["months"] == [{"month": "2026-03", "new_clients": 2}]


def test_a_window_near_the_start_of_history_is_flagged(s):
    visit(s, 1, "2022-01-05", 1)
    r = run(s, "new_clients", f=D("2022-01-03"), t=D("2022-01-16"))
    assert any(f["code"] == "history_too_short" for f in r.result["findings"])


def test_client_sources(s):
    visit(s, 1, "2026-01-05", 1); visit(s, 1, "2026-03-04", 1)          # returning to a
    visit(s, 2, "2026-01-05", 2); visit(s, 2, "2026-03-04", 1)          # from barber b
    visit(s, 3, "2026-03-04", 1)                                         # new
    a = run(s, "client_sources").result["kpis"]["a"]
    assert (a["clients"], a["returning_pct"], a["from_other_pct"], a["new_pct"]) == (3, 33.3, 33.3, 33.3)


def cohort_data(s):
    for c in (1, 2, 3, 4):
        visit(s, c, "2026-03-03", 1)
    visit(s, 1, "2026-03-20", 1)           # day 17, same barber
    visit(s, 2, "2026-04-10", 2)           # day 38, another barber
    visit(s, 3, "2026-05-20", 1)           # day 78, same barber
    visit(s, 99, "2026-07-01", 2)          # the data now reaches past every 90-day horizon


def test_return_cohorts_by_horizon(s):
    cohort_data(s)
    r = run(s, "return_cohorts")
    k = r.result["kpis"]["a"]
    assert (k["new_clients"], k["back_30_pct"], k["back_60_pct"], k["back_90_pct"], k["same_barber_90_pct"]) == (4, 25.0, 50.0, 75.0, 50.0)
    assert r.result["complete"] is True and r.result["tables"]["cohorts"][0]["month"] == "2026-03"


def test_return_cohorts_are_incomplete_until_observed(s):
    for c in (1, 2):
        visit(s, c, "2026-03-03", 1)
    visit(s, 1, "2026-03-20", 1)
    r = run(s, "return_cohorts")
    assert r.result["complete"] is False and r.result["kpis"]["a"]["back_90_pct"] is None      # nobody has been observed for 90 days yet


def test_exclusive_regulars_and_their_revenue(s):
    for d in ("2025-12-01", "2026-01-10", "2026-02-01", "2026-02-20"):
        visit(s, 21, d, 1)                                               # exclusive regular
    for d in ("2026-01-10", "2026-02-01", "2026-02-20"):
        visit(s, 22, d, 1)
    visit(s, 22, "2026-02-25", 2)                                        # also sees barber b: not exclusive
    visit(s, 23, "2026-02-01", 1); visit(s, 23, "2026-02-20", 1)         # only two visits: not a regular
    for d in ("2025-04-01", "2025-04-08", "2025-04-15"):
        visit(s, 24, d, 1)                                               # lapsed regular: no visit in the last 180 days
    r = run(s, "exclusive_clients")
    assert r.result["kpis"]["a"] == {"regulars": 2, "exclusive_regulars": 1, "exclusive_pct": 50.0, "exclusive_revenue": 3200, "revenue_share_pct": 33.3}
    assert [x["client_id"] for x in r.result["tables"]["exclusive"]] == [21]


def test_departure_impact_stayed_lost_and_with_whom(s):
    s.add(Barber(altegio_id=3, key="gone", name="Gone", active=False, left=D("2026-02-01"))); s.flush()
    for c in (31, 32, 33):
        for d in ("2025-10-01", "2025-11-01", "2025-12-01"):
            visit(s, c, d, 3)
    visit(s, 31, "2026-03-04", 1)                                        # moved to barber a
    visit(s, 32, "2026-03-05", 2)                                        # moved to barber b
    visit(s, 99, "2026-03-15", 1)                                        # the data reaches the end of the observation window
    r = run(s, "departure_impact", params={"barber": "gone"})
    assert r.result["kpis"]["team"] == {"regulars": 3, "stayed_pct": 66.7, "lost_pct": 33.3}
    assert {(x["receiving_barber"], x["clients"], x["current"]) for x in r.result["tables"]["receiving"]} == {("A", 1, True), ("B", 1, True)}
    assert r.result["complete"] is True and r.result["context"]["left"] == "2026-02-01"


def test_departure_impact_needs_a_barber_who_left(s):
    with pytest.raises(ValueError, match="has left"):
        run(s, "departure_impact", params={"barber": "a"})
    with pytest.raises(ValueError, match="has left"):
        run(s, "departure_impact")


def test_departure_window_before_the_departure_is_incomplete(s):
    s.add(Barber(altegio_id=3, key="gone", name="Gone", active=False, left=D("2026-03-20"))); s.flush()
    visit(s, 1, "2026-03-04", 1)
    assert run(s, "departure_impact", params={"barber": "gone"}).result["complete"] is False
