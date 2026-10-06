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
    ("Новий рік", 1, 1, 8),
    ("Міжнародний жіночий день", 3, 8, 3),
    ("День праці", 5, 1, 2),
    ("День памʼяті та перемоги над нацизмом", 5, 8, 2),
    ("День Конституції України", 6, 28, 2),
    ("День Української Державності", 7, 15, 2),
    ("День Незалежності України", 8, 24, 2),
    ("День захисників і захисниць України", 10, 1, 2),
    ("Різдво Христове", 12, 25, 0),
]
BODY = "Державне свято (Кодекс законів про працю, ст. 73). У воєнний стан не є вихідним днем. Довжина «розгону» перед датою — припущення моделі."
_ENGLISH = {"New Year": "Новий рік", "International Women's Day": "Міжнародний жіночий день", "Labour Day": "День праці",
            "Day of Remembrance and Victory over Nazism": "День памʼяті та перемоги над нацизмом", "Constitution Day": "День Конституції України",
            "Statehood Day": "День Української Державності", "Independence Day": "День Незалежності України",
            "Defenders Day": "День захисників і захисниць України", "Christmas": "Різдво Христове"}


def seed(s: Session) -> int:
    """Add the holidays that are not there yet (matched by source and title). Returns how many were added."""
    for f in s.scalars(select(Factor).where(Factor.source == SOURCE)):     # the first seed used English titles
        if f.title in _ENGLISH:
            factors.update(s, f.id, source="seed", title=_ENGLISH[f.title], body=BODY)
    have = {f.title for f in s.scalars(select(Factor).where(Factor.source == SOURCE))}
    n = 0
    for title, month, day, lead in HOLIDAYS:
        if title in have:
            continue
        factors.add(s, title, dt.date(REFERENCE_YEAR, month, day), kind="external", category="holiday", scopes=["shop"], recurrence="yearly", lead_days=lead,
                    body=BODY, source=SOURCE, tags=["свято"])
        n += 1
    return n
