"""How likely a silent client is to come back on their own, learned from the shop's own history.

For every client, every visit and every silence length (every 14 days up to a year) we record whether the next visit came within 90 days.
That gives P(return within 90 days | visits so far, days silent) as a small table of counts. It is the chance without any contact, and it
is recomputed whenever the client profiles are rebuilt, so it follows the shop and needs no hand-picked weights (docs/CASES.md).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

HORIZON = 90
STEP = 14
VISITS = (1, 2, 3, 4, 6, 11)                       # bucket lower bounds: 1, 2, 3, 4-5, 6-10, 11+
SILENCE = (0, 30, 45, 75, 105, 180, 270)           # bucket lower bounds in days
MIN_N = 30                                         # a cell with fewer observations borrows from its silence bucket
DEFAULT = 0.10


def _bucket(x: float, bounds: tuple[int, ...]) -> int:
    b = 0
    for i, lo in enumerate(bounds):
        if x >= lo:
            b = i
    return b


@dataclass
class ReturnModel:
    cells: dict = field(default_factory=dict)       # (visit bucket, silence bucket) -> [observations, returns]
    by_silence: dict = field(default_factory=dict)  # silence bucket -> [observations, returns]

    def chance(self, visits: int, days_silent: float) -> float:
        v, d = _bucket(visits, VISITS), _bucket(days_silent, SILENCE)
        n, k = self.cells.get((v, d), (0, 0))
        if n >= MIN_N:
            return k / n
        n2, k2 = self.by_silence.get(d, (0, 0))
        return k2 / n2 if n2 >= MIN_N else DEFAULT

    def table(self) -> list[dict]:
        """For display: the chance by visits so far and days silent."""
        return [{"visits": VISITS[v], "silence": SILENCE[d], "n": n, "chance": (k / n if n else None)} for (v, d), (n, k) in sorted(self.cells.items())]


def fit(histories: dict[int, list[dt.date]], asof: dt.date) -> ReturnModel:
    """`histories`: each client's distinct visit dates, oldest first, up to `asof`."""
    cells: dict = {}
    by_silence: dict = {}
    horizon = dt.timedelta(days=HORIZON)
    for days in histories.values():
        for i, last in enumerate(days):
            nxt = days[i + 1] if i + 1 < len(days) else None
            v = _bucket(i + 1, VISITS)
            d = STEP
            while True:
                t = last + dt.timedelta(days=d)
                if t > asof - horizon or (nxt and nxt <= t):
                    break
                came = bool(nxt and nxt <= t + horizon)
                sb = _bucket(d, SILENCE)
                c = cells.setdefault((v, sb), [0, 0]); c[0] += 1; c[1] += came
                s = by_silence.setdefault(sb, [0, 0]); s[0] += 1; s[1] += came
                d += STEP
                if d > 365:
                    break
    return ReturnModel(cells, by_silence)
