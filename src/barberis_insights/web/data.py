"""View-model helpers shared by pages and the API (cached dataset, latest measurements, labels)."""
from __future__ import annotations

import collections as C
import datetime as dt
import threading

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import Appointment, Barber, Measurement, ScheduleSlot
from ..metrics import Dataset
from ..metrics.registry import REGISTRY

_lock = threading.RLock()
_cache: dict = {}
_derived: dict = {}


def dataset(s: Session) -> Dataset:
    """Reload only when appointments or schedules changed."""
    key = (s.scalar(select(func.count(Appointment.id))), s.scalar(select(func.max(Appointment.fetched_at))),
           s.scalar(select(func.count(ScheduleSlot.id))))
    with _lock:
        if _cache.get("key") != key:
            _cache["ds"] = Dataset.load(s); _cache["key"] = key
            _derived.clear()
        return _cache["ds"]


def derived(s: Session, name, fn):
    """Compute something from the dataset once per dataset version (a year of weekly rows is not cheap)."""
    dataset(s)
    with _lock:
        if (_cache["key"], name) not in _derived:
            _derived[(_cache["key"], name)] = fn()
        return _derived[(_cache["key"], name)]


def barbers(s: Session) -> list[Barber]:
    order = {"olia": 0, "tina": 1, "yanina": 2, "solomiia": 3, "iryna": 4, "kseniia": 5}
    return sorted(s.scalars(select(Barber).where(Barber.active.is_(True))), key=lambda b: order.get(b.key, 99))


def measurement_dates(s: Session) -> list[dt.date]:
    return [d for (d,) in s.execute(select(Measurement.asof).distinct().order_by(Measurement.asof))]


def values_at(s: Session, asof: dt.date | None) -> dict[str, dict[str, float]]:
    out: dict = C.defaultdict(dict)
    if asof:
        for m in s.scalars(select(Measurement).where(Measurement.asof == asof).order_by(Measurement.metric_version)):  # newest definition wins
            out[m.scope][m.metric] = m.value
    return out


def fmt(metric: str, v) -> str:
    if v is None:
        return "—"
    unit = REGISTRY[metric].unit if metric in REGISTRY else ""
    if unit == "₴":
        return f"₴{v:,.0f}".replace(",", " ")
    if unit == "%":
        return f"{v:.0f}%" if abs(v) >= 10 else f"{v:.1f}%"
    return f"{v:g}"


MONEY = {"value_at_stake", "exclusive_revenue", "revenue", "spend", "lifetime_spend", "avg_price", "avg_check", "rev_per_sched_h", "revenue_ly"}


def kfmt(key: str, v) -> str:
    """Format any analysis figure by its key: percentages, money, counts."""
    if v is None:
        return "—"
    if key.endswith("_pct") or key.startswith("util"):
        return f"{v:g}%"
    if key in MONEY:
        return f"{v:,.0f} ₴".replace(",", " ")
    return (f"{v:,.1f}" if isinstance(v, float) else f"{v:,}").replace(",", " ")


def signed(v, digits: int = 1) -> str:
    return "" if v is None or round(v, digits) == 0 else f"{v:+,.{digits}f}".replace(",", " ")


def delta_class(metric: str, now, before) -> str:
    if now is None or before is None or now == before:
        return ""
    better = (now > before) == (REGISTRY.get(metric).direction == "up" if metric in REGISTRY else True)
    return "up" if better else "down"


# ------------------------------------------------------------------ weekly figures for the overview and the barber pages
SUMS = ("days", "sched_h", "busy_h", "visits", "no_show", "revenue", "visits_ly", "revenue_ly", "clients", "new_to_shop", "from_other", "returning")


def last_complete_week_end(ds: Dataset) -> dt.date:
    """The Sunday that ended the latest ISO week that is fully inside the data."""
    last = ds.arrived[-1].date if ds.arrived else dt.date.today()
    return last if last.weekday() == 6 else last - dt.timedelta(days=last.weekday() + 1)


def weekly_matrix(s: Session, weeks: int = 53) -> dict:
    """Per-barber weekly rows and their team total for the last `weeks` complete weeks (barbers currently employed only)."""
    from ..metrics.weekly import weekly_rows

    def build():
        ds = dataset(s)
        end = last_complete_week_end(ds)
        start = end - dt.timedelta(weeks=weeks) + dt.timedelta(days=1)
        per = {b.key: weekly_rows(ds, b.altegio_id, start, end, full=True) for b in ds.barbers}
        n = len(next(iter(per.values()))) if per else 0
        team = []
        for i in range(n):
            tot = {k: sum((rows[i].get(k) or 0) for rows in per.values()) for k in SUMS}
            first = next(iter(per.values()))[i]
            tot |= {"week": first["week"], "year": first["year"], "start": first["start"]}
            tot["util"] = round(100 * tot["busy_h"] / tot["sched_h"], 1) if tot["sched_h"] else None
            tot["rph"] = round(tot["revenue"] / tot["sched_h"]) if tot["sched_h"] else None
            tot["avg_check"] = round(tot["revenue"] / tot["visits"]) if tot["visits"] else None
            team.append(tot)
        # the shop: everyone who worked, whether or not they still do (a business trend must not lose the barbers who left)
        agg: dict = C.defaultdict(lambda: [0, 0.0])
        for a in ds.arrived:
            k = a.date.isocalendar()[:2]
            agg[k][0] += 1; agg[k][1] += a.cost
        newc = C.Counter(vs[0].date.isocalendar()[:2] for vs in ds.shop_history.values())
        shop = []
        for r in team:
            y, w = r["year"], int(r["week"][1:])
            now, ly = agg.get((y, w), [0, 0.0]), agg.get((y - 1, w))
            shop.append({"week": r["week"], "start": r["start"], "visits": now[0], "revenue": round(now[1]), "avg_check": round(now[1] / now[0]) if now[0] else None,
                         "new_clients": newc.get((y, w), 0), "visits_ly": ly[0] if ly else None, "revenue_ly": round(ly[1]) if ly else None,
                         "new_ly": newc.get((y - 1, w)) if ly else None})
        return {"end": end, "labels": [r["week"] for r in team], "starts": [r["start"] for r in team], "team": team, "shop": shop, "barbers": per,
                "names": {b.key: b.name for b in ds.barbers}}
    return derived(s, ("weekly", weeks), build)


def money(v) -> str:
    return "—" if v is None else f"₴{v:,.0f}".replace(",", " ")


def pct1(v) -> str:
    return "—" if v is None else (f"{v:.0f}%" if abs(v) >= 10 else f"{v:.1f}%")


def rel_change(now, before):
    """Relative change as ("+4.7%", verdict) or (None, None) when there is nothing to compare."""
    if now is None or not before:
        return None, None
    d = 100 * (now / before - 1)
    return (f"{d:+.1f}%".replace("-", "−"), "same" if abs(d) < 0.05 else "better" if d > 0 else "worse")


def pp_change(now, before):
    """Change in percentage points as ("+0.5 пп", verdict)."""
    if now is None or before is None:
        return None, None
    d = now - before
    return (f"{d:+.1f}".replace("-", "−"), "same" if abs(d) < 0.05 else "better" if d > 0 else "worse")
