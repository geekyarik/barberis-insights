"""Factors: the owner's Context as data. A Factor is dated (day or week grain), scoped, may recur yearly, may carry a belief about
its effect, and says how analysis should treat it. Depends on nobody: a recurring factor's measured effect and a belief's verdict
are linked in by the modules that compute them (Analyses, Experiments)."""
from __future__ import annotations

import datetime as dt
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Factor, FactorEvent, Lens  # noqa: F401  (Factor is re-exported for callers)

KINDS = ("external", "internal")
TREATMENTS = ("annotate", "exclude", "adjust", "control", "suppress_overdue")
RECURRENCE = ("none", "yearly")
CATEGORIES = ("holiday", "mobilisation", "security", "competition", "calendar", "price", "staff", "schedule", "marketing", "operations", "event", "decision", "observation", "other")
FIELDS = ("title", "body", "kind", "category", "date_from", "date_to", "recurrence", "lead_days", "scopes", "expected_effects", "treatment",
          "adjust_factor", "tags", "active")


def _d(x):
    return dt.date.fromisoformat(x) if isinstance(x, str) and x else (x or None)


def _check(f: Factor) -> None:
    if f.kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if f.treatment not in TREATMENTS:
        raise ValueError(f"treatment must be one of {TREATMENTS}")
    if f.recurrence not in RECURRENCE:
        raise ValueError(f"recurrence must be one of {RECURRENCE}")
    if f.date_to and f.date_to < f.date_from:
        raise ValueError("date_to is before date_from")
    if f.lead_days < 0:
        raise ValueError("lead_days cannot be negative")
    if f.treatment == "adjust" and not (f.adjust_factor is not None and 0 <= f.adjust_factor <= 1):
        raise ValueError("an 'adjust' factor needs adjust_factor between 0 and 1 (the share of scheduled time that counts)")
    if f.treatment == "suppress_overdue" and not any(str(x).startswith("client:") for x in f.scopes):
        raise ValueError("'suppress_overdue' applies to one client: scope it as client:<id>")
    for e in f.expected_effects or []:
        if e.get("direction") not in ("up", "down"):
            raise ValueError("an expected effect needs a direction, up or down")


def _event(s: Session, f: Factor, kind: str, detail: dict | None = None) -> None:
    s.add(FactorEvent(factor_id=f.id, kind=kind, detail=detail))


def add(s: Session, title: str, date_from, date_to=None, kind: str = "internal", category: str = "other", body: str = "", scopes: list | None = None,
        treatment: str = "annotate", expected_effects: list | None = None, recurrence: str = "none", lead_days: int = 0, adjust_factor: float | None = None,
        tags: list | None = None, source: str = "owner") -> Factor:
    f = Factor(title=title.strip(), body=body, kind=kind, category=category, date_from=_d(date_from), date_to=_d(date_to), recurrence=recurrence,
               lead_days=lead_days, scopes=scopes or ["shop"], expected_effects=expected_effects or [], treatment=treatment, adjust_factor=adjust_factor,
               tags=tags or [], source=source, active=True)
    _check(f)
    s.add(f); s.flush()
    _event(s, f, "created", {"source": source})
    return f


def update(s: Session, factor_id: int, source: str = "owner", **changes) -> Factor:
    f = s.get(Factor, factor_id)
    if f is None:
        raise KeyError(f"unknown factor {factor_id}")
    before = {k: getattr(f, k) for k in changes if k in FIELDS}
    for k, v in changes.items():
        if k not in FIELDS:
            raise ValueError(f"cannot change {k!r}")
        setattr(f, k, _d(v) if k in ("date_from", "date_to") else v)
    _check(f)
    s.flush()
    _event(s, f, "updated", {"source": source, "changes": {k: [str(before[k]), str(getattr(f, k))] for k in before if str(before[k]) != str(getattr(f, k))}})
    return f


def delete(s: Session, factor_id: int, source: str = "owner") -> bool:
    f = s.get(Factor, factor_id)
    if f is None:
        return False
    _event(s, f, "deleted", {"source": source, "title": f.title})
    s.delete(f)
    return True


def link_effect(s: Session, factor_id: int, run_id: int) -> None:
    """Record the `seasonality` run that measured this factor's effect (called by the Analyses module)."""
    f = s.get(Factor, factor_id)
    f.effect_run_id = run_id
    _event(s, f, "effect_estimated", {"run": run_id})


def note_belief_tested(s: Session, factor_id: int, hypothesis_id: int) -> None:
    _event(s, s.get(Factor, factor_id), "belief_tested", {"hypothesis": hypothesis_id})


