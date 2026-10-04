"""Weekly rows per barber (charts and ledger), ported from the original analysis (legacy/analyze.py)."""
from __future__ import annotations

import collections as C
import datetime as dt

from .context import Dataset, busy_minutes, is_addon


def iso_monday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def weekly_rows(ds: Dataset, barber: int, start: dt.date, end: dt.date, full: bool = False) -> list[dict]:
    """One row per ISO week from start's Monday to end; 2025 comparison by ISO week number."""
    mine = [a for a in ds.appts if a.barber == barber]
    by_week = C.defaultdict(list)
    for a in mine:
        by_week[a.date.isocalendar()[:2]].append(a)
    sched = ds.slots.get(barber, {})
    rows = []
    w0 = iso_monday(start)
    while w0 <= end:
        w1 = w0 + dt.timedelta(days=6)
        y, wk, _ = w0.isocalendar()
        wa = by_week.get((y, wk), [])
        visits = [a for a in wa if a.status == "arrived"]
        days = {d: v for d, v in sched.items() if w0 <= d <= w1 and v}
        smin = sum(e - s for v in days.values() for s, e in v)
        bmin = busy_minutes(wa, days)
        rev = sum(a.cost for a in visits)
        clients = {a.client for a in visits if a.client}
        new_shop = sum(1 for c in clients if not ds.visited_before(c, w0, full=full))
        from_other = sum(1 for c in clients if ds.visited_before(c, w0, full=full) and not ds.visited_before(c, w0, barber, full=full))
        try:
            ly = [a for a in by_week.get((y - 1, wk), []) if a.status == "arrived"]
        except ValueError:
            ly = []
        rows.append({"week": f"W{wk:02d}", "year": y, "start": str(w0), "days": len(days), "sched_h": round(smin / 60, 1), "busy_h": round(bmin / 60, 1),
                     "util": round(100 * bmin / smin, 1) if smin else None, "visits": len(visits),
                     "no_show": sum(1 for a in wa if a.status == "no_show"), "revenue": round(rev),
                     "avg_check": round(rev / len(visits)) if visits else None, "rev_per_sched_h": round(rev / (smin / 60)) if smin else None,
                     "clients": len(clients), "new_to_shop": new_shop, "from_other": from_other, "returning": max(0, len(clients) - new_shop - from_other),
                     "online_pct": round(100 * sum(a.online for a in visits) / len(visits)) if visits else None,
                     "addon_pct": round(100 * sum(1 for a in visits if is_addon(a)) / len(visits)) if visits else None,
                     "visits_ly": len(ly), "revenue_ly": round(sum(a.cost for a in ly))})
        w0 += dt.timedelta(weeks=1)
    return rows
