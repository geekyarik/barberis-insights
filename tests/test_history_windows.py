"""The full client history (profiles, win-back) and the Goal metrics' history are separate windows."""
import datetime as dt

import pytest

from barberis_insights.config import settings

pytestmark = pytest.mark.skipif(not (settings.data_dir / "insights.sqlite").exists(), reason="local data not imported")


@pytest.fixture(scope="module")
def ds():
    from barberis_insights.db.session import session_scope
    from barberis_insights.metrics import Dataset
    with session_scope() as s:
        yield Dataset.load(s)


def test_full_history_reaches_back_further_than_metrics_history(ds):
    first_full = min(a.date for vs in ds.shop_history.values() for a in vs)
    first_metrics = min(a.date for vs in ds.metrics_history.values() for a in vs)
    assert first_full >= dt.date.fromisoformat(settings.history_start)
    assert first_metrics >= dt.date.fromisoformat(settings.metrics_history_start)
    assert first_full <= first_metrics


def test_tracked_barbers_are_the_active_ones_only(ds):
    assert ds.barbers and all(b.active for b in ds.barbers)
