"""The fresh-data step: ask a headless Claude to pull the latest data from Altegio through its connector, and import what it fetched.

There is no direct Altegio API access (the REST token is rejected), so the connector is the only way in, and it lives in a Claude session.
This module runs one non-interactive `claude -p` that may only call the two read tools, reads every connector result straight from the
process output (nothing is retyped into files by the model), and imports them in this process. The model's own report is not trusted: a fetch
counts as successful only when the results were complete and the database received an import.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import ROOT, settings
from ..db.models import Appointment, Barber, Client, SyncRun, now as utcnow
from ..ingest.connector_files import ingest_payloads
from ..ingest.status import data_status


ALLOWED = "mcp__claude_ai_Altegio_Pro__appointments_list,mcp__claude_ai_Altegio_Pro__schedules_get"      # read-only: no files, no shell
WANTED = ("appointments_list", "schedules_get")

PROMPT = """You are the data-fetch step of a scheduled job. Fetch data from Altegio through the connector. Do exactly this and nothing else.

Location id: {location}. Window: {date_from} to {date_to} (inclusive).

1. Call appointments_list for the location with date_from={date_from}, date_to={date_to}, page_size=100, include_contacts=false. Follow pagination.next_page (page 2, 3, ...) until has_more is false.
{schedules}Do not write files, do not summarise or retype any result, do not call any other tool. If a call fails, retry it once, then continue with the rest and report the error.
When all calls are done, reply with one word: done."""


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
    return PROMPT.format(location=settings.location_id, date_from=f, date_to=t, schedules=step)


def parse_stream(text: str) -> dict:
    """What the headless Claude fetched, read from its stream-json output: the connector results themselves, exactly as returned."""
    names: dict[str, str] = {}
    payloads, problems, last_page, reply = [], [], None, ""
    for line in text.splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = e.get("type")
        if kind == "assistant":
            for c in e.get("message", {}).get("content", []):
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    names[c["id"]] = c.get("name", "")
        elif kind == "user":
            for c in e.get("message", {}).get("content", []):
                if not (isinstance(c, dict) and c.get("type") == "tool_result") or not names.get(c.get("tool_use_id", ""), "").endswith(WANTED):
                    continue
                body = c.get("content")
                raw = body if isinstance(body, str) else "".join(x.get("text", "") for x in body if isinstance(x, dict))
                if c.get("is_error"):
                    problems.append(raw[:160]); continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:                      # a large result may be saved to a file and the path given instead
                    m = re.search(r"(/[^\s\"']+\.(?:txt|json))", raw)
                    try:
                        payload = json.loads(Path(m.group(1)).read_text()) if m else None
                    except (OSError, json.JSONDecodeError):
                        payload = None
                    if payload is None:
                        problems.append("a result could not be read: " + raw[:120]); continue
                payloads.append(payload)
                if names[c["tool_use_id"]].endswith("appointments_list") and isinstance(payload, dict):
                    last_page = payload.get("pagination") or {}
        elif kind == "result":
            reply = str(e.get("result", ""))[-300:]
            if e.get("is_error"):
                problems.append(reply)
    appointments = [p for p in payloads if isinstance(p, dict) and "items" in p and "date_from" not in p]
    if appointments and last_page and last_page.get("has_more"):
        problems.append("the appointment pages stopped before the last one")
    if not appointments:
        problems.append("no appointment result was received")
    return {"payloads": payloads, "problems": problems, "reply": reply}


def _runner(prompt: str, out: Path | None = None) -> dict:
    """Run the headless Claude and return what it fetched. Replaced in tests."""
    env = None
    if settings.fetch_claude_config_dir:
        env = os.environ | {"CLAUDE_CONFIG_DIR": str(settings.fetch_claude_config_dir)}
    cmd = [_claude(), "-p", prompt, "--allowedTools", ALLOWED, "--permission-mode", "acceptEdits", "--output-format", "stream-json", "--verbose",
           "--max-turns", str(settings.fetch_max_turns)]
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=settings.fetch_timeout, stdin=subprocess.DEVNULL)
    got = parse_stream(r.stdout)
    if r.returncode != 0 and not got["payloads"]:
        return {"ok": False, "error": (r.stderr or r.stdout)[-400:], "payloads": []}
    got["ok"] = not got["problems"]
    if got["problems"]:
        got["error"] = "; ".join(got["problems"])[:400]
    return got


def fetch_fresh(s: Session, through: dt.date, now: dt.datetime | None = None, ahead_days: int = 0, schedules: bool = True) -> dict:
    """Pull fresh data and say what changed in the database. Never raises: a failed fetch is a result.
    The daily cases job asks for appointments only, reaching `ahead_days` into the future for bookings."""
    f, t = window(s, through, ahead_days)
    s.commit()
    started = utcnow()
    before = (data_status(s), s.scalar(select(func.count(Appointment.id))), s.scalar(select(func.count(Client.altegio_id))))
    try:
        res = _runner(build_prompt(s, f, t, None, schedules))
        if res.get("ok") and "payloads" in res:          # the real runner returns what it fetched; import it here, in this process
            res["import"] = ingest_payloads(s, res["payloads"])
            if res["import"]["skipped_files"]:
                res["ok"], res["error"] = False, f"{res['import']['skipped_files']} fetched results were not in a shape the importer knows (the connector may have changed)"
        res.pop("payloads", None)
    except Exception as e:                               # a missing binary, a timeout
        s.rollback()
        res = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
    s.commit()
    imported = s.scalar(select(func.count(SyncRun.id)).where(SyncRun.source == "connector_files", SyncRun.status == "ok", SyncRun.started >= started))
    after = (data_status(s), s.scalar(select(func.count(Appointment.id))), s.scalar(select(func.count(Client.altegio_id))))
    res |= {"started_at": started.isoformat(), "window": [str(f), str(t)], "last_visit": str(after[0]["last_visit"]), "last_schedule": str(after[0]["last_schedule"]),
            "appointments_added": after[1] - before[1], "clients_added": after[2] - before[2]}
    res["imported"] = bool(imported)
    if res.get("ok") and not imported:                    # Claude said it was done, but the database received nothing: that is a failure
        res["ok"], res["error"] = False, "the fetch finished but nothing was imported: " + str(res.get("reply", ""))[-160:]
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
