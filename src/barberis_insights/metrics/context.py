"""Loads appointments and schedules from the database once, and caches per-window aggregates for metrics."""
from __future__ import annotations

import collections as C
import datetime as dt
from dataclasses import dataclass, field
from functools import cached_property

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import Appointment, Barber, ScheduleSlot


@dataclass
class Appt:
    id: int
    date: dt.date
    start: int  # minutes from midnight
    barber: int
    client: int | None
    status: str
    online: bool
    duration: int
    cost: float
    titles: tuple[str, ...]


@dataclass
class Dataset:
    """Everything metrics need, loaded from the database. Excludes deleted and cancelled appointments."""
    appts: list[Appt]
    slots: dict[int, dict[dt.date, list[tuple[int, int]]]]
    barbers: list[Barber]
    _hist: dict = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, s: Session) -> "Dataset":
        rows = s.scalars(select(Appointment).where(Appointment.deleted.is_(False), Appointment.status != "cancelled")).all()
        appts = [Appt(a.id, a.date, int(a.start[:2]) * 60 + int(a.start[3:5]), a.barber_id, a.client_id, a.status, a.online,
                      a.duration_min, a.total_cost, tuple(sv.title for sv in a.services)) for a in rows]
        appts.sort(key=lambda a: (a.date, a.start))
        slots: dict[int, dict[dt.date, list]] = C.defaultdict(lambda: C.defaultdict(list))
        for sl in s.scalars(select(ScheduleSlot)):
            slots[sl.barber_id][sl.date].append((sl.start_min, sl.end_min))
        barbers = list(s.scalars(select(Barber).where(Barber.active.is_(True)).order_by(Barber.altegio_id)))
        order = {"olia": 0, "tina": 1, "yanina": 2, "solomiia": 3, "iryna": 4, "kseniia": 5}
        barbers.sort(key=lambda b: order.get(b.key, 99))
        return cls(appts, slots, barbers)

    @cached_property
    def arrived(self) -> list[Appt]:
        return [a for a in self.appts if a.status == "arrived"]

    def history_since(self, start: str) -> dict[int, list[Appt]]:
        """client -> arrived visits on or after `start`, in date order."""
        if start not in self._hist:
            d0 = dt.date.fromisoformat(start)
            h = C.defaultdict(list)
            for a in self.arrived:
                if a.client and a.date >= d0:
                    h[a.client].append(a)
            self._hist[start] = h
        return self._hist[start]

    @property
    def shop_history(self) -> dict[int, list[Appt]]:
        """Full history (from `history_start`): client profiles, segments and win-back."""
        return self.history_since(settings.history_start)

    @property
    def metrics_history(self) -> dict[int, list[Appt]]:
        """History the Goal metrics read (from `metrics_history_start`), until they get versioned definitions."""
        return self.history_since(settings.metrics_history_start)

    def visited_before(self, client: int, d: dt.date, barber: int | None = None) -> bool:
        return any(a.date < d and (barber is None or a.barber == barber) for a in self.metrics_history.get(client, ()))


def is_addon(a: Appt) -> bool:
    return any(any(k in t for k in settings.addon_keywords) for t in a.titles)


def busy_minutes(appts: list[Appt], sched: dict[dt.date, list[tuple[int, int]]]) -> int:
    tot = 0
    for a in appts:
        e = a.start + a.duration
        tot += sum(max(0, min(e, b) - max(a.start, x)) for x, b in sched.get(a.date, ()))
    return tot


@dataclass
class Scope:
    key: str  # barber key or "team"
    barber_id: int | None = None  # None for team


@dataclass
class WindowContext:
    ds: Dataset
    f: dt.date
    t: dt.date
    cohort: tuple[dt.date, dt.date] | None = None
    _cache: dict = field(default_factory=dict)

    @property
    def length(self) -> int:
        return (self.t - self.f).days + 1

    @property
    def cohort_window(self) -> tuple[dt.date, dt.date]:
        """First visits in the 90+ days ending 90 days before the window end."""
        if self.cohort:
            return self.cohort
        to = self.t - dt.timedelta(days=90)
        return to - dt.timedelta(days=max(self.length, 90) - 1), to

    @property
    def asof(self) -> dt.date:
        return self.t + dt.timedelta(days=1)

    def _memo(self, key, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    def sched(self, barber: int) -> dict[dt.date, list[tuple[int, int]]]:
        return self._memo(("sched", barber), lambda: {d: v for d, v in self.ds.slots.get(barber, {}).items() if self.f <= d <= self.t and v})

    def appts(self, barber: int | None) -> list[Appt]:
        return self._memo(("appts", barber), lambda: [a for a in self.ds.appts if self.f <= a.date <= self.t and (barber is None or a.barber == barber)])

    def visits(self, barber: int | None) -> list[Appt]:
        return self._memo(("visits", barber), lambda: [a for a in self.appts(barber) if a.status == "arrived"])

    def team_barbers(self) -> list[int]:
        return [b.altegio_id for b in self.ds.barbers]

    def sched_minutes(self, barber: int) -> int:
        return sum(e - s for v in self.sched(barber).values() for s, e in v)

    def busy(self, barber: int) -> int:
        return self._memo(("busy", barber), lambda: busy_minutes(self.appts(barber), self.sched(barber)))

    def barber_dates(self, barber: int) -> dict[int, list[dt.date]]:
        """client -> dates of arrived visits to this barber since metrics_history_start (all time, not just the window)."""
        def build():
            m = C.defaultdict(list)
            for c, vs in self.ds.metrics_history.items():
                for a in vs:
                    if a.barber == barber:
                        m[c].append(a.date)
            return m
        return self._memo(("bdates", barber), build)