# ------------------------------------------------------------------ periods and scopes
def _shift(d: dt.date, years: int) -> dt.date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:                       # 29 February
        return d.replace(year=d.year + years, day=28)


def occurrences(f: Factor, start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    """The factor's periods (its run-up included) that overlap start..end. A yearly factor recurs in every year, before and after the
    one it was entered for."""
    base = (f.date_from - dt.timedelta(days=f.lead_days), f.date_to or f.date_from)
    if f.recurrence == "none":
        cands = [base]
    else:
        cands = [(_shift(base[0], y - f.date_from.year), _shift(base[1], y - f.date_from.year)) for y in range(start.year - 1, end.year + 2)]
    return [(a, b) for a, b in cands if a <= end and b >= start]


def applies_to(f: Factor, scope: str | None) -> bool:
    """Does the factor concern this scope? None = anything. A barber is touched by shop-wide and by their own factors."""
    scopes = set(f.scopes or ["shop"])
    if scope is None or scope in scopes:
        return True
    return bool(scopes & {"shop", "team"}) and not str(scope).startswith("client:")


def in_force(s: Session, start: dt.date, end: dt.date, scope: str | None = None) -> list[Factor]:
    """Active factors with an occurrence in start..end, oldest first."""
    rows = s.scalars(select(Factor).where(Factor.active.is_(True)).order_by(Factor.date_from, Factor.id))
    return [f for f in rows if applies_to(f, scope) and occurrences(f, start, end)]


def as_dict(f: Factor) -> dict:
    return {"id": f.id, "title": f.title, "body": f.body, "kind": f.kind, "category": f.category, "date_from": str(f.date_from),
            "date_to": str(f.date_to) if f.date_to else None, "recurrence": f.recurrence, "lead_days": f.lead_days, "scopes": f.scopes,
            "expected_effects": f.expected_effects, "treatment": f.treatment, "adjust_factor": f.adjust_factor, "tags": f.tags, "source": f.source,
            "active": f.active, "effect_run": f.effect_run_id}


# ------------------------------------------------------------------ lenses
BUILTIN_LENSES = {
    "raw": {"label": "Raw", "rule": {"honour": [], "categories": None, "ids": None}},
    "clean": {"label": "Clean weeks", "rule": {"honour": ["exclude", "adjust"], "categories": None, "ids": None}},
}


def lenses(s: Session) -> list[dict]:
    """The built-in lenses plus the saved ones (a saved lens of the same key replaces a built-in, except `raw`)."""
    out = {k: {"key": k, **v} for k, v in BUILTIN_LENSES.items()}
    for l in s.scalars(select(Lens).order_by(Lens.key)):
        if l.key != "raw":
            out[l.key] = {"key": l.key, "label": l.label, "rule": l.rule}
    return list(out.values())


def resolve(s: Session, lens: str, start: dt.date, end: dt.date) -> list[dict]:
    """The factors a lens applies in start..end, frozen as plain data: what a run stores, so that the same lens name resolving to
    different factors later is visible. `raw` honours nothing."""
    if lens == "raw":
        return []
    known = {l["key"]: l for l in lenses(s)}
    if lens not in known:
        raise ValueError(f"unknown lens {lens!r}; known: {', '.join(known)}")
    rule, out = known[lens]["rule"], []
    for f in s.scalars(select(Factor).where(Factor.active.is_(True)).order_by(Factor.id)):
        if f.treatment not in rule["honour"] or (rule.get("categories") and f.category not in rule["categories"]) or (rule.get("ids") and f.id not in rule["ids"]):
            continue
        if any(str(x).startswith("client:") for x in f.scopes):
            continue
        occ = occurrences(f, start, end)
        if occ:
            out.append({"factor_id": f.id, "version": f.updated.isoformat() if f.updated else "", "treatment": f.treatment, "scopes": f.scopes,
                        "adjust_factor": f.adjust_factor, "periods": [[str(a), str(b)] for a, b in occ]})
    return out


def create_lens(s: Session, key: str, label: str, honour: Iterable[str], categories: list | None = None, ids: list | None = None) -> Lens:
    if key == "raw" or not key.isidentifier():
        raise ValueError("a lens key is a plain word and cannot be 'raw'")
    bad = set(honour) - set(TREATMENTS)
    if bad:
        raise ValueError(f"unknown treatments {sorted(bad)}")
    row = s.get(Lens, key) or Lens(key=key)
    row.label, row.rule = label, {"honour": sorted(set(honour)), "categories": categories, "ids": ids}
    s.add(row); s.flush()
    return row
