"""Local dashboard (server-rendered pages + JSON API). Run with `insights serve`; binds to 127.0.0.1 only."""
from __future__ import annotations

import collections as C
import datetime as dt
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
from ..clients.risk import CALLABLE, risk_list
from ..config import settings
from ..clients.names import names_for
from ..context import factors, service as notes
from ..db.models import Appointment, Barber, Client, ClientProfile, Hypothesis, Measurement, OutreachCase, SyncRun
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
from ..outreach import service as outreach
from ..outreach.offers import active_offers
from ..playbook import service as playbook
from ..reports import service as reports
from . import charts, data as vm
from .report_views import VIEWS

HERE = Path(__file__).parent
app = FastAPI(title="BARBERIS insights", docs_url="/api/docs", openapi_url="/api/openapi.json")
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
    return templates.TemplateResponse(request, name, {"nav": nav, "all_barbers": vm.barbers(s), "fresh": freshness(s), "flash": request.query_params.get("msg"),
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
    parts = [("active", "s3"), ("slipping", "warn-seg"), ("overdue", "s2"), ("lapsed", "muted-seg"), ("one_time", "s5"), ("switched", "s4")]
    health = charts.stack100([{"label": h["label"]("segment.", k_), "value": seg.get(k_, 0), "cls": c_} for k_, c_ in parts], title=t("overview.client_health"))
    overdue_run = analyses.latest(s, "overdue_regulars")
    # goals and calls
    board = goals.board(s)
    order = {"behind": 0, "ok": 1, "new": 2, "done": 3, "dropped": 4}
    top_goals = sorted(board, key=lambda g: (order.get(g["state"], 5), g["scope"]))[:6]
    calls = risk_list(s, ("overdue",), None, 5, include_ineligible=False)
    dates = vm.measurement_dates(s)
    cur = vm.values_at(s, dates[-1] if dates else None)
    review = next(iter(reports.list_reports(s, "weekly_review", 1)), None)
    review_job = next((j["last"] for j in jobs_service.list_jobs(s) if j["job"] == "weekly_review"), None)
    return page(request, s, "overview.html", "overview", title="nav.overview", tiles=tiles, week_label=f"{last['week']} · {last['start']}", revenue_chart=revenue_chart, rows=rows,
                health=health, seg=seg, overdue_run=overdue_run, top_goals=top_goals, board=board, calls=calls, bnames=names(s), cur=cur, latest=dates[-1] if dates else None,
                review=review, review_job=review_job, factors_n=len(dated), seg_asof=s.scalar(select(func.max(ClientProfile.asof))),
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
    util_chart = charts.line_chart(labels, [{"name": t("barber.busy_short"), "values": col("util"), "cls": "s3"}], title=t("barber.busy_share"), y_fmt=lambda v: f"{v:.0f}%",
                                   goal=util_goal["target"] if util_goal else None, goal_label=t("goal.target") if util_goal else "", table_label=t("ui.table"))
    clients_chart = charts.stacked_columns(labels, [{"name": t("barber.c_returning"), "values": col("returning"), "cls": "s1"}, {"name": t("barber.c_other"), "values": col("from_other"), "cls": "s5"},
                                                    {"name": t("barber.c_new"), "values": col("new_to_shop"), "cls": "s2"}], title=t("barber.clients_week"))
    runs = barber_runs(s, key)
    pf = lambda v: f"{v:g}%"
    viz = {}
    if "client_retention" in runs and runs["client_retention"]["kpis"].get("clients"):
        k_ = runs["client_retention"]["kpis"]
        viz["retention"] = charts.stack100([{"label": t("barber.r_stayed"), "value": k_["stayed_pct"], "cls": "s3"}, {"label": t("barber.r_switched"), "value": k_["switched_pct"], "cls": "warn-seg"},
                                            {"label": t("barber.r_lost"), "value": k_["lost_pct"], "cls": "s2"}], fmt=pf, title=t("barber.retention_title"), share=False)
    if "client_sources" in runs and runs["client_sources"]["kpis"].get("clients"):
        k_ = runs["client_sources"]["kpis"]
        viz["sources"] = charts.stack100([{"label": t("barber.c_returning"), "value": k_["returning_pct"], "cls": "s1"}, {"label": t("barber.c_other"), "value": k_["from_other_pct"], "cls": "s5"},
                                          {"label": t("barber.c_new"), "value": k_["new_pct"], "cls": "s2"}], fmt=pf, title=t("barber.sources_title"), share=False)
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
    rf, rt = reports.followup_window(s, f, end)
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
        return charts.rank_bars([{"label": b.name, "value": per[b.key][field], "href": link(b), "cls": cls[b.key]} for b in vm.barbers(s)], fmt=fmtf, ref=team[field],
                                ref_label=t("report.c.team"))
    money = lambda v: vm.money(v); pct = lambda v: f"{v:.0f}%"
    diffs_util = charts.diverging([{"label": b.name, "value": round(per[b.key]["util"] - team["util"], 1) if per[b.key]["util"] is not None and team["util"] else None}
                                   for b in vm.barbers(s)], fmt=lambda v: f"{v:+.1f} {t('msg.pp')}".replace("-", "−"))
    diffs_rph = charts.diverging([{"label": b.name, "value": round(100 * (per[b.key]["rph"] / team["rph"] - 1), 1) if per[b.key]["rph"] and team["rph"] else None}
                                  for b in vm.barbers(s)], fmt=lambda v: f"{v:+.1f}%".replace("-", "−"))
    # small multiples: each barber's revenue over 26 weeks on its own scale
    multiples = [{"name": b.name, "key": b.key, "cls": cls[b.key], "last": per[b.key]["revenue"],
                  "spark": charts.spark([r["revenue"] if r["days"] else None for r in m["barbers"][b.key][-26:]], w=160, h=44, cls=cls[b.key], label=b.name,
                                        fmt=lambda x: f"{x:,.0f}".replace(",", " "))} for b in vm.barbers(s)]
    # client figures from the latest team analyses
    def run_rank(name, field, fmtf, lower=False):
        r = analyses.latest(s, name, "team")
        if not r:
            return None, None
        return charts.rank_bars([{"label": b.name, "value": r.result["kpis"].get(b.key, {}).get(field), "href": link(b), "cls": cls[b.key]} for b in vm.barbers(s)], fmt=fmtf,
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


EXPLORE = {   # metric -> (field, where it comes from, label key, kind)
    "revenue": ("revenue", "shop", "metric.revenue", "money"), "visits": ("visits", "shop", "metric.visits", "int"), "check": ("avg_check", "shop", "metric.check", "money"),
    "new_clients": ("new_clients", "shop", "overview.new_clients", "int"), "util": ("util", "team", "metric.util", "pct"), "rph": ("rph", "team", "metric.rph", "money"),
}


@app.get("/explore", response_class=HTMLResponse)
def explore_page(request: Request, metric: str = "revenue", who: list[str] = Query(default=[]), weeks: int = 26, ly: int = 1, s: Session = Depends(db)):
    metric = metric if metric in EXPLORE else "revenue"
    weeks = weeks if weeks in (13, 26, 52) else 26
    h = helpers(lang_of(request)); t = h["t"]
    m = vm.weekly_matrix(s)
    field, src, label_key, kind = EXPLORE[metric]
    bar = vm.barbers(s)
    bfield = {"avg_check": "avg_check", "new_clients": "new_to_shop", "rph": "rev_per_sched_h"}.get(field, field)
    sel = [k_ for k_ in who if k_ in {b.key for b in bar}] if who else []
    labels = m["labels"][-weeks:]
    series, table_cols = [], []
    fmtf = {"money": lambda v: vm.money(v), "int": lambda v: f"{v:g}", "pct": lambda v: f"{v:.0f}%"}[kind]
    if not sel or src == "shop" and not sel:
        rows = m["shop"] if src == "shop" else m["team"]
        series.append({"name": t("explore.shop") if src == "shop" else t("overview.team_scope"), "values": [r[field] for r in rows[-weeks:]], "cls": "s1"})
        if ly and field in ("revenue", "visits", "new_clients") and src == "shop":
            lyf = {"revenue": "revenue_ly", "visits": "visits_ly", "new_clients": "new_ly"}[field]
            series.append({"name": t("ui.last_year"), "values": [r[lyf] for r in rows[-weeks:]], "cls": "ly", "style": "dash"})
    for i, b in enumerate(bar):
        if b.key in sel:
            rws = m["barbers"][b.key][-weeks:]
            series.append({"name": b.name, "values": [r[bfield] if r["days"] else None for r in rws], "cls": BARBER_CLS[i % 6]})
    chart = charts.line_chart(labels, series, title=t(label_key), y_fmt=fmtf, table_label=t("ui.table"))
    summary = [{"name": s_["name"], "last": next((v for v in reversed(s_["values"]) if v is not None), None),
                "avg": (sum(v for v in s_["values"] if v is not None) / max(1, sum(1 for v in s_["values"] if v is not None))) if any(v is not None for v in s_["values"]) else None}
               for s_ in series]
    return page(request, s, "explore.html", "explore", title="nav.explore", metric=metric, metrics=list(EXPLORE), sel=sel, weeks=weeks, ly=ly, chart=chart, summary=summary,
                fmtf=fmtf, label_key=label_key, src=src, EXPLORE=EXPLORE, all_barbers=bar)


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


# ---------------------------------------------------------------- reports
def _report_names(s: Session, r) -> dict:
    ids = [x["client_id"] for x in r.content.get("overdue", {}).get("top", [])] if r.report_key == "weekly_review" else []
    return names_for(s, ids)


@app.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request, s: Session = Depends(db)):
    today = dt.date.today()
    end = today - dt.timedelta(days=today.weekday() + 1)           # the last Sunday
    return page(request, s, "reports.html", "reports", title="nav.reports", reports=reports.list_reports(s, limit=50),
                kinds=("barber_book", "team_comparison", "weekly_review"), suggest_to=end, suggest_from=end - dt.timedelta(weeks=8) + dt.timedelta(days=1))


@app.post("/reports/build")
def reports_build(request: Request, kind: str = Form(...), barber: str = Form(""), date_from: str = Form(...), date_to: str = Form(...),
                  s: Session = Depends(db)):
    f, t = dt.date.fromisoformat(date_from), dt.date.fromisoformat(date_to)
    if f.weekday() != 0 or t.weekday() != 6 or t < f:
        return back(request, "/reports", "report_bad_window", "warn")
    try:
        r = reports.barber_book(s, barber, f, t) if kind == "barber_book" else reports.team_comparison(s, f, t)
    except (ValueError, KeyError) as e:
        return back(request, "/reports", "report_unknown", "warn", why=str(e))
    return RedirectResponse(f"/reports/{r.id}", status_code=303)


def _report_page(request: Request, s: Session, rid: int, export: bool):
    r = reports.get(s, rid)
    if r is None or r.report_key not in VIEWS:
        raise HTTPException(404)
    c = r.content
    return page(request, s, "report.html", "reports", title=f"report.kind.{r.report_key}", r=r, c=c, names=c.get("names", {}), vm=VIEWS[r.report_key](c), export=export, client_names=_report_names(s, r))


@app.get("/reports/{rid}", response_class=HTMLResponse)
def report_view(request: Request, rid: int, s: Session = Depends(db)):
    return _report_page(request, s, rid, False)


@app.get("/reports/{rid}/export")
def report_export(request: Request, rid: int, s: Session = Depends(db)):
    """The same report as one HTML file (no navigation, no scripts) to save or send."""
    resp = _report_page(request, s, rid, True)
    resp.headers["Content-Disposition"] = f'attachment; filename="barberis-report-{rid}.html"'
    return resp


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
