"""Local dashboard (server-rendered pages + JSON API). Run with `insights serve`; binds to 127.0.0.1 only."""
from __future__ import annotations

import collections as C
import datetime as dt
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..analyses import effects, service as analyses
from ..clients.profile import data_asof, rebuild_profiles
from ..clients import contact
from ..cases import calibration, service as cases
from ..clients.risk import CALLABLE, risk_list
from ..config import settings
from ..clients.names import names_for
from ..context import factors, service as notes
from ..db.models import Appointment, Barber, Client, ClientProfile, Hypothesis, Measurement, RiskCase, SyncRun
from ..db.session import session_factory
from ..experiments import factor_link
from ..experiments.evaluate import run as run_hypothesis
from ..goals import service as goals
from ..i18n import LANGUAGES, normalize, t as tr, translator
from ..ingest.legacy import save_measurement
from ..ingest.status import data_status
from ..jobs import service as jobs_service
from ..metrics import compute_snapshot
from ..metrics.registry import REGISTRY, catalog
from ..metrics.weekly import weekly_rows
from ..playbook import service as playbook
from . import auth, charts, data as vm
from ..db.models import User

HERE = Path(__file__).parent
@asynccontextmanager
async def lifespan(_app):
    s = session_factory()()
    try:
        if auth.ensure_admin(s):
            s.commit()
    finally:
        s.close()
    yield


app = FastAPI(title="BARBERIS insights", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.globals.update(fmt=vm.fmt, kfmt=vm.kfmt, signed=vm.signed, delta_class=vm.delta_class, REGISTRY=REGISTRY, spark=charts.spark, line_chart=charts.line_chart,
                             rank_bars=charts.rank_bars, diverging=charts.diverging, stack100=charts.stack100, stacked_columns=charts.stacked_columns,
                             bullet=charts.bullet, delta_chip=charts.delta_chip)


def goal_bullet(g: dict):
    """A goal's progress bar, formatted for its metric (start, now, target)."""
    cur = g["current"] if g["current"] is not None else g["baseline"]
    return charts.bullet(start=g["baseline"], current=cur, target=g["target"], fmt=lambda v: vm.fmt(g["metric"], v), lower_is_better=g["target"] < g["baseline"])


templates.env.globals["goal_bullet"] = goal_bullet
SEGMENTS = ("overdue", "lapsed", "one_time", "slipping", "switched", "active")


@app.middleware("http")
async def same_origin_writes(request: Request, call_next):
    """Block cross-site form posts to the local server (another website cannot change data here)."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin") or request.headers.get("referer")
        if origin and urlparse(origin).netloc != request.url.netloc:
            return JSONResponse({"detail": "cross-site request blocked"}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    """Everything needs a login except the login page and static files; an administrator may open only the Clients section."""
    path = request.url.path
    request.state.user = None
    if not path.startswith(auth.PUBLIC):
        s = session_factory()()
        try:
            user = auth.user_for_token(s, request.cookies.get(auth.COOKIE))
            if user is not None:
                request.state.user = {"id": user.id, "username": user.username, "name": user.display_name or user.username, "role": user.role,
                                      "must_change_password": user.must_change_password}
        finally:
            s.close()
        u = request.state.user
        if u is None:
            if path.startswith("/api/"):
                return JSONResponse({"detail": "login required"}, status_code=401)
            return RedirectResponse(f"/login?next={quote(path + ('?' + request.url.query if request.url.query else ''))}", status_code=303)
        if not auth.allowed(u["role"], path):
            if path.startswith("/api/") or request.method != "GET":
                return JSONResponse({"detail": "not allowed for your role"}, status_code=403)
            return RedirectResponse(auth.HOME[u["role"]], status_code=303)
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
    return templates.TemplateResponse(request, name, {"nav": nav, "user": getattr(request.state, "user", None), "all_barbers": vm.barbers(s), "fresh": freshness(s), "flash": request.query_params.get("msg"),
                                                      "flash_kind": request.query_params.get("kind"), "title": h["t"](title), **h, **ctx})


def back(request: Request, url: str, key: str | None = None, kind: str = "", **params) -> RedirectResponse:
    """Redirect with a confirmation message, translated now into the viewer's language (catalog key "flash.<key>")."""
    sep = "&" if "?" in url else "?"
    msg = tr(f"flash.{key}", lang_of(request), **params) if key else None
    return RedirectResponse(url + (f"{sep}msg={quote(msg)}&kind={kind}" if msg else ""), status_code=303)


# ---------------------------------------------------------------- login, account, users
def _safe_next(url: str, role: str = "superadmin") -> str:
    ok = url.startswith("/") and not url.startswith("//") and not url.startswith("/login")
    return url if ok and auth.allowed(role, url.split("?")[0]) else auth.HOME[role]


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/", s: Session = Depends(db)):
    return page(request, s, "login.html", "login", title="auth.login_title", next=next, export=True, error=request.query_params.get("error"))


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("/"), s: Session = Depends(db)):
    user = auth.authenticate(s, username, password)
    if user is None:
        return RedirectResponse(f"/login?error=1&next={quote(next)}", status_code=303)
    token = auth.start_session(s, user)
    r = RedirectResponse(_safe_next(next, user.role), status_code=303)
    r.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=request.url.scheme == "https")
    return r


@app.post("/logout")
def logout(request: Request, s: Session = Depends(db)):
    auth.end_session(s, request.cookies.get(auth.COOKIE))
    r = RedirectResponse("/login", status_code=303)
    r.delete_cookie(auth.COOKIE)
    return r


