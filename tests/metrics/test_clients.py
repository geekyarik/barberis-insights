import datetime as dt

from conftest import visit
from metric_helpers import A, D, F, T, TEAM, ctx, shop

from barberis_insights.metrics.clients.new_to_shop import new_to_shop
from barberis_insights.metrics.clients.overdue_regulars import risk_n
from barberis_insights.metrics.clients.return_90d import return_90d


def test_new_to_shop_excludes_clients_seen_before(s):
    shop(s)
    visit(s, 3, "2025-06-01", 2)  # client 3 came to the shop before, to another barber
    assert new_to_shop(ctx(s), A) == 67               # clients 1, 2 new; 3 not


def test_new_to_shop_is_barber_only(s):
    assert new_to_shop(ctx(shop(s)), TEAM) is None


def test_return_90d_needs_five_clients(s):
    assert return_90d(ctx(shop(s), cohort=(F, T)), A) is None


def test_return_90d_share_within_ninety_days(s):
    shop(s)
    for c in (11, 12, 13, 14):
        visit(s, c, "2026-03-04", 1)
    visit(s, 11, "2026-04-01", 1)                      # comes back
    # cohort: clients 1, 2, 11, 12, 13, 14 (3 is new too: no earlier visit); 1 and 11 returned
    assert return_90d(ctx(s, cohort=(F, T)), A) == round(100 * 2 / 7)


def test_overdue_regular(s):
    for d in ("2026-01-05", "2026-01-12", "2026-01-19"):
        visit(s, 21, d, 1)                              # silent 56 days at 2026-03-16 (> 45)
    for d in ("2026-01-05", "2026-01-12", "2026-01-19", "2026-03-09"):
        visit(s, 22, d, 1)                              # came back, not overdue
    visit(s, 23, "2026-01-19", 1)                       # fewer than three visits: not a regular
    assert risk_n(ctx(s), A) == 1
    assert risk_n(ctx(s), TEAM) == 1


def test_overdue_stops_at_the_lapsed_limit(s):
    for d in ("2025-06-01", "2025-06-08", "2025-06-15"):
        visit(s, 31, d, 1)                              # silent ~274 days at 2026-03-16: Lapsed, not Overdue
    assert risk_n(ctx(s), A) == 0
