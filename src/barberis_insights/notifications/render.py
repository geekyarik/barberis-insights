"""Turns a stored report (or an alert) into message text in the recipient's language. Text comes from the i18n catalogs."""
from __future__ import annotations

import datetime as dt
import html

from ..i18n import normalize, t


def num(x, lang: str, digits: int = 0) -> str:
    if x is None:
        return "—"
    s = f"{x:,.{digits}f}".replace(",", " ")
    return s.replace(".", ",") if normalize(lang) == "uk" else s.replace(" ", ",")


def delta(d, lang: str, digits: int = 0, unit: str = "") -> str:
    if d is None or round(d, digits) == 0:
        return ""
    sign = "▲" if d > 0 else "▼"
    return f" ({sign} {num(abs(d), lang, digits)}{unit})"


def _short(d: str) -> str:
    return dt.date.fromisoformat(d).strftime("%d.%m")


def weekly_review(content: dict, lang: str, client_names: dict[int, str] | None = None, catchup: list[dict] | None = None) -> str:
    """The weekly review message. `catchup` holds the contents of older weeks that were processed in the same tick."""
    lang = normalize(lang)
    names, team, vs = content["names"], content["team"], content.get("vs_prev") or {}
    d = lambda k, digits=0, unit="": delta((vs.get("team", {}).get(k) or {}).get("delta"), lang, digits, unit)
    f, to = content["window"]
    lines = [t("msg.weekly.title", lang, week=content["week"].split("-W")[1]),
             t("msg.weekly.window", lang, start=_short(f), end=_short(to), asof=_short(content["data_as_of"])), "",
             t("msg.weekly.team", lang),
             t("msg.weekly.revenue", lang, value=num(team.get("revenue"), lang), delta=d("revenue")),
             t("msg.weekly.visits", lang, value=num(team.get("visits"), lang), delta=d("visits")),
             t("msg.weekly.util", lang, value=num(team.get("util"), lang, 1), delta=d("util", 1, " " + t("msg.pp", lang))),
             t("msg.weekly.rph", lang, value=num(team.get("rph"), lang), delta=d("rph")),
             t("msg.weekly.check", lang, value=num(team.get("check"), lang), delta=d("check"))]
    ly = content.get("vs_year") or {}
    if ly.get("rph") is not None or ly.get("util") is not None:
        lines.append(t("msg.weekly.year", lang, rph=delta(ly.get("rph"), lang).strip(" ()") or "=", util=delta(ly.get("util"), lang, 1, " " + t("msg.pp", lang)).strip(" ()") or "="))
    lines += ["", t("msg.weekly.barbers", lang)]
    for key, v in content["barbers"].items():
        if not any(x is not None for x in v.values()):
            continue                                 # not working that week
        lines.append(t("msg.weekly.barber_line", lang, name=html.escape(names.get(key, key)), util=num(v.get("util"), lang, 1),
                       rph=num(v.get("rph"), lang), visits=num(v.get("visits"), lang)))
    ov = content["overdue"]
    lines += ["", t("msg.weekly.overdue", lang, n=ov["count"], value=num(ov["value"], lang))]
    if ov["top"]:
        who = ", ".join(f"{html.escape((client_names or {}).get(r['client_id']) or str(r['client_id']))} "
                        f"({html.escape(names.get(r['barber'], r['barber']))}, {r['days_silent']})" for r in ov["top"])
        lines.append(t("msg.weekly.overdue_top", lang, list=who))
    g = content["goals"]["counts"]
    other = sum(g.values()) - sum(g.get(k, 0) for k in ("on_track", "behind", "reached"))
    lines += ["", t("msg.weekly.goals", lang, on_track=g.get("on_track", 0), behind=g.get("behind", 0), reached=g.get("reached", 0))
              + (t("msg.weekly.goals_other", lang, n=other) if other else "")]
    if content["goals"]["behind"]:
        lines.append(t("msg.weekly.goals_behind", lang, list="; ".join(html.escape(x["title"]) for x in content["goals"]["behind"][:5])))
    if catchup:
        lines += ["", t("msg.weekly.catchup", lang)] + [
            t("msg.weekly.catchup_line", lang, week=c["week"].split("-W")[1], revenue=num(c["team"].get("revenue"), lang), util=num(c["team"].get("util"), lang, 1))
            for c in catchup]
    return "\n".join(lines)


def alert(code: str, lang: str, **params) -> str:
    params.setdefault("command", t("msg.refresh_command", lang))
    return t(f"msg.alert.{code}", lang, **{k: html.escape(str(v)) for k, v in params.items()})
