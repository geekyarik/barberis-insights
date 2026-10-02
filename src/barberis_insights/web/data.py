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

_lock = threading.Lock()
_cache: dict = {}


def dataset(s: Session) -> Dataset:
    """Reload only when appointments or schedules changed."""
    key = (s.scalar(select(func.count(Appointment.id))), s.scalar(select(func.max(Appointment.fetched_at))),
           s.scalar(select(func.count(ScheduleSlot.id))))
    with _lock:
        if _cache.get("key") != key:
            _cache["ds"] = Dataset.load(s); _cache["key"] = key
        return _cache["ds"]


def barbers(s: Session) -> list[Barber]:
    order = {"olia": 0, "tina": 1, "yanina": 2, "solomiia": 3, "iryna": 4, "kseniia": 5}
    return sorted(s.scalars(select(Barber).where(Barber.active.is_(True))), key=lambda b: order.get(b.key, 99))


def measurement_dates(s: Session) -> list[dt.date]:
    return [d for (d,) in s.execute(select(Measurement.asof).distinct().order_by(Measurement.asof))]


def values_at(s: Session, asof: dt.date | None) -> dict[str, dict[str, float]]:
    out: dict = C.defaultdict(dict)
    if asof:
        for m in s.scalars(select(Measurement).where(Measurement.asof == asof)):
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


def delta_class(metric: str, now, before) -> str:
    if now is None or before is None or now == before:
        return ""
    better = (now > before) == (REGISTRY.get(metric).direction == "up" if metric in REGISTRY else True)
    return "up" if better else "down"
