"""Linking Factors to Hypotheses: "test this belief", and a Factor's belief status read from its hypotheses."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..context import factors
from ..db.models import Factor, Hypothesis
from ..metrics import Dataset
from . import evaluate

STATUS = {"supported": "supported", "rejected": "refuted", "inconclusive": "inconclusive", "open": "belief"}


def status(s: Session, factor_id: int) -> str:
    """belief until a linked hypothesis has a verdict; then that verdict (the latest evaluated one decides). Never stored on the Factor."""
    hs = list(s.scalars(select(Hypothesis).where(Hypothesis.factor_id == factor_id).order_by(Hypothesis.evaluated.desc().nullslast(), Hypothesis.id.desc())))
    evaluated = [h for h in hs if h.status != "open"]
    return STATUS[evaluated[0].status] if evaluated else "belief"


def test_belief(s: Session, factor_id: int, intervention: dt.date | None = None) -> Hypothesis:
    """Turn a Factor's first expected effect into a before/after Hypothesis over the current barbers and evaluate it."""
    f = s.get(Factor, factor_id)
    if f is None:
        raise KeyError(f"unknown factor {factor_id}")
    if not f.expected_effects:
        raise ValueError("the factor has no expected effect to test")
    e = f.expected_effects[0]
    ds = Dataset.load(s)
    h = Hypothesis(title=f"Belief: {f.title}", statement=f.body, metric=e["metric"], kind="prepost", treatment=[b.key for b in ds.barbers], control=[],
                   intervention_date=intervention or f.date_from, expected=e["direction"], factor_id=f.id)
    s.add(h); s.flush()
    evaluate.run(s, h)
    factors.note_belief_tested(s, f.id, h.id)
    return h
