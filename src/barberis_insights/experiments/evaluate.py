"""Hypothesis tests.

did      difference-in-differences on weekly values of a metric: treatment barbers vs control barbers,
         `pre_weeks` before vs `post_weeks` after the intervention date; bootstrap 95% CI over weeks.
prepost  same without a control group (treatment after − before).
offer_ab win-back rate by offer arm from outreach cases (two-proportion z-test).
"""
from __future__ import annotations

import datetime as dt
import math
import random
import statistics as st

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Barber, Hypothesis, OutreachCase, now
from ..metrics import Dataset, REGISTRY, Scope, WindowContext


def weekly_series(ds: Dataset, metric: str, barber_keys: list[str], start: dt.date, weeks: int) -> list[float | None]:
    """Mean of the metric across the given barbers for each ISO week (Monday start), skipping barbers with no value."""
    fn = REGISTRY[metric].fn
    ids = {b.key: b.altegio_id for b in ds.barbers}
    out = []
    for i in range(weeks):
        f = start + dt.timedelta(weeks=i); ctx = WindowContext(ds, f, f + dt.timedelta(days=6))
        vals = [v for k in barber_keys if k in ids and (v := fn(ctx, Scope(k, ids[k]))) is not None]
        out.append(st.mean(vals) if vals else None)
    return out


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else None


def _boot(diff_fn, groups: list[list[float]], n: int = 2000, seed: int = 7) -> tuple[float, float]:
    rng = random.Random(seed); res = []
    for _ in range(n):
        sample = [[rng.choice(g) for _ in g] for g in groups]
        v = diff_fn(*sample)
        if v is not None:
            res.append(v)
    res.sort()
    return res[int(0.025 * len(res))], res[int(0.975 * len(res)) - 1]


def evaluate_did(ds: Dataset, metric: str, treatment: list[str], control: list[str], intervention: dt.date, pre_weeks: int = 8,
                 post_weeks: int = 8) -> dict:
    monday = intervention - dt.timedelta(days=intervention.weekday())
    pre_start = monday - dt.timedelta(weeks=pre_weeks); post_start = monday + dt.timedelta(weeks=1)  # skip the change week itself
    clean = lambda xs: [x for x in xs if x is not None]
    T0 = clean(weekly_series(ds, metric, treatment, pre_start, pre_weeks)); T1 = clean(weekly_series(ds, metric, treatment, post_start, post_weeks))
    out = {"metric": metric, "treatment": treatment, "pre_window": [str(pre_start), str(monday - dt.timedelta(days=1))],
           "post_window": [str(post_start), str(post_start + dt.timedelta(weeks=post_weeks, days=-1))], "weeks": {"treatment_pre": len(T0), "treatment_post": len(T1)}}
    if len(T0) < 3 or len(T1) < 3:
        return out | {"verdict": "Not enough weeks of data to evaluate.", "msg": {"key": "not_enough_weeks"}}
    out["treatment_before"], out["treatment_after"] = round(st.mean(T0), 2), round(st.mean(T1), 2)
    if control:
        C0 = clean(weekly_series(ds, metric, control, pre_start, pre_weeks)); C1 = clean(weekly_series(ds, metric, control, post_start, post_weeks))
        if len(C0) < 3 or len(C1) < 3:
            return out | {"verdict": "Not enough control weeks to evaluate.", "msg": {"key": "not_enough_control"}}
        f = lambda a, b, c, d: (st.mean(b) - st.mean(a)) - (st.mean(d) - st.mean(c))
        effect = f(T0, T1, C0, C1); lo, hi = _boot(f, [T0, T1, C0, C1])
        out |= {"control": control, "control_before": round(st.mean(C0), 2), "control_after": round(st.mean(C1), 2), "weeks": out["weeks"] | {"control_pre": len(C0), "control_post": len(C1)}}
    else:
        f = lambda a, b: st.mean(b) - st.mean(a)
        effect = f(T0, T1); lo, hi = _boot(f, [T0, T1])
    out |= {"effect": round(effect, 2), "ci95": [round(lo, 2), round(hi, 2)]}
    unit = REGISTRY[metric].unit
    sig = lo > 0 or hi < 0
    out["significant"] = sig
    out["verdict"] = (f"{'Significant' if sig else 'No clear'} effect on {REGISTRY[metric].label.lower()}: {effect:+.2f}{unit if unit == '%' else ''} "
                      f"(95% CI {lo:+.2f} to {hi:+.2f}){' relative to the control group' if control else ''}.")
    # the same verdict as a catalog key + numbers, so the dashboard can show it in the viewer's language
    out["msg"] = {"key": "did_significant" if sig else "did_unclear", "control": bool(control),
                  "params": {"metric": metric, "effect": f"{effect:+.2f}{unit if unit == '%' else ''}", "lo": f"{lo:+.2f}", "hi": f"{hi:+.2f}"}}
    return out


def evaluate_offer_ab(s: Session) -> dict:
    rows = {}
    for c in s.scalars(select(OutreachCase).where(OutreachCase.offer_arm.is_not(None), OutreachCase.status.in_(("won_back", "not_returned")))):
        r = rows.setdefault(c.offer_arm, [0, 0]); r[1] += 1; r[0] += c.status == "won_back"
    arms = {k: {"won": w, "closed": n, "rate": round(w / n, 3)} for k, (w, n) in rows.items()}
    out = {"arms": arms}
    if len(arms) == 2:
        (a, (wa, na)), (b, (wb, nb)) = rows.items()
        if na >= 10 and nb >= 10:
            p = (wa + wb) / (na + nb); se = math.sqrt(p * (1 - p) * (1 / na + 1 / nb)) or 1e-9
            z = (wa / na - wb / nb) / se; pval = math.erfc(abs(z) / math.sqrt(2))
            out |= {"z": round(z, 2), "p_value": round(pval, 4), "significant": pval < 0.05,
                    "verdict": f"{a} {wa}/{na} vs {b} {wb}/{nb} won back; p = {pval:.3f}.",
                    "msg": {"key": "ab_result", "params": {"a": a, "wa": wa, "na": na, "b": b, "wb": wb, "nb": nb, "p": f"{pval:.3f}"}}}
        else:
            out["verdict"] = "Need at least 10 closed cases per arm."; out["msg"] = {"key": "ab_need_10"}
    else:
        out["verdict"] = "Needs exactly two offer arms with closed cases."; out["msg"] = {"key": "ab_need_two"}
    return out


def status_for(expected: str, res: dict) -> str:
    """expected: "up"/"down" = the change should move the metric that way; "none" = the change should NOT move it."""
    if "significant" not in res:
        return "inconclusive"
    sig = res["significant"]
    if expected == "none":
        return "rejected" if sig else "supported"
    if "effect" not in res:  # offer A/B: any significant difference supports "the offers differ"
        return "supported" if sig else "inconclusive"
    if not sig:
        return "inconclusive"
    return "supported" if (res["effect"] > 0) == (expected == "up") else "rejected"


def run(s: Session, h: Hypothesis) -> dict:
    if h.kind == "offer_ab":
        res = evaluate_offer_ab(s)
    else:
        res = evaluate_did(Dataset.load(s), h.metric, h.treatment, h.control if h.kind == "did" else [], h.intervention_date, h.pre_weeks, h.post_weeks)
    h.status = status_for(h.expected, res)
    h.result, h.evaluated = res, now()
    return res
