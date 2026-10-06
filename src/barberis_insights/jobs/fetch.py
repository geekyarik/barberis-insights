"""The fresh-data step of the weekly flow: ask a headless Claude to pull the latest data from Altegio through its connector and import it.

There is no direct Altegio API access (the REST token is rejected), so the connector is the only way in, and it lives in a Claude
session. This module runs one non-interactive `claude -p` with only the tools it needs, then checks the database to see what arrived.
The model's report is not trusted: the result is what the database holds afterwards (`data_status`).
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import ROOT, settings
from ..db.models import Appointment, Barber, Client, SyncRun, now as utcnow
from ..ingest.status import data_status

ALLOWED = ("mcp__claude_ai_Altegio_Pro__appointments_list,mcp__claude_ai_Altegio_Pro__schedules_get,"
           "Write,Read,Bash(uv run insights ingest:*),Bash(ls:*)")

PROMPT = """You are the data-fetch step of a scheduled job. Fetch fresh data from Altegio through the connector and import it. Do exactly this and nothing else.

Location id: {location}. Window: {date_from} to {date_to} (inclusive). Save files in: {out}

1. Call appointments_list for the location with date_from={date_from}, date_to={date_to}, page_size=300, include_contacts=false. Follow pagination.next_page until it is null.
{schedules}3. Every result must end up as a JSON file that holds the result object exactly as the tool returned it (no edits, no summary). When the tool saved a large result to a file, ingest that file from where it is. When it came back inline, write it unchanged with Write to {out}/<tool>-<n>.json.
4. Import all files in one command: uv run insights ingest <file> <file> ...
5. Reply with one line: the ingest command's JSON output, or the first error you hit.

Do not read or print client names or phone numbers. Do not call any other tool. If a call fails, retry it once, then continue with the rest and report the error."""


def _claude() -> str | None:
    return settings.fetch_claude_bin or shutil.which("claude") or str(Path.home() / ".local/bin/claude")


def window(s: Session, through: dt.date, ahead_days: int = 0) -> tuple[dt.date, dt.date]:
    """From two weeks before the newest imported visit (late status changes) to `through`, never more than two months back from it.
    `ahead_days` reaches into the future, to see bookings."""
    last = data_status(s)["last_visit"]
    start = (last - dt.timedelta(days=14)) if last else through - dt.timedelta(days=28)
    return max(start, through - dt.timedelta(days=60)), through + dt.timedelta(days=ahead_days)


def build_prompt(s: Session, f: dt.date, t: dt.date, out: Path, schedules: bool = True) -> str:
    barbers = "\n".join(f"   - {b.name}: team_member_id={b.altegio_id}" for b in s.scalars(select(Barber).where(Barber.active.is_(True))))
    step = (f"2. For each active team member below call schedules_get with date_from={f}, date_to={t}:\n{barbers}\n") if schedules else ""
    return PROMPT.format(location=settings.location_id, date_from=f, date_to=t, out=out, schedules=step)


def _runner(prompt: str, out: Path) -> dict:
    """Run the headless Claude. Replaced in tests."""
    env = None
    if settings.fetch_claude_config_dir:
        import os
        env = os.environ | {"CLAUDE_CONFIG_DIR": str(settings.fetch_claude_config_dir)}
    cmd = [_claude(), "-p", prompt, "--allowedTools", ALLOWED, "--permission-mode", "acceptEdits", "--output-format", "json",
           "--max-turns", str(settings.fetch_max_turns), "--add-dir", str(out)]
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=settings.fetch_timeout, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        return {"ok": False, "error": (r.stderr or r.stdout)[-400:]}
    try:
        res = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": r.stdout[-400:]}
    return {"ok": not res.get("is_error"), "reply": str(res.get("result", ""))[-400:]}


def fetch_fresh(s: Session, through: dt.date, now: dt.datetime | None = None, ahead_days: int = 0, schedules: bool = True) -> dict:
    """Pull fresh data and say what changed in the database. Never raises: a failed fetch is a result.
    The daily cases job asks for appointments only, reaching `ahead_days` into the future for bookings."""
    f, t = window(s, through, ahead_days)
    out = settings.data_dir / "fetch" / (now or dt.datetime.now()).strftime("%Y%m%dT%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    s.commit()                                           # release any lock: the import runs in another process
    started = utcnow()
    before = (data_status(s), s.scalar(select(func.count(Appointment.id))), s.scalar(select(func.count(Client.altegio_id))))
    try:
        res = _runner(build_prompt(s, f, t, out, schedules), out)
    except Exception as e:                               # a missing binary, a timeout
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
    s.expire_all()
    s.commit()                                           # see what the ingest (a separate process) wrote
    after = (data_status(s), s.scalar(select(func.count(Appointment.id))), s.scalar(select(func.count(Client.altegio_id))))
    res |= {"started_at": started.isoformat(), "window": [str(f), str(t)], "last_visit": str(after[0]["last_visit"]), "last_schedule": str(after[0]["last_schedule"]),
            "appointments_added": after[1] - before[1], "clients_added": after[2] - before[2]}
    shutil.rmtree(out, ignore_errors=True)
    return res


def reconcile_future(s: Session, fetch_result: dict, today: dt.date, ahead_days: int) -> int:
    """Altegio drops a cancelled appointment from its list instead of marking it, so a booking we no longer see is gone.
    Only after a fetch that really imported something, and only inside the window the fetch covered."""
    if not fetch_result.get("ok"):
        return 0
    since = dt.datetime.fromisoformat(fetch_result["started_at"])
    imported = s.scalar(select(func.count(SyncRun.id)).where(SyncRun.source == "connector_files", SyncRun.status == "ok", SyncRun.started >= since))
    if not imported:
        return 0
    gone = list(s.scalars(select(Appointment).where(Appointment.date >= today, Appointment.date <= today + dt.timedelta(days=ahead_days), Appointment.deleted.is_(False),
                                                     Appointment.status.in_(("waiting", "confirmed")), Appointment.fetched_at < since)))
    for a in gone:
        a.deleted = True
    s.flush()
    return len(gone)
