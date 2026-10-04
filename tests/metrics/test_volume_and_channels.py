from metric_helpers import A, ctx, shop

from barberis_insights.metrics.channels.addon_share import addon_share
from barberis_insights.metrics.channels.online_share import online_share
from barberis_insights.metrics.volume.visits_per_week import visits_per_week


def test_visits_per_week_counts_weeks_worked(s):
    assert visits_per_week(ctx(shop(s)), A) == 2.0    # 4 visits over 2 ISO weeks with shifts


def test_online_share(s):
    assert online_share(ctx(shop(s)), A) == 25        # 1 of 4 visits


def test_addon_share(s):
    assert addon_share(ctx(shop(s)), A) == 25.0       # the massage visit
