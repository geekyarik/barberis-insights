"""Regression: the metrics engine must reproduce the 2026-09-27 baseline from the real (local) data.

Runs against var/insights.sqlite after `insights import-legacy`; skipped when that database is absent.
"""
import datetime as dt
import json
import subprocess
from pathlib import Path

import pytest

from barberis_insights.config import settings

pytestmark = pytest.mark.skipif(not (settings.data_dir / "insights.sqlite").exists(), reason="local data not imported")
LEGACY = Path(__file__).resolve().parents[1] / "legacy"
BASELINE = LEGACY / "baseline_snapshot.json"
SKILL_SNAPSHOT = settings.data_dir / "legacy-skill/scripts/snapshot.py"  # optional cross-check against the original script (private archive)


@pytest.fixture(scope="module")
def ds():
    from barberis_insights.db.session import session_scope
    from barberis_insights.metrics import Dataset
    with session_scope() as s:
        yield Dataset.load(s)


def test_reproduces_baseline(ds):
    from barberis_insights.metrics import compute_snapshot
    base = json.loads(BASELINE.read_text())["values"]
    snap = compute_snapshot(ds, dt.date(2026, 1, 12), dt.date(2026, 9, 27), (dt.date(2026, 1, 12), dt.date(2026, 6, 30)))["values"]
    diffs = [(k, m, v, snap[k].get(m)) for k in base for m, v in base[k].items() if snap[k].get(m) != v]
    assert sum(len(v) for v in base.values()) == 95
    assert diffs == []


@pytest.mark.skipif(not SKILL_SNAPSHOT.exists(), reason="refresh skill not installed")
def test_month_matches_skill_script(ds, tmp_path):
    from barberis_insights.metrics import compute_snapshot
    out = tmp_path / "skill.json"
    subprocess.run(["python3", str(SKILL_SNAPSHOT), "--from", "2026-08-31", "--to", "2026-09-27", "--out", str(out)], check=True, capture_output=True)
    skill = json.loads(out.read_text())["values"]
    mine = compute_snapshot(ds, dt.date(2026, 8, 31), dt.date(2026, 9, 27))["values"]
    diffs = [(k, m, v, mine[k].get(m)) for k in skill for m, v in skill[k].items() if mine[k].get(m) != v]
    assert diffs == []
