"""The weekly message's figures. Built from the data when it is sent; there is no stored "report"."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analyses import service as analyses
from ..clients.contact import active_flags
from ..db.models import Client
from ..goals import service as goals
from ..ingest.status import data_status

KEY = ("revenue", "visits", "util", "rph", "check")


def weekly_content(s: Session, f: dt.date, t: dt.date, created_by: str = "schedule") -> dict:
    """The figures of one whole ISO week, computed from the data as it is now: against the week before and the same week last year, overdue regulars, and the goals. Nothing is stored except the analysis runs it is built from."""
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
    skip = set(active_flags(s, None)) | set(s.scalars(select(Client.altegio_id).where(Client.do_not_contact.is_(True))))     # told not to call: never suggested
    top, seen = [], set(skip)
    for r in sorted(overdue.result["tables"]["overdue"], key=lambda r: -r["priority"]):       # one line per client, even if overdue with two barbers
        if r["client_id"] not in seen:
            seen.add(r["client_id"]); top.append(r)
    top = top[:5]
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
    return content
