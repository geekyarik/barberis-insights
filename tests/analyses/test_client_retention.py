from conftest import visit
from metric_helpers import D, F, T

from barberis_insights.analyses import service


def seed(s):
    """Barber a (id 1) sees clients 1-4 in the window 2026-03-02..2026-03-15. Client 4 is new to the shop."""
    for c in (1, 2, 3):
        visit(s, c, "2025-12-01", 1)                    # known clients
        visit(s, c, "2026-03-04", 1)                    # in the window
    visit(s, 4, "2026-03-05", 1)                        # new client
    visit(s, 1, "2026-04-10", 1)                        # 1 stays with a
    visit(s, 2, "2026-04-12", 2)                        # 2 goes to barber b
    visit(s, 4, "2026-04-20", 1)                        # 4 stays
    visit(s, 9, "2026-07-01", 2)                        # the data reaches past the 90-day follow-up (2026-06-13)
    s.flush()


def test_stayed_switched_and_lost(s):
    seed(s)
    r = service.run(s, "client_retention", F, T)
    a = r.result["kpis"]["a"]
    assert r.result["complete"] is True
    assert (a["clients"], a["stayed_pct"], a["switched_pct"], a["lost_pct"]) == (4, 50.0, 25.0, 25.0)
    assert (a["new_clients"], a["new_stayed_pct"], a["returning_clients"], a["returning_stayed_pct"]) == (1, 100.0, 3, 33.3)
    assert r.result["kpis"]["team"]["shop_retained_pct"] == 75.0     # client 3 never came back anywhere


def test_lost_clients_are_listed_by_id_only(s):
    seed(s)
    rows = service.run(s, "client_retention", F, T).result["tables"]["lost_clients"]
    assert rows == [{"scope": "a", "client_id": 3, "shop_visits": 2, "last_visit": "2026-03-04"}]


def test_a_window_whose_follow_up_has_not_happened_is_incomplete(s):
    seed(s)
    r = service.run(s, "client_retention", F, T, params={"lookahead_days": 400})
    assert r.result["complete"] is False
    assert any(f["code"] == "window_incomplete" for f in r.result["findings"])


def test_scope_to_one_barber_keeps_that_barber_and_the_team(s):
    seed(s)
    r = service.run(s, "client_retention", F, T, scope="a")
    assert set(r.result["kpis"]) == {"a", "team"}


def test_former_barbers_are_never_reported(s):
    from barberis_insights.db.models import Barber
    s.add(Barber(altegio_id=3, key="gone", name="Gone", tier="", active=False))
    seed(s)
    visit(s, 1, "2026-03-04", 3)
    assert "gone" not in service.run(s, "client_retention", F, T).result["kpis"]
