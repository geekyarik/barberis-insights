"""Shared builders for the per-metric tests in tests/metrics/.

A tiny shop and a two-week window, 2026-03-02 .. 2026-03-15; barber `a` has Altegio id 1, `b` has id 2.
"""
import datetime as dt

from conftest import visit

from barberis_insights.db.models import ScheduleSlot
from barberis_insights.metrics import Dataset, Scope, WindowContext

D = dt.date.fromisoformat
F, T = D("2026-03-02"), D("2026-03-15")
A = Scope("a", 1)
TEAM = Scope("team")


def slot(s, barber, day, start_h=10, end_h=14):
    s.add(ScheduleSlot(barber_id=barber, date=D(day), start_min=start_h * 60, end_min=end_h * 60))


def ctx(s, cohort=None) -> WindowContext:
    s.flush()
    return WindowContext(Dataset.load(s), F, T, cohort)


def shop(s):
    """Barber a works Mon 3/2, Tue 3/3 and Mon 3/9, 10:00-14:00 (12 h). Four visits worth 3000 ₴ (one online,
    one with an add-on) and one no-show. Returns the session."""
    for day in ("2026-03-02", "2026-03-03", "2026-03-09"):
        slot(s, 1, day)
    visit(s, 1, "2026-03-02", 1, 800, online=True)
    visit(s, 2, "2026-03-02", 1, 600, start="11:00", titles=("Чоловіча стрижка", "Масаж"))
    visit(s, 3, "2026-03-09", 1, 700)
    visit(s, 1, "2026-03-03", 1, 900)
    visit(s, 4, "2026-03-09", 1, 500, start="11:00", status="no_show")
    return s
