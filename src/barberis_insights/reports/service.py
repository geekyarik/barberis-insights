"""The Reports service. A report is composed from analysis runs and goal states, then frozen as a `report_run`."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analyses import service as analyses
from ..db.models import ReportRun
from ..goals import service as goals
from ..ingest.status import data_status

KEY = ("revenue", "visits", "util", "rph", "check")


def weekly_review(s: Session, f: dt.date, t: dt.date, created_by: str = "schedule") -> ReportRun:
    """Last week against the week before and the same week last year, overdue regulars, and the goals."""
    week = analyses.run(s, "barber_scorecard", f, t, created_by=created_by)
    prev = analyses.run(s, "barber_scorecard", f - dt.timedelta(days=7), t - dt.timedelta(days=7), created_by=created_by)
    overdue = analyses.run(s, "overdue_regulars", f, t, created_by=created_by)
    cmp = analyses.compare(s, prev.id, week.id)

    kpis = week.result["kpis"]
    pick = lambda scope: {k: kpis.get(scope, {}).get(k) for k in KEY}
    vs_prev = {sc: {k: {"delta": v["delta"], "verdict": v["verdict"]} for k, v in ch.items() if k in KEY} for sc, ch in cmp["changes"].items()} if cmp["comparable"] else None
    vs_year = {r["metric"]: r["delta"] for r in week.result["tables"]["vs_last_year"] if r["scope"] == "team" and r["metric"] in KEY}

    board = goals.board(s)
    counts: dict[str, int] = {}
    for g in board:
        counts[g["label_key"].rsplit(".", 1)[1]] = counts.get(g["label_key"].rsplit(".", 1)[1], 0) + 1
    top = sorted(overdue.result["tables"]["overdue"], key=lambda r: -r["priority"])[:5]
    ov = overdue.result["kpis"]["team"]
    iso = f.isocalendar()
    content = {
        "week": f"{iso[0]}-W{iso[1]:02d}", "window": [str(f), str(t)], "data_as_of": str(data_status(s)["last_visit"]),
        "names": week.result["context"]["names"],
        "team": pick("team"), "barbers": {k: pick(k) for k in kpis if k != "team"},
        "vs_prev": vs_prev, "vs_year": vs_year,
        "overdue": {"count": ov["overdue"], "value": ov["value_at_stake"],
                    "top": [{"client_id": r["client_id"], "barber": r["scope"], "days_silent": r["days_silent"], "lifetime_spend": r["lifetime_spend"]} for r in top]},
        "goals": {"counts": counts, "behind": [{"id": g["id"], "scope": g["scope"], "title": g["title"]} for g in board if g["label_key"] == "goal.state.behind"]},
    }
    row = ReportRun(report_key="weekly_review", window_from=f, window_to=t, lens="raw", analysis_run_ids=[week.id, prev.id, overdue.id],
                    created_by=created_by, content=content)
    s.add(row)
    s.flush()
    return row


def get(s: Session, report_id: int) -> ReportRun | None:
    return s.get(ReportRun, report_id)


def list_reports(s: Session, key: str | None = None, limit: int = 20) -> list[ReportRun]:
    q = select(ReportRun).order_by(ReportRun.window_to.desc(), ReportRun.id.desc()).limit(limit)
    if key:
        q = q.where(ReportRun.report_key == key)
    return list(s.scalars(q))


# ------------------------------------------------------------------ barber book and team comparison
FOLLOW_UP_DAYS = 90


def followup_window(s: Session, f: dt.date, t: dt.date) -> tuple[dt.date, dt.date]:
    """The latest window of the same length whose 90-day follow-up has fully happened (for retention and return cohorts)."""
    last = data_status(s)["last_visit"] or t
    late = (t + dt.timedelta(days=FOLLOW_UP_DAYS) - last).days
    shift = dt.timedelta(weeks=-(-late // 7)) if late > 0 else dt.timedelta(0)
    return f - shift, t - shift


def _rows(run, scope: str) -> dict:
    return {name: [r for r in rows if r.get("scope", scope) in (scope, None)] for name, rows in run.result["tables"].items()}


def _part(run, scope: str) -> dict:
    return {"run": run.id, "window": [str(run.window_from), str(run.window_to)], "complete": run.result.get("complete", True),
            "kpis": run.result["kpis"].get(scope, {}), "team": run.result["kpis"].get("team", {}), "tables": _rows(run, scope)}


def _findings(runs: dict, scopes: tuple[str, ...]) -> list[dict]:
    return [f | {"analysis": key} for key, r in runs.items() for f in r.result["findings"] if f["scope"] in scopes]


def _goals(s: Session, scope: str) -> list[dict]:
    keep = ("id", "title", "metric", "baseline", "target", "current", "progress", "label_key", "state", "due")
    return [{k: g[k] for k in keep} for g in goals.board(s, scope)]


def barber_book(s: Session, key: str, f: dt.date, t: dt.date, created_by: str = "dashboard") -> ReportRun:
    """One barber over a window: scorecard against the team and last year, week by week, weekdays and hours, retention, cohorts,
    sources, exclusivity, overdue regulars and services, plus their goals."""
    rf, rt = followup_window(s, f, t)
    spec = {"scorecard": ("barber_scorecard", f, t), "weekly": ("weekly_book", f, t), "weekday": ("weekday_pattern", f, t),
            "retention": ("client_retention", rf, rt), "cohorts": ("return_cohorts", rf, rt), "sources": ("client_sources", f, t),
            "exclusive": ("exclusive_clients", f, t), "overdue": ("overdue_regulars", f, t), "services": ("service_mix", f, t)}
    runs = {name: analyses.run(s, a, wf, wt, scope=key, created_by=created_by) for name, (a, wf, wt) in spec.items()}
    names = runs["scorecard"].result["context"]["names"]
    content = {"kind": "barber_book", "barber": key, "name": names[key], "window": [str(f), str(t)], "followup_window": [str(rf), str(rt)],
               "data_as_of": str(data_status(s)["last_visit"]), "names": names, "sections": {n: _part(r, key) for n, r in runs.items()},
               "last_year": runs["scorecard"].result["last_year"], "directions": runs["scorecard"].result["directions"],
               "findings": _findings({spec[n][0]: r for n, r in runs.items()}, (key,)), "goals": _goals(s, key)}
    row = ReportRun(report_key="barber_book", window_from=f, window_to=t, lens="raw", analysis_run_ids=[r.id for r in runs.values()],
                    created_by=created_by, content=content)
    s.add(row); s.flush()
    return row


def team_comparison(s: Session, f: dt.date, t: dt.date, created_by: str = "dashboard") -> ReportRun:
    """All current barbers side by side over a window, with the team's goals."""
    rf, rt = followup_window(s, f, t)
    spec = {"scorecard": ("barber_scorecard", f, t), "weekday": ("weekday_pattern", f, t), "retention": ("client_retention", rf, rt),
            "sources": ("client_sources", f, t), "exclusive": ("exclusive_clients", f, t), "overdue": ("overdue_regulars", f, t)}
    runs = {name: analyses.run(s, a, wf, wt, created_by=created_by) for name, (a, wf, wt) in spec.items()}
    names = runs["scorecard"].result["context"]["names"]
    content = {"kind": "team_comparison", "window": [str(f), str(t)], "followup_window": [str(rf), str(rt)], "data_as_of": str(data_status(s)["last_visit"]),
               "names": names, "directions": runs["scorecard"].result["directions"],
               "sections": {n: {"run": r.id, "window": [str(r.window_from), str(r.window_to)], "complete": r.result.get("complete", True), "kpis": r.result["kpis"]}
                            for n, r in runs.items()},
               "last_year": runs["scorecard"].result["last_year"],
               "findings": _findings({spec[n][0]: r for n, r in runs.items()}, tuple(runs["scorecard"].result["kpis"])), "goals": _goals(s, "team")}
    row = ReportRun(report_key="team_comparison", window_from=f, window_to=t, lens="raw", analysis_run_ids=[r.id for r in runs.values()],
                    created_by=created_by, content=content)
    s.add(row); s.flush()
    return row
