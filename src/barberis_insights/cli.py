"""`insights` command line."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Optional

import typer

from .config import ROOT, settings

app = typer.Typer(help="BARBERIS insights: data, metrics, goals, clients and win-back.", no_args_is_help=True)


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
def snapshot(
    date_from: str = typer.Option(..., "--from"), date_to: str = typer.Option(..., "--to"),
    cohort: Optional[str] = typer.Option(None, help="FROM:TO override for the 90-day-return cohort"),
    save: bool = typer.Option(True, help="Store the measurement"), label: str = "Monthly measurement",
) -> None:
    """Compute every metric for every barber and the team over a window, and store it as a measurement."""
    from .db.session import session_scope
    from .ingest.legacy import save_measurement
    from .metrics import Dataset, compute_snapshot
    co = tuple(_date(x) for x in cohort.split(":")) if cohort else None
    with session_scope() as s:
        snap = compute_snapshot(Dataset.load(s), _date(date_from), _date(date_to), co)
        if save:
            n = save_measurement(s, snap, label)
            typer.echo(f"saved {n} values for {snap['asof']}", err=True)
    typer.echo(json.dumps(snap, ensure_ascii=False, indent=1))


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
def propose(
    segment: list[str] = typer.Option(["overdue"], help="Segments to propose cases for"), limit: int = 30,
    barber: Optional[str] = None, arms: Optional[str] = typer.Option(None, help="Comma-separated offer codes for an A/B test, e.g. call_only,pct10"),
) -> None:
    """Create proposed win-back cases from the top of the risk list (approve them in the dashboard or with `approve`)."""
    from .clients.profile import rebuild_profiles
    from .clients.risk import risk_list
    from .db.session import session_scope
    from .ingest.base import barber_by_key
    from .metrics import Dataset
    from .outreach.service import propose as do_propose
    with session_scope() as s:
        rebuild_profiles(s, Dataset.load(s))
        rows = risk_list(s, tuple(segment), barber_by_key(s, barber).altegio_id if barber else None, limit)
        cases = do_propose(s, rows, arms.split(",") if arms else None)
        typer.echo(f"proposed {len(cases)} cases (eligible candidates: {len(rows)})")


@app.command()
def approve(case_ids: list[int], assigned_to: Optional[str] = None) -> None:
    """Approve proposed cases so the next sheet sync sends them to the admin."""
    from .db.session import session_scope
    from .outreach.service import approve as do_approve
    with session_scope() as s:
        typer.echo(f"approved {do_approve(s, case_ids, assigned_to)}")


@app.command("sheet-sync")
def sheet_sync(dry_run: bool = typer.Option(False, "--dry-run", help="Use an in-memory sheet and roll back"),
               lang: str = typer.Option(None, "--lang", help="Sheet language: uk or en (default: INSIGHTS_SHEET_LANG, uk)")) -> None:
    """Pull the admin's outcomes, mark returned clients, push approved cases, archive closed ones."""
    from .db.session import session_factory
    from .outreach.offers import active_offers
    from .i18n import normalize
    from .outreach.sheets import FakeSheet, GspreadSheet, sync, tab_name
    s = session_factory()()
    try:
        if dry_run:
            sheet = FakeSheet()
        else:
            if not settings.sheet_id:
                raise typer.BadParameter("Set INSIGHTS_SHEET_ID in .env (the id from the sheet URL)")
            try:
                sheet = GspreadSheet(settings.sheet_id)
            except (RuntimeError, FileNotFoundError) as e:
                typer.echo(f"Could not connect to the sheet: {e}", err=True)
                raise typer.Exit(1)
        lang = normalize(lang or settings.sheet_lang)
        out = sync(s, sheet, [o.code for o in active_offers(s)], lang)
        s.rollback() if dry_run else s.commit()
        typer.echo(json.dumps(out | ({"dry_run_rows": sheet.read(tab_name("call", lang))[:5]} if dry_run else {}), ensure_ascii=False, indent=1, default=str))
    finally:
        s.close()


@app.command("sheet-auth")
def sheet_auth() -> None:
    """Connect to the admin call sheet (service-account key, or a one-time Google sign-in) and create its tabs."""
    from .db.session import session_scope
    from .outreach.offers import active_offers
    from .outreach.sheets import GspreadSheet, prepare
    if not settings.sheet_id:
        raise typer.BadParameter("Set INSIGHTS_SHEET_ID in .env first")
    try:
        sheet = GspreadSheet(settings.sheet_id, interactive=True)
    except (RuntimeError, FileNotFoundError) as e:
        typer.echo(f"Could not connect to the sheet: {e}", err=True)
        raise typer.Exit(1)
    with session_scope() as s:
        offers = [o.code for o in active_offers(s)]
    prepare(sheet, offers)
    typer.echo(f"Signed in. Sheet “{sheet.sh.title}” is ready with tabs: {[w.title for w in sheet.sh.worksheets()]}")


@app.command()
def attribute() -> None:
    """Mark contacted clients as won back / not returned from the latest visit data."""
    from .db.session import session_scope
    from .outreach.attribution import attribute as do_attribute
    with session_scope() as s:
        typer.echo(json.dumps(do_attribute(s)))


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