@app.get("/account", response_class=HTMLResponse)
def account_page(request: Request, s: Session = Depends(db)):
    return page(request, s, "account.html", "account", title="auth.account")


@app.post("/account/password")
def account_password(request: Request, current: str = Form(...), new: str = Form(...), again: str = Form(...), s: Session = Depends(db)):
    user = s.get(User, request.state.user["id"])
    if not auth.verify_password(user.password_hash, current):
        return back(request, "/account", "pw_wrong", "warn")
    if new != again:
        return back(request, "/account", "pw_mismatch", "warn")
    if (why := auth.validate_password(new)):
        return back(request, "/account", f"pw_{why}", "warn")
    auth.set_password(s, user, new)
    token = auth.start_session(s, user)                      # the change signed everyone out: keep this one in
    r = back(request, "/account", "pw_changed")
    r.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=request.url.scheme == "https")
    return r


def _superadmin(request: Request) -> None:
    if request.state.user["role"] != "superadmin":
        raise HTTPException(403)


@app.get("/admin/users", response_class=HTMLResponse)
def users_page(request: Request, s: Session = Depends(db)):
    _superadmin(request)
    return page(request, s, "admin_users.html", "users", title="nav.users", users=list(s.scalars(select(User).order_by(User.id))), roles=auth.ROLES)


@app.post("/admin/users")
def users_add(request: Request, username: str = Form(...), display_name: str = Form(""), role: str = Form("administrator"), password: str = Form(...), s: Session = Depends(db)):
    _superadmin(request)
    name = username.strip().lower()
    if not name or role not in auth.ROLES or s.scalar(select(User.id).where(User.username == name)):
        return back(request, "/admin/users", "user_bad", "warn")
    if (why := auth.validate_password(password)):
        return back(request, "/admin/users", f"pw_{why}", "warn")
    s.add(User(username=name, display_name=display_name.strip()[:80], role=role, password_hash=auth.hash_password(password), active=True))
    return back(request, "/admin/users", "user_added")


@app.post("/admin/users/{uid}")
def users_update(request: Request, uid: int, role: str = Form(""), active: str = Form(""), password: str = Form(""), s: Session = Depends(db)):
    _superadmin(request)
    u = s.get(User, uid)
    if u is None:
        raise HTTPException(404)
    supers = s.scalars(select(User).where(User.role == "superadmin", User.active.is_(True))).all()
    new_role = role if role in auth.ROLES else u.role
    new_active = (active == "on") if active in ("on", "off") else u.active
    if u.role == "superadmin" and u.active and len(supers) == 1 and (new_role != "superadmin" or not new_active):
        return back(request, "/admin/users", "user_last_super", "warn")
    u.role, u.active = new_role, new_active
    if password:
        if (why := auth.validate_password(password)):
            return back(request, "/admin/users", f"pw_{why}", "warn")
        auth.set_password(s, u, password)
        u.must_change_password = False
    if not u.active:
        s.execute(auth.delete(auth.UserSession).where(auth.UserSession.user_id == u.id))
    return back(request, "/admin/users", "user_saved")


@app.get("/lang/{code}")
def set_language(code: str, next: str = "/"):
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    r = RedirectResponse(target, status_code=303)
    r.set_cookie(LANG_COOKIE, normalize(code), max_age=365 * 24 * 3600, samesite="lax", httponly=True)
    return r


def freshness(s: Session) -> dict:
    """How old the newest completed visit is, and whether that is too old (the same limit the data_watch alert uses)."""
    last = data_status(s)["last_visit"]
    age = (dt.date.today() - last).days if last else None
    return {"last_visit": last, "age_days": age, "stale": age is None or age > settings.data_stale_days}


def names_by_key(s: Session) -> dict[str, str]:
    return {b.key: b.name for b in s.scalars(select(Barber))}


def names(s: Session) -> dict[int, str]:
    return {b.altegio_id: b.name for b in s.scalars(select(Barber))}


# ---------------------------------------------------------------- overview
KEY_METRICS = ["util", "rph", "visits_wk", "check", "online", "addon", "conv_new90", "risk_n"]


