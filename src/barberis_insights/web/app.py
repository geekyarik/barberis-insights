"""Local dashboard (server-rendered pages + JSON API). Run with `insights serve`; binds to 127.0.0.1 only."""
from __future__ import annotations

import collections as C
import datetime as dt
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..clients.profile import data_asof, rebuild_profiles
from ..clients.risk import CALLABLE, risk_list
from ..config import settings
from ..context import service as notes
from ..db.models import Appointment, Barber, Client, ClientProfile, Hypothesis, Measurement, OutreachCase, SyncRun
from ..db.session import session_factory
from ..experiments.evaluate import run as run_hypothesis
from ..goals import service as goals
from ..i18n import LANGUAGES, normalize, t as tr, translator
from ..ingest.legacy import save_measurement
from ..metrics import compute_snapshot
from ..metrics.registry import REGISTRY, catalog
from ..metrics.weekly import weekly_rows
from ..outreach import service as outreach
from ..outreach.offers import active_offers
from ..playbook import service as playbook
from . import data as vm

HERE = Path(__file__).parent
app = FastAPI(title="BARBERIS insights", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.globals.update(fmt=vm.fmt, delta_class=vm.delta_class, REGISTRY=REGISTRY)
SEGMENTS = ("overdue", "lapsed", "one_time", "slipping", "switched", "active")


@app.middleware("http")
async def same_origin_writes(request: Request, call_next):
    """Block cross-site form posts to the local server (another website cannot change data here)."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin and urlparse(origin).netloc != request.url.netloc:
            return JSONResponse({"detail": "cross-site request blocked"}, status_code=403)
    return await call_next(request)


def db():
    s = session_factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


LANG_COOKIE = "lang"


def lang_of(request: Request) -> str:
    """Interface language: the viewer's choice (cookie), else Ukrainian — the team's language."""
    return normalize(request.cookies.get(LANG_COOKIE))


def helpers(lang: str) -> dict:
    """Template functions bound to one language. Codes (segments, statuses, offers…) are translated through
    catalog prefixes and fall back to the code itself, so unknown data still shows."""
    t = translator(lang)

    def label(prefix: str, code, default=None) -> str:
        key = f"{prefix}{code}"
        text = t(key)
        return text if text != key else (default or str(code))

    def mlabel(metric: str) -> str:
        return label("metric.", metric, REGISTRY[metric].label if metric in REGISTRY else metric)

    def verdict(res: dict) -> str:
        msg = res.get("msg")
        if not msg:
            return res.get("verdict", "")
        p = dict(msg.get("params", {}))
        if "metric" in p:
            p["metric"] = mlabel(p["metric"])
        for k in ("a", "b"):
            if k in p:
                p[k] = label("offer.", p[k])
        return t("verdict." + msg["key"], **p) + (t("verdict.vs_control") if msg.get("control") else "")

    return {"t": t, "lang": lang, "languages": LANGUAGES, "label": label, "mlabel": mlabel, "verdict": verdict,
            "reasons": lambda codes: ", ".join(label("reason.", c) for c in codes)}


def page(request: Request, s: Session, name: str, nav: str, title: str = "", **ctx):
    h = helpers(lang_of(request))
    return templates.TemplateResponse(request, name, {"nav": nav, "all_barbers": vm.barbers(s), "flash": request.query_params.get("msg"),
                                                      "flash_kind": request.query_params.get("kind"), "title": h["t"](title), **h, **ctx})


def back(request: Request, url: str, key: str | None = None, kind: str = "", **params) -> RedirectResponse:
    """Redirect with a confirmation message, translated now into the viewer's language (catalog key "flash.<key>")."""
    sep = "&" if "?" in url else "?"
    msg = tr(f"flash.{key}", lang_of(request), **params) if key else None
    return RedirectResponse(url + (f"{sep}msg={quote(msg)}&kind={kind}" if msg else ""), status_code=303)


@app.get("/lang/{code}")
def set_language(code: str, next: str = "/"):
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    r = RedirectResponse(target, status_code=303)
    r.set_cookie(LANG_COOKIE, normalize(code), max_age=365 * 24 * 3600, samesite="lax", httponly=True)
    return r


def names(s: Session) -> dict[int, str]:
    return {b.altegio_id: b.name for b in s.scalars(select(Barber))}


# ---------------------------------------------------------------- overview
KEY_METRICS = ["util", "rph", "visits_wk", "check", "online", "addon", "conv_new90", "risk_n"]


@app.get("/", response_class=HTMLResponse)
def overview(request: Request, s: Session = Depends(db)):
    dates = vm.measurement_dates(s)
    latest = dates[-1] if dates else None
    prev = dates[-2] if len(dates) > 1 else None
    cur, before = vm.values_at(s, latest), vm.values_at(s, prev)
    board = goals.board(s)
    states = C.Counter(g["state"] for g in board)
    cases = C.Counter(st for (st,) in s.execute(select(OutreachCase.status)))
    seg = C.Counter(st for (st,) in s.execute(select(ClientProfile.segment)))
    no_phone = s.scalar(select(func.count(ClientProfile.client_id)).where(ClientProfile.segment.in_(CALLABLE))) or 0
    with_phone = s.scalar(select(func.count(Client.altegio_id)).where(Client.phone.is_not(None))) or 0
    return page(request, s, "overview.html", "overview", title="nav.overview", latest=latest, prev=prev, cur=cur, before=before,
                key_metrics=KEY_METRICS, board=board, states=states, cases=cases, seg=seg, callable_n=no_phone, with_phone=with_phone,
                data_asof=data_asof(s))


# ---------------------------------------------------------------- barber
@app.get("/barber/{key}", response_class=HTMLResponse)
def barber_page(request: Request, key: str, weeks: int = 26, s: Session = Depends(db)):
    b = s.scalar(select(Barber).where(Barber.key == key))
    if not b:
        raise HTTPException(404)
    ds = vm.dataset(s)
    end = data_asof(s) - dt.timedelta(days=1)
    rows = weekly_rows(ds, b.altegio_id, end - dt.timedelta(weeks=weeks - 1), end)
    dates = vm.measurement_dates(s)
    cur = vm.values_at(s, dates[-1] if dates else None).get(key, {})
    risk = risk_list(s, ("overdue",), b.altegio_id, 15, include_ineligible=True)
    return page(request, s, "barber.html", key, title=b.name, b=b, rows=rows, weeks=weeks, cur=cur, key_metrics=KEY_METRICS,
                goals=goals.board(s, key), tips=playbook.listing(s, key), risk=risk, catalog=catalog(), latest=dates[-1] if dates else None)


# ---------------------------------------------------------------- goals
@app.get("/goals", response_class=HTMLResponse)
def goals_page(request: Request, s: Session = Depends(db)):
    board = goals.board(s)
    by_scope = C.defaultdict(list)
    for g in board:
        by_scope[g["scope"]].append(g)
    order = ["team"] + [b.key for b in vm.barbers(s)]
    return page(request, s, "goals.html", "goals", title="nav.goals", by_scope=by_scope, order=order, catalog=catalog(),
                scope_names={"team": tr("common.team", lang_of(request))} | {b.key: b.name for b in vm.barbers(s)})


@app.post("/goals")
def goal_save(request: Request, goal_id: str = Form(""), scope: str = Form(...), title: str = Form(...), metric: str = Form(...), baseline: str = Form(""),
              target: float = Form(...), due: str = Form(...), status: str = Form("active"), actions: str = Form(""),
              manual_current: str = Form(""), next_url: str = Form("/goals"), s: Session = Depends(db)):
    data = {"scope": scope, "title": title.strip(), "metric": metric, "target": target, "due": due, "status": status, "actions": actions.strip(),
            "baseline": float(baseline) if baseline.strip() else None, "manual_current": float(manual_current) if manual_current.strip() else None}
    if goal_id:
        g = s.get(goals.Goal, goal_id)
        if g and data["baseline"] is None:
            data["baseline"] = g.baseline
    goals.upsert(s, data, goal_id or None)
    return back(request, next_url, "goal_saved")


@app.post("/goals/{goal_id}/delete")
def goal_delete(request: Request, goal_id: str, confirm: str = Form(""), next_url: str = Form("/goals"), s: Session = Depends(db)):
    if confirm != "yes":
        return back(request, next_url, "goal_confirm", "warn")
    goals.delete(s, goal_id)
    return back(request, next_url, "goal_deleted")


# ---------------------------------------------------------------- clients at risk
@app.get("/risk", response_class=HTMLResponse)
def risk_page(request: Request, segment: list[str] | None = None, barber: str = "", show_all: bool = False, limit: int = 100,
              s: Session = Depends(db)):
    segment = segment or ["overdue"]
    bid = s.scalar(select(Barber.altegio_id).where(Barber.key == barber)) if barber else None
    rows = risk_list(s, tuple(segment), bid, limit, include_ineligible=show_all)
    proposed = outreach.case_rows(s, ("proposed",))
    seg = C.Counter(st for (st,) in s.execute(select(ClientProfile.segment)))
    asof = s.scalar(select(func.max(ClientProfile.asof)))
    return page(request, s, "risk.html", "risk", title="nav.risk", rows=rows, segments=SEGMENTS, chosen=segment, barber=barber,
                show_all=show_all, proposed=proposed, seg=seg, bnames=names(s), asof=asof, offers=active_offers(s))


@app.post("/risk/rebuild")
def risk_rebuild(request: Request, s: Session = Depends(db)):
    n = rebuild_profiles(s, vm.dataset(s))
    return back(request, "/risk", "profiles_rebuilt", n=n)


@app.post("/risk/propose")
async def risk_propose(request: Request, s: Session = Depends(db)):
    form = await request.form()
    ids = {int(x) for x in form.getlist("client_id")}
    arms = [a for a in form.getlist("arms") if a]
    rows = [r for r in risk_list(s, SEGMENTS, None, 100000, include_ineligible=False) if r["client_id"] in ids]
    cases = outreach.propose(s, rows, arms or None)
    return back(request, "/risk", "proposed", n=len(cases))


@app.post("/cases/decide")
async def cases_decide(request: Request, s: Session = Depends(db)):
    form = await request.form()
    ids = [int(x) for x in form.getlist("case_id")]
    action = form.get("action")
    if action == "approve":
        n = outreach.approve(s, ids, (form.get("assigned_to") or "").strip() or None)
        return back(request, form.get("next_url") or "/risk", "approved", n=n)
    n = outreach.skip(s, ids, (form.get("note") or "").strip() or None)
    return back(request, form.get("next_url") or "/risk", "skipped", n=n)


# ---------------------------------------------------------------- client card
@app.get("/client/{cid}", response_class=HTMLResponse)
def client_page(request: Request, cid: int, s: Session = Depends(db)):
    c, p = s.get(Client, cid), s.get(ClientProfile, cid)
    visits = list(s.scalars(select(Appointment).where(Appointment.client_id == cid, Appointment.deleted.is_(False)).order_by(Appointment.date.desc()).limit(40)))
    if not (c or p or visits):
        raise HTTPException(404)
    cases = list(s.scalars(select(OutreachCase).where(OutreachCase.client_id == cid).order_by(OutreachCase.created.desc())))
    per_barber = C.Counter(v.barber_id for v in visits if v.status == "arrived")
    return page(request, s, "client.html", "risk", title=c.name if c and c.name else tr("client.fallback", lang_of(request), id=cid), cid=cid, c=c, p=p, visits=visits,
                cases=cases, per_barber=per_barber, bnames=names(s))


@app.post("/client/{cid}/dnc")
def client_dnc(request: Request, cid: int, value: str = Form("on"), s: Session = Depends(db)):
    c = s.get(Client, cid) or Client(altegio_id=cid)
    c.do_not_contact = value == "on"; s.add(c)
    return back(request, f"/client/{cid}", "dnc_updated")


# ---------------------------------------------------------------- win-back
@app.get("/outreach", response_class=HTMLResponse)
def outreach_page(request: Request, status: str = "", s: Session = Depends(db)):
    statuses = (status,) if status else outreach.OPEN + outreach.CLOSED
    rows = outreach.case_rows(s, statuses)
    all_cases = list(s.scalars(select(OutreachCase)))
    contacted = [c for c in all_cases if c.status in ("won_back", "not_returned")]
    by = lambda key: sorted(((k, sum(1 for c in v if c.status == "won_back"), len(v), sum(c.revenue_recovered or 0 for c in v)) for k, v in
                             _group(contacted, key).items()), key=lambda r: -r[2])
    return page(request, s, "outreach.html", "outreach", title="nav.outreach", rows=rows, status=status, counts=C.Counter(c.status for c in all_cases),
                won=sum(1 for c in contacted if c.status == "won_back"), closed=len(contacted), revenue=sum(c.revenue_recovered or 0 for c in contacted),
                by_offer=by(lambda c: c.offer_given or c.suggested_offer or "—"), by_admin=by(lambda c: c.assigned_to or "—"),
                by_segment=by(lambda c: c.segment), statuses=outreach.OPEN + outreach.CLOSED, outcomes=outreach.OUTCOMES,
                offers=active_offers(s), sheet=bool(settings.sheet_id), bnames=names(s))


def _group(items, key):
    g = C.defaultdict(list)
    for x in items:
        g[key(x)].append(x)
    return g


@app.post("/cases/{case_id}/status")
def case_status(request: Request, case_id: int, status: str = Form(...), note: str = Form(""), offer: str = Form(""), s: Session = Depends(db)):
    c = s.get(OutreachCase, case_id)
    if not c:
        raise HTTPException(404)
    outreach.set_status(s, c, status, note=note.strip() or None, offer=offer or None)
    return back(request, f"/client/{c.client_id}", "case_status", id=case_id, status=helpers(lang_of(request))["label"]("status.", status))


@app.post("/outreach/sync")
def outreach_sync(request: Request, s: Session = Depends(db)):
    if not settings.sheet_id:
        return back(request, "/outreach", "sheet_missing", "warn")
    from ..outreach.sheets import GspreadSheet, sync
    try:
        r = sync(s, GspreadSheet(settings.sheet_id), [o.code for o in active_offers(s)])
    except Exception as e:  # shown to the user, nothing written on failure
        s.rollback()
        return back(request, "/outreach", "sheet_failed", "warn", error=e)
    return back(request, "/outreach", "synced", pulled=r["pulled_changes"], pushed=r["pushed"], archived=r["archived"], won=r["won_back"],
                lost=r["not_returned"])


# ---------------------------------------------------------------- context
@app.get("/context", response_class=HTMLResponse)
def context_page(request: Request, q: str = "", scope: str = "", s: Session = Depends(db)):
    found = notes.search(s, q or None, scope or None, limit=200)
    return page(request, s, "context.html", "context", title="nav.context", notes=found, q=q, scope=scope, kinds=notes.KINDS, today=dt.date.today())


@app.post("/context")
def context_add(request: Request, title: str = Form(...), date_from: str = Form(...), date_to: str = Form(""), kind: str = Form("observation"),
                scopes: list[str] = Form(["shop"]), tags: str = Form(""), body: str = Form(""), s: Session = Depends(db)):
    notes.add(s, title.strip(), date_from, body.strip(), kind, scopes, [t.strip() for t in tags.split(",") if t.strip()], date_to or None)
    return back(request, "/context", "note_added")


@app.post("/context/{nid}/delete")
def context_delete(request: Request, nid: int, s: Session = Depends(db)):
    n = s.get(notes.Note, nid)
    if n:
        s.delete(n)
    return back(request, "/context", "note_deleted")


# ---------------------------------------------------------------- hypotheses
@app.get("/hypotheses", response_class=HTMLResponse)
def hypotheses_page(request: Request, s: Session = Depends(db)):
    hs = list(s.scalars(select(Hypothesis).order_by(Hypothesis.created.desc())))
    return page(request, s, "hypotheses.html", "hypotheses", title="nav.hypotheses", hs=hs, catalog=catalog())


@app.post("/hypotheses")
def hypothesis_add(request: Request, title: str = Form(...), statement: str = Form(""), metric: str = Form(...), kind: str = Form("did"),
                   treatment: list[str] = Form([]), control: list[str] = Form([]), intervention: str = Form(""), pre_weeks: int = Form(8),
                   post_weeks: int = Form(8), expected: str = Form("up"), s: Session = Depends(db)):
    h = Hypothesis(title=title.strip(), statement=statement.strip(), metric=metric, kind=kind, treatment=treatment, control=control,
                   intervention_date=dt.date.fromisoformat(intervention) if intervention else None, pre_weeks=pre_weeks, post_weeks=post_weeks, expected=expected)
    s.add(h); s.flush()
    if kind != "offer_ab" and not intervention:
        return back(request, "/hypotheses", "hyp_need_date", "warn")
    res = run_hypothesis(s, h)
    return back(request, "/hypotheses", "hyp_evaluated", verdict=helpers(lang_of(request))["verdict"](res))


@app.post("/hypotheses/{hid}/evaluate")
def hypothesis_eval(request: Request, hid: int, s: Session = Depends(db)):
    h = s.get(Hypothesis, hid)
    res = run_hypothesis(s, h)
    return back(request, "/hypotheses", "hyp_evaluated", verdict=helpers(lang_of(request))["verdict"](res))


@app.post("/hypotheses/{hid}/delete")
def hypothesis_delete(request: Request, hid: int, s: Session = Depends(db)):
    h = s.get(Hypothesis, hid)
    if h:
        s.delete(h)
    return back(request, "/hypotheses", "hyp_deleted")


# ---------------------------------------------------------------- playbook
@app.get("/playbook", response_class=HTMLResponse)
def playbook_page(request: Request, s: Session = Depends(db)):
    return page(request, s, "playbook.html", "playbook", title="nav.playbook", tips=playbook.listing(s))


@app.post("/playbook")
def playbook_save(request: Request, tip_id: str = Form(""), title: str = Form(...), tag: str = Form(""), body: str = Form(""), barbers: list[str] = Form([]),
                  s: Session = Depends(db)):
    playbook.upsert(s, {"title": title.strip(), "tag": tag.strip(), "body": body.strip(), "barbers": barbers}, tip_id or None)
    return back(request, "/playbook", "tip_saved")


@app.post("/playbook/{tip_id}/delete")
def playbook_delete(request: Request, tip_id: str, s: Session = Depends(db)):
    t = s.get(playbook.Tip, tip_id)
    if t:
        s.delete(t)
    return back(request, "/playbook", "tip_deleted")


# ---------------------------------------------------------------- data & sync
@app.get("/data", response_class=HTMLResponse)
def data_page(request: Request, s: Session = Depends(db)):
    runs = list(s.scalars(select(SyncRun).order_by(SyncRun.started.desc()).limit(30)))
    months = s.execute(select(func.strftime("%Y-%m", Appointment.date), func.count()).group_by(func.strftime("%Y-%m", Appointment.date))).all()
    snaps = s.execute(select(Measurement.asof, Measurement.window_from, Measurement.window_to, Measurement.label, func.count())
                      .group_by(Measurement.asof, Measurement.window_from, Measurement.window_to, Measurement.label).order_by(Measurement.asof)).all()
    last = s.scalar(select(func.max(Measurement.window_to)))
    suggest_from = (last + dt.timedelta(days=1)) if last else None
    today = dt.date.today(); suggest_to = today - dt.timedelta(days=today.weekday() + 1)
    return page(request, s, "data.html", "data", title="nav.data", runs=runs, months=months, snaps=snaps, data_asof=data_asof(s),
                suggest_from=suggest_from, suggest_to=suggest_to)


@app.post("/data/snapshot")
def data_snapshot(request: Request, date_from: str = Form(...), date_to: str = Form(...), s: Session = Depends(db)):
    f, t = dt.date.fromisoformat(date_from), dt.date.fromisoformat(date_to)
    if (t - f).days < 13:
        return back(request, "/data", "measure_short", "warn")
    snap = compute_snapshot(vm.dataset(s), f, t)
    n = save_measurement(s, snap, "Monthly measurement")
    return back(request, "/data", "measure_saved", date=t, n=n)


# ---------------------------------------------------------------- JSON API (for scripts, Claude, a future SPA)
@app.get("/api/metrics")
def api_metrics():
    return catalog()


@app.get("/api/measurements")
def api_measurements(scope: str | None = None, metric: str | None = None, s: Session = Depends(db)):
    q = select(Measurement).order_by(Measurement.asof)
    if scope:
        q = q.where(Measurement.scope == scope)
    if metric:
        q = q.where(Measurement.metric == metric)
    return [{"asof": str(m.asof), "scope": m.scope, "metric": m.metric, "value": m.value, "metric_version": m.metric_version, "window": [str(m.window_from), str(m.window_to)]} for m in s.scalars(q)]


@app.get("/api/goals")
def api_goals(scope: str | None = None, s: Session = Depends(db)):
    return goals.board(s, scope)


@app.get("/api/weekly/{key}")
def api_weekly(key: str, weeks: int = 26, s: Session = Depends(db)):
    b = s.scalar(select(Barber).where(Barber.key == key))
    if not b:
        raise HTTPException(404)
    end = data_asof(s) - dt.timedelta(days=1)
    return weekly_rows(vm.dataset(s), b.altegio_id, end - dt.timedelta(weeks=weeks - 1), end)


@app.get("/api/risk")
def api_risk(segment: str = "overdue", barber: str | None = None, limit: int = 50, s: Session = Depends(db)):
    bid = s.scalar(select(Barber.altegio_id).where(Barber.key == barber)) if barber else None
    return risk_list(s, tuple(segment.split(",")), bid, limit, include_ineligible=True)


@app.get("/api/notes")
def api_notes(q: str | None = None, scope: str | None = None, s: Session = Depends(db)):
    return [notes.as_dict(n) for n in notes.search(s, q, scope)]
