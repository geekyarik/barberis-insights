import datetime as dt
import itertools

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from barberis_insights.db.models import Appointment, AppointmentService, Barber, Base, Client

_ids = itertools.count(1)


@pytest.fixture(autouse=True)
def _no_live_fetch(monkeypatch):
    """Tests never start a headless Claude; the ones about the fetch step turn it on with a fake runner."""
    from barberis_insights.config import settings
    monkeypatch.setattr(settings, "weekly_fetch", False)


@pytest.fixture
def s(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path / 't.sqlite'}")
    Base.metadata.create_all(eng)
    sess = sessionmaker(eng, expire_on_commit=False)()
    sess.add_all([Barber(altegio_id=1, key="a", name="A", tier="Експерт"), Barber(altegio_id=2, key="b", name="B", tier="Майстер")])
    sess.flush()
    yield sess
    sess.close()


def visit(s, client, day, barber=1, cost=800.0, status="arrived", start="10:00", dur=60, online=False, titles=("Чоловіча стрижка",)):
    a = Appointment(id=next(_ids), date=day if isinstance(day, dt.date) else dt.date.fromisoformat(day), start=start, barber_id=barber,
                    client_id=client, status=status, online=online, duration_min=dur, total_cost=cost, deleted=False,
                    services=[AppointmentService(title=t, cost=cost, amount=1) for t in titles])
    s.add(a)
    return a


def client(s, cid, phone="+380000000000", **kw):
    c = Client(altegio_id=cid, name=f"Client {cid}", phone=phone, **kw)
    s.add(c)
    return c