@app.get("/", response_class=HTMLResponse)
def overview(request: Request, s: Session = Depends(db)):
    h = helpers(lang_of(request)); t = h["t"]
    m = vm.weekly_matrix(s)
    team, labels, shop = m["team"], m["labels"], m["shop"]
    last, prev = team[-1], team[-2]
    slast, sprev = shop[-1], shop[-2]
    col = lambda key, rows=team: [r[key] for r in rows]
    tr26 = lambda key, rows=team: col(key, rows)[-26:]

    def tile(metric, value, rel_pp, trend_key, ly=None, href=None, rows=None):
        d, v = rel_pp
        rows = rows or team
        note = t("overview.team_scope") if rows is team else None
        if ly is not None and ly[0]:
            lyd, _ = vm.rel_change(*ly)
            note = t("overview.vs_ly", delta=lyd) if lyd else note
        return {"label": h["mlabel"](metric), "value": value, "delta": d, "verdict": v, "vs": t("report.wr.vs_prev") if d else None, "note": note, "href": href,
                "trend": charts.spark(tr26(trend_key, rows), label=h["mlabel"](metric), fmt=lambda x: f"{x:,.0f}".replace(",", " "))}
    tiles = [
        tile("revenue", vm.money(slast["revenue"]), vm.rel_change(slast["revenue"], sprev["revenue"]), "revenue", (slast["revenue"], slast["revenue_ly"]), rows=shop),
        tile("visits", f"{slast['visits']}", vm.rel_change(slast["visits"], sprev["visits"]), "visits", (slast["visits"], slast["visits_ly"]), rows=shop),
        tile("util", vm.pct1(last["util"]), vm.pp_change(last["util"], prev["util"]), "util"),
        tile("rph", vm.money(last["rph"]), vm.rel_change(last["rph"], prev["rph"]), "rph"),
        tile("check", vm.money(slast["avg_check"]), vm.rel_change(slast["avg_check"], sprev["avg_check"]), "avg_check", rows=shop),
        tile("new_share", f"{slast['new_clients']}", (f"{slast['new_clients'] - sprev['new_clients']:+d}".replace("-", "−") if slast["new_clients"] != sprev["new_clients"] else None,
                                                     "better" if slast["new_clients"] > sprev["new_clients"] else "worse"), "new_clients",
             (slast["new_clients"], slast["new_ly"]), rows=shop),
    ]
    tiles[5]["label"] = t("overview.new_clients")

    # revenue against last year, with the context that explains the dips and jumps
    first, lastd = m["starts"][0], m["end"]
    dated = [x for x in s.scalars(select(factors.Factor).where(factors.Factor.active.is_(True), factors.Factor.recurrence == "none",
                                                               factors.Factor.date_from >= dt.date.fromisoformat(first), factors.Factor.date_from <= lastd)
                                  .order_by(factors.Factor.date_from)) if x.category not in ("observation",)]
    markers = [{"i": (x.date_from - dt.date.fromisoformat(first)).days // 7, "label": f"{x.title} ({x.date_from.strftime('%d.%m.%Y')})"} for x in dated][:8]
    k = lambda v: f"{v / 1000:.0f}k"
    revenue_chart = charts.line_chart(labels, [{"name": t("ui.this_year"), "values": col("revenue", shop), "cls": "s1"},
                                               {"name": t("ui.last_year"), "values": col("revenue_ly", shop), "cls": "ly", "style": "dash"}],
                                      title=t("overview.trend_title"), y_fmt=lambda v: vm.money(v) if v >= 1000 else f"{v:.0f}", markers=markers, table_label=t("ui.table"))

    # barbers: one row each, with the week's figures and a 26-week revenue trend
    rows = []
    for b in vm.barbers(s):
        r, p = m["barbers"][b.key][-1], m["barbers"][b.key][-2]
        rows.append({"key": b.key, "name": b.name, "tier": b.tier, "util": r["util"], "rph": r["rev_per_sched_h"], "visits": r["visits"], "check": r["avg_check"],
                     "visits_d": vm.rel_change(r["visits"], p["visits"]), "trend": charts.spark([x["revenue"] for x in m["barbers"][b.key][-26:]], cls="s1", label=b.name,
                                                                                        fmt=lambda x: f"{x:,.0f}".replace(",", " "))})
    # client health
    seg = C.Counter(st for (st,) in s.execute(select(ClientProfile.segment)))
    parts = [("active", "s1"), ("slipping", "c-lt"), ("overdue", "s2"), ("lapsed", "c-grey"), ("one_time", "c-pale"), ("switched", "s3")]
    health = charts.stack100([{"label": h["label"]("segment.", k_), "value": seg.get(k_, 0), "cls": c_} for k_, c_ in parts], title=t("overview.client_health"))
    overdue_run = analyses.latest(s, "overdue_regulars")
    # goals and calls
    board = goals.board(s)
    order = {"behind": 0, "ok": 1, "new": 2, "done": 3, "dropped": 4}
    top_goals = sorted(board, key=lambda g: (order.get(g["state"], 5), g["scope"]))[:6]
    calls = cases.case_rows(s, "open", limit=6)
    dates = vm.measurement_dates(s)
    cur = vm.values_at(s, dates[-1] if dates else None)
    review_job = next((j["last"] for j in jobs_service.list_jobs(s) if j["job"] == "weekly_review"), None)
    return page(request, s, "overview.html", "overview", title="nav.overview", tiles=tiles, week_label=f"{last['week']} · {last['start']}", revenue_chart=revenue_chart, rows=rows,
                health=health, seg=seg, overdue_run=overdue_run, top_goals=top_goals, board=board, calls=calls, bnames=names(s), cur=cur, latest=dates[-1] if dates else None,
                review_job=review_job, factors_n=len(dated), seg_asof=s.scalar(select(func.max(ClientProfile.asof))),
                scope_names={"team": t("common.team")} | names_by_key(s))


# ---------------------------------------------------------------- barber
def barber_runs(s: Session, key: str) -> dict:
    """For each analysis, the newest run that covers this barber (a barber-scoped run, or the team run), with their own figures cut out."""
    out = {}
    for name in ("weekday_pattern", "client_retention", "return_cohorts", "client_sources", "exclusive_clients", "service_mix"):
        best = None
        for sc in (key, "team"):
            r = analyses.latest(s, name, sc)
            if r and (best is None or (r.window_to, r.id) > (best.window_to, best.id)):
                best = r
        if best:
            out[name] = {"run": best, "kpis": best.result["kpis"].get(key, {}), "team": best.result["kpis"].get("team", {}),
                         "tables": {t_: [x for x in rows if x.get("scope", key) == key] for t_, rows in best.result["tables"].items()}}
    return out


@app.get("/barber/{key}", response_class=HTMLResponse)
def barber_page(request: Request, key: str, weeks: int = 26, s: Session = Depends(db)):
    b = s.scalar(select(Barber).where(Barber.key == key, Barber.active.is_(True)))
    if not b:
        raise HTTPException(404)
    weeks = weeks if weeks in (13, 26, 52) else 26
    h = helpers(lang_of(request)); t = h["t"]
    m = vm.weekly_matrix(s)
    rows = m["barbers"][key]
    sel = rows[-weeks:]
    labels = [r["week"] for r in sel]
    col = lambda k_: [r[k_] if r['days'] else None for r in sel]        # a week off is a gap, not a zero
    last, prev = rows[-1], rows[-2]
    sp = lambda k_: charts.spark([r[k_] for r in rows[-26:]], label=h["mlabel"]("revenue"), fmt=lambda x: f"{x:,.0f}".replace(",", " "))
    def tile(label, value, change, key_, note=None):
        d, v = change
        return {"label": label, "value": value, "delta": d, "verdict": v, "vs": t("report.wr.vs_prev") if d else None, "note": note, "trend": sp(key_), "href": None}
    ly = lambda a, b_: (t("overview.vs_ly", delta=vm.rel_change(a, b_)[0]) if b_ else None)
    tiles = [tile(h["mlabel"]("revenue"), vm.money(last["revenue"]), vm.rel_change(last["revenue"], prev["revenue"]), "revenue", ly(last["revenue"], last["revenue_ly"])),
             tile(h["mlabel"]("visits"), f"{last['visits']}", vm.rel_change(last["visits"], prev["visits"]), "visits", ly(last["visits"], last["visits_ly"])),
             tile(h["mlabel"]("util"), vm.pct1(last["util"]), vm.pp_change(last["util"], prev["util"]), "util"),
             tile(h["mlabel"]("rph"), vm.money(last["rev_per_sched_h"]), vm.rel_change(last["rev_per_sched_h"], prev["rev_per_sched_h"]), "rev_per_sched_h"),
             tile(h["mlabel"]("check"), vm.money(last["avg_check"]), vm.rel_change(last["avg_check"], prev["avg_check"]), "avg_check"),
             tile(t("overview.new_clients"), f"{last['new_to_shop']}", (f"{last['new_to_shop'] - prev['new_to_shop']:+d}".replace("-", "−") if last["new_to_shop"] != prev["new_to_shop"] else None,
                                                                     "better" if last["new_to_shop"] > prev["new_to_shop"] else "worse"), "new_to_shop")]
    # the goal for busy share, drawn as a line on its chart; context marks from this barber's and the shop's factors
    board = goals.board(s, key)
    util_goal = next((g for g in board if g["metric"] == "util" and g["status"] == "active"), None)
    start = dt.date.fromisoformat(sel[0]["start"])
    marks = [x for x in s.scalars(select(factors.Factor).where(factors.Factor.active.is_(True), factors.Factor.recurrence == "none", factors.Factor.date_from >= start)
                                  .order_by(factors.Factor.date_from)) if factors.applies_to(x, key) and x.category != "observation"]
    markers = [{"i": (x.date_from - start).days // 7, "label": f"{x.title} ({x.date_from.strftime('%d.%m.%Y')})"} for x in marks][:6]
    money_k = lambda v: vm.money(v) if v >= 1000 else f"{v:.0f}"
    rev_chart = charts.line_chart(labels, [{"name": t("ui.this_year"), "values": col("revenue"), "cls": "s1"}, {"name": t("ui.last_year"), "values": col("revenue_ly"), "cls": "ly", "style": "dash"}],
                                  title=t("barber.revenue_week"), y_fmt=money_k, markers=markers, table_label=t("ui.table"))
    util_chart = charts.line_chart(labels, [{"name": t("barber.busy_short"), "values": col("util"), "cls": "s4"}], title=t("barber.busy_share"), y_fmt=lambda v: f"{v:.0f}%",
                                   goal=util_goal["target"] if util_goal else None, goal_label=t("goal.target") if util_goal else "", table_label=t("ui.table"))
    clients_chart = charts.stacked_columns(labels, [{"name": t("barber.c_returning"), "values": col("returning"), "cls": "s1"}, {"name": t("barber.c_other"), "values": col("from_other"), "cls": "c-lt"},
                                                    {"name": t("barber.c_new"), "values": col("new_to_shop"), "cls": "s3"}], title=t("barber.clients_week"))
    runs = barber_runs(s, key)
    pf = lambda v: f"{v:g}%"
    viz = {}
    if "client_retention" in runs and runs["client_retention"]["kpis"].get("clients"):
        k_ = runs["client_retention"]["kpis"]
        viz["retention"] = charts.stack100([{"label": t("barber.r_stayed"), "value": k_["stayed_pct"], "cls": "s1"}, {"label": t("barber.r_switched"), "value": k_["switched_pct"], "cls": "c-lt"},
                                            {"label": t("barber.r_lost"), "value": k_["lost_pct"], "cls": "s2"}], fmt=pf, title=t("barber.retention_title"), share=False)
    if "client_sources" in runs and runs["client_sources"]["kpis"].get("clients"):
        k_ = runs["client_sources"]["kpis"]
        viz["sources"] = charts.stack100([{"label": t("barber.c_returning"), "value": k_["returning_pct"], "cls": "s1"}, {"label": t("barber.c_other"), "value": k_["from_other_pct"], "cls": "c-lt"},
                                          {"label": t("barber.c_new"), "value": k_["new_pct"], "cls": "s3"}], fmt=pf, title=t("barber.sources_title"), share=False)
    if "service_mix" in runs:
        viz["services"] = charts.rank_bars([{"label": x["service"], "value": x["share_pct"]} for x in runs["service_mix"]["tables"].get("services", [])[:8]], fmt=pf)
    risk = risk_list(s, ("overdue",), b.altegio_id, 10, include_ineligible=True)
    flist = [x for x in factors.in_force(s, start, dt.date.fromisoformat(sel[-1]["start"]) + dt.timedelta(days=6), key) if x.category != "observation"][:8]
    return page(request, s, "barber.html", key, title=b.name, b=b, weeks=weeks, tiles=tiles, viz=viz, rev_chart=rev_chart, util_chart=util_chart, clients_chart=clients_chart, runs=runs,
                goals=board, risk=risk, flist=flist, tips=playbook.listing(s, key), week_label=f"{last['week']} · {last['start']}",
                scope_names={"team": t("common.team")} | names_by_key(s))


@app.post("/barber/{key}/analyses")
def barber_refresh_analyses(request: Request, key: str, s: Session = Depends(db)):
    """Re-run the client analyses for this barber over the latest twelve complete weeks (the follow-up window for retention)."""
    m = vm.weekly_matrix(s)
    end = m["end"]; f = end - dt.timedelta(weeks=12) + dt.timedelta(days=1)
    rf, rt = analyses.followup_window(s, f, end)
    for name, (wf, wt) in {"weekday_pattern": (f, end), "client_sources": (f, end), "exclusive_clients": (f, end), "service_mix": (f, end),
                           "client_retention": (rf, rt), "return_cohorts": (rf, rt)}.items():
        analyses.run(s, name, wf, wt, scope=key, created_by="dashboard")
    return back(request, f"/barber/{key}", "analyses_refreshed")


BARBER_CLS = ("s1", "s2", "s3", "s4", "s5", "s6")


def _agg(rows: list[dict]) -> dict:
    """Totals and ratios over some weekly rows."""
    tot = {k: sum((r.get(k) or 0) for r in rows) for k in ("revenue", "visits", "sched_h", "busy_h", "days")}
    worked = sum(1 for r in rows if r.get("days"))
    return tot | {"util": round(100 * tot["busy_h"] / tot["sched_h"], 1) if tot["sched_h"] else None,
                  "rph": round(tot["revenue"] / tot["sched_h"]) if tot["sched_h"] else None,
                  "check": round(tot["revenue"] / tot["visits"]) if tot["visits"] else None,
                  "visits_pw": round(tot["visits"] / worked, 1) if worked else None}


@app.get("/team", response_class=HTMLResponse)
def team_page(request: Request, weeks: int = 8, s: Session = Depends(db)):
    weeks = weeks if weeks in (4, 8, 13, 26) else 8
    h = helpers(lang_of(request)); t = h["t"]
    m = vm.weekly_matrix(s)
    cls = {b.key: BARBER_CLS[i % 6] for i, b in enumerate(vm.barbers(s))}
    per = {b.key: _agg(m["barbers"][b.key][-weeks:]) for b in vm.barbers(s)}
    team = _agg(m["team"][-weeks:])
    link = lambda b: f"/barber/{b.key}"
    def ranks(field, fmtf):
        return charts.rank_bars([{"label": b.name, "value": per[b.key][field], "href": link(b), "cls": "s1"} for b in vm.barbers(s)], fmt=fmtf, ref=team[field],
                                ref_label=t("report.c.team"))
    money = lambda v: vm.money(v); pct = lambda v: f"{v:.0f}%"
    diffs_util = charts.diverging([{"label": b.name, "value": round(per[b.key]["util"] - team["util"], 1) if per[b.key]["util"] is not None and team["util"] else None}
                                   for b in vm.barbers(s)], fmt=lambda v: f"{v:+.1f} {t('msg.pp')}".replace("-", "−"))
    diffs_rph = charts.diverging([{"label": b.name, "value": round(100 * (per[b.key]["rph"] / team["rph"] - 1), 1) if per[b.key]["rph"] and team["rph"] else None}
                                  for b in vm.barbers(s)], fmt=lambda v: f"{v:+.1f}%".replace("-", "−"))
    # small multiples: each barber's revenue over 26 weeks on its own scale
    multiples = [{"name": b.name, "key": b.key, "cls": cls[b.key], "last": per[b.key]["revenue"],
                  "spark": charts.spark([r["revenue"] if r["days"] else None for r in m["barbers"][b.key][-26:]], w=160, h=44, cls="s1", label=b.name,
                                        fmt=lambda x: f"{x:,.0f}".replace(",", " "))} for b in vm.barbers(s)]
    # client figures from the latest team analyses
    def run_rank(name, field, fmtf, lower=False):
        r = analyses.latest(s, name, "team")
        if not r:
            return None, None
        return charts.rank_bars([{"label": b.name, "value": r.result["kpis"].get(b.key, {}).get(field), "href": link(b), "cls": "s1"} for b in vm.barbers(s)], fmt=fmtf,
                                ref=r.result["kpis"].get("team", {}).get(field), ref_label=t("report.c.team"), lower_is_better=lower), r
    pf = lambda v: f"{v:g}%"
    retention, r_run = run_rank("client_retention", "stayed_pct", pf)
    lost, _ = run_rank("client_retention", "lost_pct", pf, lower=True)
    exclusive, e_run = run_rank("exclusive_clients", "exclusive_pct", pf, lower=True)
    overdue, o_run = run_rank("overdue_regulars", "value_at_stake", money, lower=True)
    rows = [{"b": b, "cls": cls[b.key], **per[b.key]} for b in vm.barbers(s)]
    return page(request, s, "team.html", "team", title="nav.team", weeks=weeks, rank_util=ranks("util", pct), rank_rph=ranks("rph", money), rank_check=ranks("check", money),
                diffs_util=diffs_util, diffs_rph=diffs_rph, multiples=multiples, retention=retention, lost=lost, exclusive=exclusive, overdue=overdue, r_run=r_run, e_run=e_run,
                o_run=o_run, rows=rows, team=team, window=f"{m['starts'][-weeks]} – {m['end']}")


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


# ---------------------------------------------------------------- clients at risk: the case queue
TABS = ("open", "booking", "processed", "all")


@app.get("/risk", response_class=HTMLResponse)
def risk_page(request: Request, tab: str = "open", outcome: str = "", barber: str = "", segment: list[str] = Query(default=[]), show_all: bool = False,
              limit: int = 100, s: Session = Depends(db)):
    tab = tab if tab in TABS else "open"
    bid = s.scalar(select(Barber.altegio_id).where(Barber.key == barber)) if barber else None
    ctx: dict = {"tab": tab, "counts": cases.counts(s), "barber": barber, "bnames": names(s), "asof": s.scalar(select(func.max(ClientProfile.asof))),
                 "here": request.url.path + (f"?{request.url.query}" if request.url.query else ""), "today": dt.date.today(), "expire": settings.case_expire_days}
    if tab != "all":
        rows = cases.case_rows(s, tab, bid)
        if tab == "processed" and outcome:
            rows = [r for r in rows if r["outcome"] == outcome]
        return page(request, s, "risk.html", "risk", title="nav.risk", rows=rows, outcome=outcome, **ctx)
    segment = segment or ["overdue"]
    rows = risk_list(s, tuple(segment), bid, limit, include_ineligible=show_all)
    seg = C.Counter(st for (st,) in s.execute(select(ClientProfile.segment)))
    comma = lang_of(request) == "uk"
    factor = f"{settings.overdue_gap_factor:g}".replace(".", ",") if comma else f"{settings.overdue_gap_factor:g}"
    ex_gap = 40
    rules = {"min": settings.overdue_min_days, "ft": settings.first_timer_days, "factor": factor, "two": settings.two_visit_line_days, "lmin": settings.lapsed_min_days, "lmax": settings.lapsed_max_days, "lfac": f"{settings.lapsed_gap_factor:g}".replace(".", ",") if comma else f"{settings.lapsed_gap_factor:g}", "ex_gap": ex_gap,
             "ex_line": round(max(settings.overdue_min_days, settings.overdue_gap_factor * ex_gap))}
    return page(request, s, "risk.html", "risk", title="nav.risk", rows=rows, segments=SEGMENTS, chosen=segment, show_all=show_all, seg=seg, rules=rules,
                active=cases.active_cases(s, [r["client_id"] for r in rows]), **ctx)


@app.post("/risk/rebuild")
def risk_rebuild(request: Request, s: Session = Depends(db)):
    n = rebuild_profiles(s, vm.dataset(s))
    return back(request, "/risk?tab=all", "profiles_rebuilt", n=n)


@app.get("/cases/{case_id}", response_class=HTMLResponse)
def case_page(request: Request, case_id: int, s: Session = Depends(db)):
    case = s.get(RiskCase, case_id)
    if case is None:
        raise HTTPException(404)
    c, p = s.get(Client, case.client_id), s.get(ClientProfile, case.client_id)
    visits = list(s.scalars(select(Appointment).where(Appointment.client_id == case.client_id, Appointment.deleted.is_(False)).order_by(Appointment.date.desc()).limit(8)))
    others = list(s.scalars(select(RiskCase).where(RiskCase.client_id == case.client_id, RiskCase.id != case.id).order_by(RiskCase.opened.desc())))
    flag = contact.active_flags(s, [case.client_id]).get(case.client_id)
    return page(request, s, "case.html", "risk", title="case.title", case=case, c=c, p=p, visits=visits, others=others, flag=flag, bnames=names(s),
                reasons=cases.REJECT_REASONS, today=dt.date.today(), pct=settings.book_now_pct, days_left=(case.expires_on - dt.date.today()).days)


def _after_case(request: Request, s: Session, case: RiskCase, key: str, **params) -> RedirectResponse:
    """After processing, go straight to the next case in the queue (or back to the list when it is empty)."""
    nxt = cases.next_open(s, case.id)
    return back(request, f"/cases/{nxt.id}" if nxt else "/risk", key if nxt else key + "_last", **params)


def _case_or_404(s: Session, case_id: int) -> RiskCase:
    case = s.get(RiskCase, case_id)
    if case is None:
        raise HTTPException(404)
    return case


@app.post("/cases/{case_id}/booked")
def case_booked(request: Request, case_id: int, booked_for: str = Form(""), note: str = Form(""), s: Session = Depends(db)):
    case = _case_or_404(s, case_id)
    try:
        cases.record_booking(s, case, request.state.user["username"], dt.date.fromisoformat(booked_for) if booked_for else None, note.strip())
    except ValueError as e:
        return back(request, f"/cases/{case_id}", "case_bad", "warn", why=str(e))
    return _after_case(request, s, case, "case_booked")


@app.post("/cases/{case_id}/reject")
def case_reject(request: Request, case_id: int, reason: str = Form(...), comment: str = Form(""), until: str = Form(""), s: Session = Depends(db)):
    case = _case_or_404(s, case_id)
    try:
        cases.reject(s, case, request.state.user["username"], reason, comment.strip(), dt.date.fromisoformat(until) if until else None)
    except contact.CommentRequired:
        return back(request, f"/cases/{case_id}", "case_bad", "warn", why=tr("flag.comment_required", lang_of(request)))
    except ValueError as e:
        return back(request, f"/cases/{case_id}", "case_bad", "warn", why=str(e))
    return _after_case(request, s, case, "case_rejected")


@app.post("/cases/{case_id}/no-answer")
def case_no_answer(request: Request, case_id: int, note: str = Form(""), s: Session = Depends(db)):
    case = _case_or_404(s, case_id)
    try:
        cases.no_answer(s, case, request.state.user["username"], note.strip())
    except ValueError as e:
        return back(request, f"/cases/{case_id}", "case_bad", "warn", why=str(e))
    return _after_case(request, s, case, "case_no_answer")


# ---------------------------------------------------------------- client card
@app.get("/client/{cid}", response_class=HTMLResponse)
def client_page(request: Request, cid: int, s: Session = Depends(db)):
    c, p = s.get(Client, cid), s.get(ClientProfile, cid)
    visits = list(s.scalars(select(Appointment).where(Appointment.client_id == cid, Appointment.deleted.is_(False)).order_by(Appointment.date.desc()).limit(60)))
    if not (c or p or visits):
        raise HTTPException(404)
    client_cases = list(s.scalars(select(RiskCase).where(RiskCase.client_id == cid).order_by(RiskCase.opened.desc())))
    per_barber = C.Counter(dict(s.execute(select(Appointment.barber_id, func.count()).where(Appointment.client_id == cid, Appointment.status == "arrived",
                                                                                           Appointment.deleted.is_(False)).group_by(Appointment.barber_id)).all()))
    bn = names(s)
    barbers_chart = charts.stack100([{"label": bn.get(b, str(b)), "value": n, "cls": BARBER_CLS[i % 6]} for i, (b, n) in enumerate(per_barber.most_common())],
                                    fmt=lambda v: f"{v:g}", title=tr("client.barbers_title", lang_of(request))) if per_barber else None
    total_visits = sum(per_barber.values())
    flag = contact.active_flags(s, [cid]).get(cid)
    return page(request, s, "client.html", "risk", title=c.name if c and c.name else tr("client.fallback", lang_of(request), id=cid), cid=cid, c=c, p=p, visits=visits,
                client_cases=client_cases, per_barber=per_barber, bnames=bn, barbers_chart=barbers_chart, total_visits=total_visits, flag=flag, flag_history=contact.history(s, cid), flag_reasons=contact.REASONS,
                here=f"/client/{cid}", today=dt.date.today())


def _next(url: str, cid: int) -> str:
    return url if url.startswith("/") and not url.startswith("//") else f"/client/{cid}"


@app.post("/client/{cid}/flag")
def client_flag(request: Request, cid: int, reason: str = Form(...), comment: str = Form(""), until: str = Form(""),
                next_url: str = Form(""), s: Session = Depends(db)):
    """Someone who knows the client says why not to call them (abroad, mobilised, ...), optionally until a date."""
    try:
        contact.add_flag(s, cid, reason, comment, dt.date.fromisoformat(until) if until else None)
    except contact.CommentRequired:
        return back(request, _next(next_url, cid), "flag_bad", "warn", why=tr("flag.comment_required", lang_of(request)))
    except ValueError as e:
        return back(request, _next(next_url, cid), "flag_bad", "warn", why=str(e))
    return back(request, _next(next_url, cid), "flag_saved")


@app.post("/client/{cid}/flag/lift")
def client_flag_lift(request: Request, cid: int, next_url: str = Form(""), s: Session = Depends(db)):
    """Lifts whatever keeps the client off the call list: a flag, or the older permanent do-not-contact mark."""
    contact.lift_flag(s, cid)
    if (c := s.get(Client, cid)) is not None:
        c.do_not_contact = False
    return back(request, _next(next_url, cid), "flag_lifted")


# ---------------------------------------------------------------- win-back results
@app.get("/outreach", response_class=HTMLResponse)
def outreach_page(request: Request, s: Session = Depends(db)):
    allc = list(s.scalars(select(RiskCase)))
    closed = [c for c in allc if c.status == "closed"]
    worked = [c for c in closed if c.contacted]                       # an administrator processed them: the ones our work can claim
    def group(key, items):
        g = C.defaultdict(list)
        for c in items:
            g[key(c)].append(c)
        return sorted(((k, len(v), sum(1 for c in v if c.outcome == "visited"), sum(c.visit_revenue or 0 for c in v if c.outcome == "visited")) for k, v in g.items()), key=lambda r: -r[1])
    won = [c for c in worked if c.outcome == "visited"]
    return page(request, s, "outreach.html", "outreach", title="nav.outreach", total=len(allc), counts=cases.counts(s), outcomes=C.Counter(c.outcome for c in closed),
                worked=len(worked), won=len(won), won_revenue=sum(c.visit_revenue or 0 for c in won), on_own=sum(1 for c in closed if c.outcome == "visited" and not c.contacted),
                by_offer=group(lambda c: c.offer or "—", [c for c in worked if c.outcome != "expired"]), by_trigger=group(lambda c: c.trigger, closed),
                by_admin=group(lambda c: c.processed_by or "—", worked), calib=calibration.calibration(s), by_reason=C.Counter(c.reason for c in closed if c.outcome == "rejected").most_common())


# ---------------------------------------------------------------- context
@app.get("/context", response_class=HTMLResponse)
def context_page(request: Request, q: str = "", scope: str = "", category: str = "", s: Session = Depends(db)):
    found = [f for f in notes.search(s, q or None, scope or None, limit=200) if not category or f.category == category]
    return page(request, s, "context.html", "context", title="nav.context", notes=found, q=q, scope=scope, category=category, today=dt.date.today(),
                statuses={f.id: factor_link.status(s, f.id) for f in found}, effects={f.id: effects.summary(s, f) for f in found if f.recurrence == "yearly"},
                kinds=factors.KINDS, treatments=factors.TREATMENTS, categories=factors.CATEGORIES, lenses=factors.lenses(s), catalog=catalog())


@app.post("/context")
def context_add(request: Request, title: str = Form(...), date_from: str = Form(...), date_to: str = Form(""), kind: str = Form("internal"),
                category: str = Form("other"), treatment: str = Form("annotate"), recurrence: str = Form("none"), lead_days: int = Form(0),
                adjust_factor: str = Form(""), effect_metric: str = Form(""), effect_direction: str = Form(""), size_min: str = Form(""), size_max: str = Form(""),
                scopes: list[str] = Form(["shop"]), tags: str = Form(""), body: str = Form(""), s: Session = Depends(db)):
    if kind in notes.KINDS:                                  # the old note kinds still work: they become the category
        category, kind = (category if category != "other" else kind), ("external" if kind == "external" else "internal")
    effect = []
    if effect_metric and effect_direction:
        effect = [{"metric": effect_metric, "direction": effect_direction, "size_min": float(size_min) if size_min else None, "size_max": float(size_max) if size_max else None}]
    try:
        factors.add(s, title, date_from, date_to or None, kind, category, body.strip(), scopes, treatment, effect, recurrence, lead_days,
                    float(adjust_factor) if adjust_factor else None, [t.strip() for t in tags.split(",") if t.strip()], "owner")
    except ValueError as e:
        return back(request, "/context", "factor_error", "warn", why=str(e))
    return back(request, "/context", "note_added")


@app.post("/context/{nid}/delete")
def context_delete(request: Request, nid: int, s: Session = Depends(db)):
    factors.delete(s, nid)
    return back(request, "/context", "note_deleted")


@app.post("/context/{nid}/estimate")
def context_estimate(request: Request, nid: int, s: Session = Depends(db)):
    try:
        run = effects.estimate(s, nid, created_by="dashboard")
    except (ValueError, KeyError) as e:
        return back(request, "/context", "factor_error", "warn", why=str(e))
    return back(request, "/context", "effect_estimated", run=run.id)


@app.post("/context/{nid}/test")
def context_test(request: Request, nid: int, s: Session = Depends(db)):
    try:
        h = factor_link.test_belief(s, nid)
    except (ValueError, KeyError) as e:
        return back(request, "/context", "factor_error", "warn", why=str(e))
    return back(request, "/hypotheses", "belief_tested", id=h.id)


@app.post("/lenses")
def lens_add(request: Request, key: str = Form(...), label: str = Form(...), honour: list[str] = Form([]), s: Session = Depends(db)):
    try:
        factors.create_lens(s, key.strip(), label.strip(), honour)
    except ValueError as e:
        return back(request, "/context", "factor_error", "warn", why=str(e))
    return back(request, "/context", "lens_saved")


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
    return page(request, s, "data.html", "data", title="nav.data", runs=runs, months=months[-12:], older_months=months[:-12], snaps=snaps, data_asof=data_asof(s),
                suggest_from=suggest_from, suggest_to=suggest_to, fresh=freshness(s), jobs=jobs_service.list_jobs(s))


@app.post("/jobs/{key}/run")
def job_run_now(request: Request, key: str, s: Session = Depends(db)):
    """Run one scheduled job now (the same code the scheduler runs; a real run is recorded and may send a Telegram message)."""
    from ..jobs.registry import JOBS
    if key not in JOBS:
        raise HTTPException(404)
    out = jobs_service.run_now(s, key)
    return back(request, "/data", "job_ran", "warn" if out["status"] in ("failed", "blocked") else "", job=JOBS[key].label, status=out["status"])


@app.post("/data/snapshot")
def data_snapshot(request: Request, date_from: str = Form(...), date_to: str = Form(...), s: Session = Depends(db)):
    f, t = dt.date.fromisoformat(date_from), dt.date.fromisoformat(date_to)
    if (t - f).days < 13:
        return back(request, "/data", "measure_short", "warn")
    if f.weekday() != 0 or t.weekday() != 6:
        return back(request, "/data", "measure_weeks", "warn")
    run = analyses.run(s, "barber_scorecard", f, t, created_by="dashboard", ds=vm.dataset(s), label="Monthly measurement")
    return back(request, "/data", "measure_saved", date=t, n=sum(len(v) for v in run.result["kpis"].values()))


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
