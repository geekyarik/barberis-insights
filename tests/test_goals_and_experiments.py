import datetime as dt

from conftest import visit

from barberis_insights.db.models import Measurement, OutreachCase, ScheduleSlot
from barberis_insights.experiments.evaluate import evaluate_did, evaluate_offer_ab, status_for
from barberis_insights.goals import service as goals
from barberis_insights.metrics import REGISTRY, Dataset

D = dt.date.fromisoformat


def meas(s, asof, scope, metric, value):
    s.add(Measurement(asof=D(asof), window_from=D(asof), window_to=D(asof), scope=scope, metric=metric, metric_version=REGISTRY[metric].version, value=value))


def test_goal_states(s):
    meas(s, "2026-09-27", "a", "util", 60); meas(s, "2026-09-27", "a", "risk_n", 70)
    up = goals.upsert(s, {"scope": "a", "title": "Fill shifts", "metric": "util", "target": 70, "due": "2026-12-31"})
    down = goals.upsert(s, {"scope": "a", "title": "Fewer overdue", "metric": "risk_n", "baseline": 70, "target": 50, "due": "2026-12-31"})
    assert up.baseline == 60  # empty baseline takes the latest measured value
    assert goals.assess(s, up)["label"] == "Waiting for first measurement"
    meas(s, "2026-10-25", "a", "util", 61); meas(s, "2026-10-25", "a", "risk_n", 60); s.flush()
    a, b = goals.assess(s, up), goals.assess(s, down)
    assert a["state"] == "behind" and a["progress"] == 0.1       # 10% of the way, 30% of the time gone
    assert b["state"] == "ok" and b["progress"] == 0.5            # lower is better: 70 → 60 of 70 → 50
    meas(s, "2026-11-29", "a", "util", 72); s.flush()
    assert goals.assess(s, up)["label"] == "Target reached"
    goals.upsert(s, {"status": "dropped"}, up.id)
    assert goals.assess(s, up)["state"] == "dropped"
    assert goals.delete(s, down.id) and goals.board(s) == [goals.assess(s, up)]


def _week_of_visits(s, barber, monday, per_day, days=4):
    for d in range(days):
        day = monday + dt.timedelta(days=d)
        s.add(ScheduleSlot(barber_id=barber, date=day, start_min=600, end_min=1200))
        for k in range(per_day):
            visit(s, 1000 + barber * 100000 + day.toordinal() * 10 + k, day, barber=barber, start=f"{10 + k:02d}:00")


def test_did_recovers_known_effect(s):
    start = D("2026-01-05")  # Monday
    for w in range(16):
        monday = start + dt.timedelta(weeks=w)
        post = w >= 8
        _week_of_visits(s, 1, monday, 6 + (2 if post else 0))   # treatment: +2/day after week 8 → +8 visits/week
        _week_of_visits(s, 2, monday, 5 + (1 if post else 0))   # control: +1/day (shop-wide trend)
    s.flush()
    ds = Dataset.load(s)
    res = evaluate_did(ds, "visits_wk", ["a"], ["b"], start + dt.timedelta(weeks=8), pre_weeks=7, post_weeks=7)
    assert res["effect"] == 4.0 and res["significant"]            # (32−24) − (24−20) visits per week
    assert status_for("up", res) == "supported" and status_for("none", res) == "rejected"


def test_offer_ab(s):
    for i in range(40):
        arm = "pct10" if i % 2 else "call_only"
        won = (arm == "pct10" and i % 4 != 3) or (arm == "call_only" and i % 8 == 0)
        s.add(OutreachCase(client_id=i, offer_arm=arm, status="won_back" if won else "not_returned"))
    s.flush()
    r = evaluate_offer_ab(s)
    assert r["arms"]["pct10"]["rate"] == 0.5 and r["arms"]["call_only"]["rate"] == 0.25
    assert "p_value" in r


def test_goal_on_an_older_metric_definition_is_flagged_not_compared(s):
    meas(s, "2026-09-27", "a", "risk_n", 70)
    g = goals.upsert(s, {"scope": "a", "title": "Fewer overdue", "metric": "risk_n", "baseline": 70, "target": 50, "due": "2026-12-31"})
    g.metric_version = 1                               # set before the definition changed
    s.flush()
    out = goals.assess(s, g)
    assert out["label_key"] == "goal.state.redefined" and out["current"] is None   # v2 measurements are not compared with a v1 baseline
