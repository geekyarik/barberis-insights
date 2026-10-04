"""Ukraine's public holidays as recurring factors, from Labour Code art. 73 as it stands since Law 3258-IX of 14.07.2023
(docs/research/external-factor-feeds.md has the sources). Since 24.03.2022 martial law suspends art. 73, so these are not statutory days
off; they are dates when clients behave differently, which is exactly what the shop's own history can measure.

Easter and Trinity move every year and are left out. The run-up (`lead_days`) is a modelling choice, not a legal fact; the measured
effect, not the length, is what the owner should read. No belief is attached: that is for the owner to add.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Factor
from . import factors

SOURCE = "research:holidays"
REFERENCE_YEAR = 2026
# (title, month, day, run-up days before the date)
HOLIDAYS = [
    ("New Year", 1, 1, 8),
    ("International Women's Day", 3, 8, 3),
    ("Labour Day", 5, 1, 2),
    ("Day of Remembrance and Victory over Nazism", 5, 8, 2),
    ("Constitution Day", 6, 28, 2),
    ("Statehood Day", 7, 15, 2),
    ("Independence Day", 8, 24, 2),
    ("Defenders Day", 10, 1, 2),
    ("Christmas", 12, 25, 0),
]


def seed(s: Session) -> int:
    """Add the holidays that are not there yet (matched by source and title). Returns how many were added."""
    have = {f.title for f in s.scalars(select(Factor).where(Factor.source == SOURCE))}
    n = 0
    for title, month, day, lead in HOLIDAYS:
        if title in have:
            continue
        factors.add(s, title, dt.date(REFERENCE_YEAR, month, day), kind="external", category="holiday", scopes=["shop"], recurrence="yearly", lead_days=lead,
                    body="Public holiday, Labour Code art. 73 (not a statutory day off during martial law). The run-up length is a modelling choice.",
                    source=SOURCE, tags=["holiday"])
        n += 1
    return n
