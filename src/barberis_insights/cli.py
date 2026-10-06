"""`insights` command line."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Optional

import typer

from .config import ROOT, settings

app = typer.Typer(help="BARBERIS insights: data, metrics, goals, clients and win-back.", no_args_is_help=True)
jobs_app = typer.Typer(help="Scheduled jobs: run what is due, run one now, list.", no_args_is_help=True)
notify_app = typer.Typer(help="Telegram: find your chat, send a test message.", no_args_is_help=True)
app.add_typer(jobs_app, name="jobs")
app.add_typer(notify_app, name="notify")


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


@app.command()
def init() -> None:
    """Create or upgrade the database schema."""
    from alembic import command
    from alembic.config import Config

    from .db.session import engine, ensure_fts
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    ensure_fts(engine())
    from .db.session import session_scope
    from .web import auth
    with session_scope() as s:
        if auth.ensure_admin(s):
            typer.echo("created the super-admin user admin / admin: change its password after the first login")
    typer.echo(f"database ready: {settings.db_url}")


@app.command("import-legacy")
def import_legacy_cmd(artifact_export: Optional[Path] = typer.Option(None, help="Folder from `ArtifactData list ... out_dir`")) -> None:
    """One-time import of the refresh skill cache (and the artifact page's goals, tips and measurements)."""
    from .db.session import session_scope
    from .ingest.legacy import import_legacy
    with session_scope() as s:
        out = import_legacy(s, artifact_export=artifact_export)
    typer.echo(json.dumps(out, ensure_ascii=False, indent=1, default=str))


@app.command()
def ingest(files: list[Path] = typer.Argument(..., help="Saved Altegio Pro connector results (appointments, schedules, clients)")) -> None:
    """Import files fetched through the Altegio Pro connector."""
    from .db.session import session_scope
    from .ingest.connector_files import ingest_files
    with session_scope() as s:
        out = ingest_files(s, [str(f) for f in files])
    typer.echo(json.dumps(out, indent=1))


@app.command()
def fetch(through: Optional[str] = typer.Option(None, help="YYYY-MM-DD, default: last Sunday"), ahead: int = typer.Option(0, help="Days into the future to fetch bookings for"),
          schedules: bool = typer.Option(True, help="Also fetch the barbers' shifts (the weekly job does; the daily cases job does not)")) -> None:
    """Pull fresh data from Altegio through a headless Claude and import it (the weekly job's first step), without sending anything."""
    from .db.session import session_scope
    from .jobs import fetch as fetching
    day = _date(through) if through else dt.date.today() - dt.timedelta(days=dt.date.today().weekday() + 1)
    with session_scope() as s:
        typer.echo(json.dumps(fetching.fetch_fresh(s, day, ahead_days=ahead, schedules=schedules), ensure_ascii=False, indent=1, default=str))


@app.command()
def snapshot(
    date_from: str = typer.Option(..., "--from"), date_to: str = typer.Option(..., "--to"),
    cohort: Optional[str] = typer.Option(None, help="FROM:TO override for the 90-day-return cohort"),
    save: bool = typer.Option(True, help="Store the measurement"), label: str = "Monthly measurement",
) -> None:
    """Compute every metric for every barber and the team over a window, and store it as a measurement."""
    from .analyses import service as analyses
    from .db.session import session_scope
    with session_scope() as s:
        row = analyses.run(s, "barber_scorecard", _date(date_from), _date(date_to), params={"cohort": cohort}, created_by="cli",
                           label=label if save else None)
        snap = {"asof": str(row.asof), "run": row.id, "window_from": str(row.window_from), "window_to": str(row.window_to),
                "cohort_window": row.result["context"]["cohort_window"], "versions": row.metric_versions, "values": row.result["kpis"]}
        if save:
            typer.echo(f"stored run {row.id} and its measurement for {snap['asof']}", err=True)
    typer.echo(json.dumps(snap, ensure_ascii=False, indent=1))


@app.command()
def analyses(action: str = typer.Argument("list", help="list | <analysis key>"), date_from: Optional[str] = typer.Option(None, "--from", help="Monday, YYYY-MM-DD"),
             date_to: Optional[str] = typer.Option(None, "--to", help="Sunday, YYYY-MM-DD"), scope: str = "team",
             param: list[str] = typer.Option([], "--param", help="key=value, repeatable"),
             lens: str = typer.Option("raw", help="raw, clean or a saved lens (only barber_scorecard honours one)")) -> None:
    """List the analyses, or run one over whole ISO weeks and store the result as a run."""
    from .analyses import service
    from .db.session import session_scope
    if action == "list":
        typer.echo(json.dumps(service.catalog(), ensure_ascii=False, indent=1))
        return
    if not (date_from and date_to):
        raise typer.BadParameter("--from and --to are required")
    params = {k: (int(v) if v.isdigit() else v) for k, v in (p.split("=", 1) for p in param)}
    with session_scope() as s:
        row = service.run(s, action, _date(date_from), _date(date_to), scope, lens=lens, params=params, created_by="cli")
        typer.echo(json.dumps({"run": row.id, "analysis": row.analysis_key, "version": row.analysis_version, "window": [str(row.window_from), str(row.window_to)],
                               "complete": row.result["complete"], "team": row.result["kpis"].get("team"),
                               "findings": [(f["code"], f["scope"]) for f in row.result["findings"]]}, ensure_ascii=False, indent=1))


@app.command()
def runs(key: Optional[str] = None, scope: Optional[str] = None, limit: int = 20) -> None:
    """List stored analysis runs, newest window first."""
    from .analyses import service
    from .db.session import session_scope
    with session_scope() as s:
        for r in service.list_runs(s, key, scope, limit):
            typer.echo(f"{r.id:>4}  {r.analysis_key:18} v{r.analysis_version}  {r.scope:9} {r.window_from}..{r.window_to}  {'complete' if r.result.get('complete', True) else 'incomplete'}  by {r.created_by}")


@app.command()
def compare(after: int, before: Optional[int] = typer.Argument(None, help="Defaults to the previous comparable run")) -> None:
    """Compare two analysis runs (ids from `insights runs`), metric by metric."""
    from .analyses import service
    from .db.session import session_scope
    with session_scope() as s:
        out = service.compare(s, before, after) if before else service.compare_with_previous(s, after)
    typer.echo(json.dumps(out, ensure_ascii=False, indent=1))


factors_app = typer.Typer(help="Context factors: list, measure a recurring one's effect, test a belief.", no_args_is_help=True)
app.add_typer(factors_app, name="factors")


@factors_app.command("list")
def factors_list(date_from: Optional[str] = typer.Option(None, "--from"), date_to: Optional[str] = typer.Option(None, "--to")) -> None:
    """Factors, or only those in force between two dates."""
    from .context import factors, service as notes
    from .db.session import session_scope
    from .experiments import factor_link
    with session_scope() as s:
        found = factors.in_force(s, _date(date_from or date_to), _date(date_to or date_from)) if (date_from or date_to) else notes.search(s, None, None, limit=500)
        for f in found:
            typer.echo(f"{f.id:>4}  {f.date_from}{('..' + str(f.date_to)) if f.date_to else ''}  {f.kind:8} {f.category:13} {f.treatment:12} "
                       f"{'yearly+' + str(f.lead_days) if f.recurrence == 'yearly' else 'once':9} {factor_link.status(s, f.id):12} {f.title}")


@factors_app.command("seed-holidays")
def factors_seed_holidays() -> None:
    """Add Ukraine's public holidays as recurring factors (from the law; Easter and Trinity are left out). Safe to repeat."""
    from .context import holidays
    from .db.session import session_scope
    with session_scope() as s:
        typer.echo(f"holidays added: {holidays.seed(s)}")


@factors_app.command("estimate")
def factors_estimate(factor_id: int) -> None:
    """Measure a yearly factor's effect from the shop's own history (seasonality analysis)."""
    from .analyses import effects
    from .context.factors import Factor
    from .db.session import session_scope
    with session_scope() as s:
        run = effects.estimate(s, factor_id)
        typer.echo(json.dumps({"run": run.id} | (effects.summary(s, s.get(Factor, factor_id)) or {}), indent=1))


@factors_app.command("belief")
def factors_belief(factor_id: int) -> None:
    """Test a factor's expected effect against the facts."""
    from .db.session import session_scope
    from .experiments import factor_link
    with session_scope() as s:
        h = factor_link.test_belief(s, factor_id)
        typer.echo(json.dumps({"hypothesis": h.id, "status": factor_link.status(s, factor_id), "verdict": (h.result or {}).get("verdict")}, ensure_ascii=False, indent=1))


@jobs_app.command("list")
def jobs_list() -> None:
    """The jobs, their cadence and their last run."""
    from .db.session import session_scope
    from .jobs import service
    with session_scope() as s:
        typer.echo(json.dumps(service.list_jobs(s), ensure_ascii=False, indent=1))


@jobs_app.command("tick")
def jobs_tick(dry_run: bool = typer.Option(False, "--dry-run", help="Only show what is due"), only: Optional[str] = typer.Option(None, help="One job")) -> None:
    """Run every job that is due (this is what the launchd agent calls every 15 minutes). Missed slots are caught up in order."""
    from .db.session import session_factory
    from .jobs import service
    s = session_factory()()
    try:
        typer.echo(json.dumps(service.tick(s, dry_run=dry_run, only=only), ensure_ascii=False, indent=1, default=str))
    finally:
        s.close()


@jobs_app.command("run")
def jobs_run(job: str, slot: Optional[str] = typer.Option(None, help="YYYY-MM-DD[THH], the slot to run (default: the latest one)"),
             dry_run: bool = typer.Option(False, "--dry-run", help="Build and print, store and send nothing")) -> None:
    """Run one job now, whether or not it is due."""
    from .db.session import session_factory
    from .jobs import service
    from .jobs.registry import JOBS
    if job not in JOBS:
        raise typer.BadParameter(f"unknown job; known: {', '.join(JOBS)}")
    when = dt.datetime.strptime(slot if "T" in slot else slot + "T09", service.FMT) if slot else None
    s = session_factory()()
    try:
        out = service.run_now(s, job, when, dry_run)
        if dry_run:
            if job == "weekly_review" and out.get("content"):
                from .clients.names import names_for
                from .notifications import render
                c = out["content"]
                typer.echo(render.weekly_review(c, settings.owner_lang, names_for(s, [x["client_id"] for x in c["overdue"]["top"]])))
                out = {k: v for k, v in out.items() if k != "content"}
            s.rollback()
        else:
            s.commit()
        typer.echo(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    finally:
        s.close()


@jobs_app.command("plist")
def jobs_plist() -> None:
    """Print the launchd agent that runs `jobs tick` every 15 minutes. Save it to ~/Library/LaunchAgents/ and load it yourself."""
    import shutil
    uv = shutil.which("uv") or "uv"
    typer.echo(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.barberis.insights.jobs</string>
  <key>ProgramArguments</key><array><string>{uv}</string><string>--directory</string><string>{ROOT}</string><string>run</string><string>insights</string><string>jobs</string><string>tick</string></array>
  <key>StartInterval</key><integer>900</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>{ROOT}/var/jobs.log</string>
  <key>StandardErrorPath</key><string>{ROOT}/var/jobs.log</string>
</dict></plist>""")


@notify_app.command("discover")
def notify_discover(save: bool = typer.Option(False, "--save", help="Write the chat id to .env as INSIGHTS_TELEGRAM_OWNER_CHAT_ID")) -> None:
    """After pressing Start in the bot, show the chats that wrote to it (and optionally save yours)."""
    from .notifications.channels import get
    from .notifications.channels import ChannelError
    chats = {}
    try:
        updates = get("telegram").updates()
    except ChannelError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    for u in updates:
        c = (u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}).get("chat") or {}
        if c.get("type") in ("private", "group", "supergroup", "channel"):
            chats[c["id"]] = f"{c['type']}: {c.get('title') or c.get('first_name', '')}"
    if not chats:
        typer.echo("No chat yet: open the bot in Telegram and press Start, then run this again.")
        raise typer.Exit(1)
    for cid, name in chats.items():
        typer.echo(f"{cid}  {name}")
    if save:
        if len(chats) != 1:
            raise typer.BadParameter("more than one chat wrote to the bot; put the right id in .env yourself (INSIGHTS_TELEGRAM_OWNER_CHAT_ID)")
        env = ROOT / ".env"
        lines = [l for l in (env.read_text().splitlines() if env.exists() else []) if not l.startswith("INSIGHTS_TELEGRAM_OWNER_CHAT_ID=")]
        env.write_text("\n".join(lines + [f"INSIGHTS_TELEGRAM_OWNER_CHAT_ID={next(iter(chats))}"]) + "\n")
        typer.echo("saved to .env")


@notify_app.command("test")
def notify_test(channel: Optional[str] = typer.Option(None, help="telegram or console")) -> None:
    """Send a test message to the owner."""
    from .db.session import session_scope
    from .notifications import service
    with session_scope() as s:
        if not service.ensure_owner(s):
            raise typer.BadParameter("INSIGHTS_TELEGRAM_OWNER_CHAT_ID is not set: run `insights notify discover --save` after pressing Start in the bot")
        out = service.send_test(s, channel)
        typer.echo(json.dumps([{"channel": d.channel, "status": d.status, "error": d.error} for d in out]))
        if any(d.status != "sent" for d in out):
            raise typer.Exit(1)


@app.command("import-clients")
def import_clients(file: Path, dry_run: bool = typer.Option(False, "--dry-run", help="Only show recognised columns and a count")) -> None:
    """Import the client base exported from Altegio (Clients → Export, .xlsx or .csv): names, phones, consent."""
    from .db.session import session_scope
    from .ingest.client_export import import_client_export, read_export
    if dry_run:
        cols, items, info = read_export(file)
        typer.echo(f"recognised columns: {sorted(cols)}\nrows: {len(items)}; with a phone: {sum(1 for i in items if i['phone'])}; "
                   f"with a client id: {sum(1 for i in items if i['id'])}; comments meaning do-not-contact: {sum(1 for i in items if i['dnc'])}\nfile notes: {info}")
        if "id" not in cols:
            typer.echo("no client-id column: rows will be matched to clients by their first/last visit time (names break ties)")
        missing = [f for f in ("name", "phone") if f not in cols] + ([] if "id" in cols or "last_visit" in cols else ["id or last visit"])
        if missing:
            typer.echo(f"MISSING required columns: {missing} — add their header names to ALIASES in ingest/client_export.py", err=True)
        return
    with session_scope() as s:
        out = import_client_export(s, file)
    typer.echo(json.dumps(out, ensure_ascii=False))


@app.command()
def risk(
    segment: list[str] = typer.Option(["overdue", "lapsed"], help="overdue, lapsed, one_time, slipping, switched, active"),
    barber: Optional[str] = typer.Option(None, help="Usual barber key"), limit: int = 30,
    all_clients: bool = typer.Option(False, "--all", help="Include clients that cannot be called (no phone, no consent, cool-down)"),
) -> None:
    """Rebuild client profiles and print the ranked win-back list."""
    import collections as C

    from .clients.profile import data_asof, rebuild_profiles
    from .clients.risk import risk_list
    from .db.models import ClientProfile
    from .db.session import session_scope
    from .ingest.base import barber_by_key
    from .metrics import Dataset
    from sqlalchemy import select
    with session_scope() as s:
        asof = data_asof(s)
        n = rebuild_profiles(s, Dataset.load(s), asof)
        seg = C.Counter(p.segment for p in s.scalars(select(ClientProfile)))
        typer.echo(f"profiles rebuilt for {n} clients as of {asof}: {dict(seg)}")
        bid = barber_by_key(s, barber).altegio_id if barber else None
        rows = risk_list(s, tuple(segment), bid, limit, include_ineligible=all_clients)
    for r in rows:
        typer.echo(f"{r['priority']:7.2f}  {r['segment']:9} client {r['client_id']:>10}  {r['name'][:22]:22} visits {r['visits']:3}  "
                   f"₴{r['lifetime_spend']:>8,.0f}  last {r['last_visit']} ({r['days_since']}d)  offer {r['suggested_offer']}"
                   + ("" if r["eligible"] else f"  [{', '.join(r['ineligible_reasons'])}]"))


@app.command()
def serve(port: int = settings.port, reload: bool = False) -> None:
    """Run the dashboard on http://127.0.0.1:PORT (local only)."""
    import uvicorn
    uvicorn.run("barberis_insights.web.app:app", host=settings.host, port=port, reload=reload)


@app.command()
def status() -> None:
    """Data freshness, last measurement and the suggested next measurement window."""
    from sqlalchemy import func, select

    from .clients.profile import data_asof
    from .db.models import Appointment, Client, Measurement, ScheduleSlot
    from .db.session import session_scope
    with session_scope() as s:
        asof = data_asof(s)
        last = s.scalar(select(func.max(Measurement.window_to)))
        sched = s.scalar(select(func.max(ScheduleSlot.date)))
        phones = s.scalar(select(func.count(Client.altegio_id)).where(Client.phone.is_not(None)))
        appts = s.scalar(select(func.count(Appointment.id)))
    today = dt.date.today()
    nxt_to = today - dt.timedelta(days=today.weekday() + 1)
    nxt_from = last + dt.timedelta(days=1) if last else None
    typer.echo(json.dumps({"appointments": appts, "completed_visits_up_to": str(asof - dt.timedelta(days=1)), "schedules_up_to": str(sched),
                           "clients_with_phone": phones, "last_measurement_window_to": str(last),
                           "next_window": [str(nxt_from), str(nxt_to)] if nxt_from and (nxt_to - nxt_from).days >= 13 else "too early (needs 2+ whole weeks)",
                           "fetch_appointments_from": str(nxt_from - dt.timedelta(days=14)) if nxt_from else None}, indent=1))


@app.command()
def barber(action: str = typer.Argument(..., help="list | add | deactivate"), key: Optional[str] = None, altegio_id: Optional[int] = None,
           name: Optional[str] = None, tier: str = "", left: Optional[str] = typer.Option(None, help="YYYY-MM-DD last working day")) -> None:
    """List, add or deactivate tracked barbers."""
    from sqlalchemy import select

    from .db.models import Barber
    from .db.session import session_scope
    with session_scope() as s:
        if action == "add":
            if not (key and altegio_id and name):
                raise typer.BadParameter("add needs --key, --altegio-id and --name")
            s.add(Barber(altegio_id=altegio_id, key=key, name=name, tier=tier, active=True, joined=dt.date.today()))
        elif action == "deactivate":
            b = s.scalar(select(Barber).where(Barber.key == key))
            if not b:
                raise typer.BadParameter(f"unknown barber {key}")
            b.active, b.left = False, _date(left) if left else dt.date.today()
        for b in s.scalars(select(Barber).order_by(Barber.altegio_id)):
            typer.echo(f"{b.key:10} {b.altegio_id:>9} {b.name:10} {b.tier:16} {'active' if b.active else 'left ' + str(b.left)}")


@app.command("import-schedule")
def import_schedule(barber: str, file: Path) -> None:
    """Import a barber's working days from a text file: one line per day, `YYYY-MM-DD HH:MM-HH:MM [HH:MM-HH:MM ...]`.
    Dates in the file replace existing slots for those dates."""
    from .db.session import session_scope
    from .ingest.base import barber_by_key, parse_schedule_line, replace_schedule, sync_run
    days = dict(x for x in (parse_schedule_line(l) for l in file.read_text().splitlines()) if x)
    with session_scope() as s, sync_run(s, "schedule_text") as run:
        n = replace_schedule(s, barber_by_key(s, barber).altegio_id, days)
        run.counts = {"barber": barber, "days": len(days), "slots": n}
    typer.echo(f"{barber}: {len(days)} days, {n} slots")


@app.command("mcp")
def mcp_cmd() -> None:
    """Run the MCP server on stdio (for Claude Code / Claude Desktop)."""
    from .mcp_server import main
    main()


@app.command()
def seed() -> None:
    """Add the default offers and the known business events (idempotent)."""
    from .context.service import seed as seed_notes
    from .db.session import session_scope
    from .outreach.offers import seed_offers
    with session_scope() as s:
        typer.echo(f"offers added: {seed_offers(s)}, notes added: {seed_notes(s)}")


@app.command()
def cases(today: Optional[str] = typer.Option(None, help="YYYY-MM-DD, default today"), dry_run: bool = typer.Option(False, "--dry-run", help="Roll back"),
          backfill: bool = typer.Option(False, "--backfill", help="Also open the clients who crossed a line long ago (the highest priority first, up to what the administrators can work)")) -> None:
    """Open new win-back cases and follow the active ones up (what the daily job does after the fresh data is in)."""
    from .cases import service
    from .clients.profile import rebuild_profiles
    from .db.session import session_scope
    from .metrics import Dataset
    day = _date(today) if today else dt.date.today()
    with session_scope() as s:
        rebuild_profiles(s, Dataset.load(s))
        out = {"detect": service.detect(s, day, backfill=backfill), "refresh": service.refresh(s, day)}
        out["detect"].pop("ids")
        if dry_run:
            s.rollback()
        typer.echo(json.dumps(out, ensure_ascii=False, indent=1))


@app.command()
def hypothesis(
    title: str, metric: str = typer.Option(...), kind: str = typer.Option("did", help="did | prepost | offer_ab"),
    treatment: str = typer.Option("", help="Comma-separated barber keys"), control: str = typer.Option("", help="Comma-separated barber keys"),
    intervention: Optional[str] = typer.Option(None, help="YYYY-MM-DD"), pre_weeks: int = 8, post_weeks: int = 8,
    expected: str = typer.Option("up", help="up | down | none"), statement: str = "",
) -> None:
    """Record a hypothesis and evaluate it now."""
    from .db.models import Hypothesis
    from .db.session import session_scope
    from .experiments.evaluate import run
    with session_scope() as s:
        h = Hypothesis(title=title, statement=statement, metric=metric, kind=kind, treatment=[x for x in treatment.split(",") if x],
                       control=[x for x in control.split(",") if x], intervention_date=_date(intervention) if intervention else None,
                       pre_weeks=pre_weeks, post_weeks=post_weeks, expected=expected)
        s.add(h); s.flush()
        res = run(s, h)
        typer.echo(json.dumps({"id": h.id, "status": h.status} | res, ensure_ascii=False, indent=1))


@app.command()
def goals(scope: Optional[str] = None) -> None:
    """Goal progress against the latest measurement."""
    from .db.session import session_scope
    from .goals.service import board
    with session_scope() as s:
        for g in board(s, scope):
            cur = "—" if g["current"] is None else f"{g['current']:g}"
            typer.echo(f"{g['scope']:9} {g['title'][:44]:44} {g['baseline']:>7g} → {cur:>7} → {g['target']:>7g}  {g['label']} ({g['progress']:.0%})")


if __name__ == "__main__":
    app()
