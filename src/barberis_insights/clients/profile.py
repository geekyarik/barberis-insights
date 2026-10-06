"""Per-client facts derived from visit history (shop level), rebuilt on every ingest."""
from __future__ import annotations

import collections as C
import datetime as dt
import statistics as st
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db.models import Appointment, ClientProfile
from ..metrics.context import Dataset


@dataclass
class Facts:
    client: int
    first: dt.date
    last: dt.date
    visits: int
    spend: float
    usual_barber: int
    last_barber: int
    median_gap: float | None
    days_since: int


def data_asof(s: Session) -> dt.date:
    """The day after the latest completed visit in the data: profiles measure silence up to here, not up to today."""
    last = s.scalar(select(func.max(Appointment.date)).where(Appointment.status == "arrived", Appointment.deleted.is_(False)))
    return (last or dt.date.today()) + dt.timedelta(days=1)


def build_facts(ds: Dataset, asof: dt.date) -> dict[int, Facts]:
    out = {}
    for c, vs in ds.shop_history.items():
        vs = [a for a in vs if a.date < asof]
        if not vs:
            continue
        days = sorted({a.date for a in vs})
        gaps = [(y - x).days for x, y in zip(days, days[1:]) if (y - x).days > 3]
        per_barber = C.Counter(a.barber for a in vs)
        out[c] = Facts(c, days[0], days[-1], len(days), sum(a.cost for a in vs), per_barber.most_common(1)[0][0], vs[-1].barber,
                       st.median(gaps) if len(days) >= 3 and gaps else None, (asof - days[-1]).days)
    return out


def rebuild_profiles(s: Session, ds: Dataset, asof: dt.date | None = None) -> int:
    from . import return_model
    from .risk import classify  # local import avoids a cycle
    asof = asof or data_asof(s)
    facts = build_facts(ds, asof)
    model = return_model.fit({c: sorted({a.date for a in vs if a.date < asof}) for c, vs in ds.shop_history.items()}, asof)
    s.execute(delete(ClientProfile))
    for f in facts.values():
        seg, prio, chance, offer = classify(f, model)
        s.add(ClientProfile(client_id=f.client, asof=asof, first_visit=f.first, last_visit=f.last, visits=f.visits,
                            lifetime_spend=round(f.spend, 2), usual_barber=f.usual_barber, last_barber=f.last_barber,
                            median_gap_days=f.median_gap, days_since_last=f.days_since, segment=seg, priority=prio, return_chance=chance, suggested_offer=offer))
    return len(facts)
