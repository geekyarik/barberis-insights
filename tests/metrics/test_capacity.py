from conftest import visit
from metric_helpers import A, ctx, shop

from barberis_insights.metrics.capacity.busy_share import busy_share
from barberis_insights.metrics.capacity.busy_share_by_weekday import _weekday_util


def test_busy_share_counts_no_shows_as_booked(s):
    # five bookings of 60 min inside 720 scheduled minutes
    assert busy_share(ctx(shop(s)), A) == 41.7


def test_busy_share_is_none_without_a_schedule(s):
    visit(s, 1, "2026-03-02", 1)
    assert busy_share(ctx(s), A) is None


def test_busy_share_by_weekday(s):
    c = ctx(shop(s))
    assert _weekday_util(0)(c, A) == 50.0   # Mondays 3/2 and 3/9: 240 booked of 480
    assert _weekday_util(1)(c, A) is None   # only one scheduled Tuesday
