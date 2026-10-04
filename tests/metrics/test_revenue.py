from metric_helpers import A, TEAM, ctx, shop

from barberis_insights.metrics.revenue.average_check import average_check
from barberis_insights.metrics.revenue.revenue_per_hour import revenue_per_hour


def test_revenue_per_scheduled_hour(s):
    assert revenue_per_hour(ctx(shop(s)), A) == 250  # 3000 ₴ over 12 scheduled hours


def test_average_check_ignores_no_shows(s):
    assert average_check(ctx(shop(s)), A) == 750      # 3000 ₴ / 4 visits


def test_team_average_check_is_the_whole_shop(s):
    assert average_check(ctx(shop(s)), TEAM) == 750


def test_revenue_is_the_sum_of_visit_prices(s):
    from barberis_insights.metrics.revenue.revenue import revenue
    c = ctx(shop(s))
    assert revenue(c, A) == 3000 and revenue(c, TEAM) == 3000
