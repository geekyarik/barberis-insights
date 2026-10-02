"""Database schema. Measurements are long-format (scope, metric, value) so new metrics need no migration."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Barber(Base):
    __tablename__ = "barbers"
    altegio_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    tier: Mapped[str] = mapped_column(String(40), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    joined: Mapped[dt.date | None] = mapped_column(Date)
    left: Mapped[dt.date | None] = mapped_column(Date)


class Client(Base):
    """A person as Altegio knows them. Contact fields are personal data: keep minimal, never commit."""
    __tablename__ = "clients"
    altegio_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(200))
    birthday: Mapped[dt.date | None] = mapped_column(Date)
    data_processing_allowed: Mapped[bool | None] = mapped_column(Boolean)
    mass_notification_allowed: Mapped[bool | None] = mapped_column(Boolean)
    tags: Mapped[list | None] = mapped_column(JSON)
    do_not_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    altegio_comment: Mapped[str | None] = mapped_column(Text)  # staff comment from the Altegio client card
    updated_from_altegio_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class ClientProfile(Base):
    """Derived facts, rebuilt from appointments on every ingest."""
    __tablename__ = "client_profiles"
    client_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asof: Mapped[dt.date] = mapped_column(Date)
    first_visit: Mapped[dt.date | None] = mapped_column(Date)
    last_visit: Mapped[dt.date | None] = mapped_column(Date)
    visits: Mapped[int] = mapped_column(Integer, default=0)
    lifetime_spend: Mapped[float] = mapped_column(Float, default=0)
    usual_barber: Mapped[int | None] = mapped_column(Integer)
    last_barber: Mapped[int | None] = mapped_column(Integer)
    median_gap_days: Mapped[float | None] = mapped_column(Float)
    days_since_last: Mapped[int | None] = mapped_column(Integer)
    segment: Mapped[str] = mapped_column(String(20), default="active")
    priority: Mapped[float] = mapped_column(Float, default=0)
    suggested_offer: Mapped[str | None] = mapped_column(String(40))


class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    start: Mapped[str] = mapped_column(String(5))  # HH:MM local
    barber_id: Mapped[int] = mapped_column(Integer, index=True)
    barber_name: Mapped[str | None] = mapped_column(String(80))
    client_id: Mapped[int | None] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_min: Mapped[int] = mapped_column(Integer, default=0)
    total_cost: Mapped[float] = mapped_column(Float, default=0)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    services: Mapped[list["AppointmentService"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class AppointmentService(Base):
    __tablename__ = "appointment_services"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    cost: Mapped[float] = mapped_column(Float, default=0)
    amount: Mapped[float] = mapped_column(Float, default=1)


class ScheduleSlot(Base):
    __tablename__ = "schedule_slots"
    __table_args__ = (UniqueConstraint("barber_id", "date", "start_min"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    barber_id: Mapped[int] = mapped_column(Integer, index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    start_min: Mapped[int] = mapped_column(Integer)
    end_min: Mapped[int] = mapped_column(Integer)


class Measurement(Base):
    __tablename__ = "measurements"
    __table_args__ = (UniqueConstraint("asof", "scope", "metric"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asof: Mapped[dt.date] = mapped_column(Date, index=True)
    window_from: Mapped[dt.date] = mapped_column(Date)
    window_to: Mapped[dt.date] = mapped_column(Date)
    scope: Mapped[str] = mapped_column(String(40), index=True)  # barber key or "team"
    metric: Mapped[str] = mapped_column(String(40), index=True)
    value: Mapped[float] = mapped_column(Float)
    label: Mapped[str] = mapped_column(String(80), default="")


class Offer(Base):
    __tablename__ = "offers"
    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(10), default="none")  # none | percent | fixed
    value: Mapped[float] = mapped_column(Float, default=0)
    valid_days: Mapped[int] = mapped_column(Integer, default=30)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class OutreachCase(Base):
    __tablename__ = "outreach_cases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(Integer, index=True)
    reason: Mapped[str] = mapped_column(String(200), default="")
    segment: Mapped[str] = mapped_column(String(20), default="overdue")
    barber_id: Mapped[int | None] = mapped_column(Integer)
    priority: Mapped[float] = mapped_column(Float, default=0)
    suggested_offer: Mapped[str | None] = mapped_column(String(40))
    offer_arm: Mapped[str | None] = mapped_column(String(40))
    offer_given: Mapped[str | None] = mapped_column(String(40))
    assigned_to: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    contacted_on: Mapped[dt.date | None] = mapped_column(Date)
    returned_on: Mapped[dt.date | None] = mapped_column(Date)
    revenue_recovered: Mapped[float | None] = mapped_column(Float)
    created: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    due: Mapped[dt.date | None] = mapped_column(Date)
    closed: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    sheet_state: Mapped[dict | None] = mapped_column(JSON)  # admin columns as last read from the sheet
    events: Mapped[list["OutreachEvent"]] = relationship(cascade="all, delete-orphan", lazy="selectin", order_by="OutreachEvent.at")


class OutreachEvent(Base):
    __tablename__ = "outreach_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("outreach_cases.id", ondelete="CASCADE"), index=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    kind: Mapped[str] = mapped_column(String(20))  # status | call | note | auto
    outcome: Mapped[str | None] = mapped_column(String(40))
    offer_given: Mapped[str | None] = mapped_column(String(40))
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="dashboard")  # sheet | dashboard | auto | claude


class Goal(Base):
    __tablename__ = "goals"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    scope: Mapped[str] = mapped_column(String(40), index=True)  # barber key or "team"
    title: Mapped[str] = mapped_column(String(200))
    metric: Mapped[str] = mapped_column(String(40))
    baseline: Mapped[float] = mapped_column(Float)
    target: Mapped[float] = mapped_column(Float)
    due: Mapped[dt.date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")
    actions: Mapped[str] = mapped_column(Text, default="")
    manual_current: Mapped[float | None] = mapped_column(Float)
    created: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class GoalEvent(Base):
    __tablename__ = "goal_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goal_id: Mapped[str] = mapped_column(String(60), index=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    kind: Mapped[str] = mapped_column(String(20))  # created | updated | checkin | deleted
    detail: Mapped[dict | None] = mapped_column(JSON)


class Note(Base):
    """Business context: events, decisions, observations. Searchable (FTS5 table `notes_fts`)."""
    __tablename__ = "notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date_from: Mapped[dt.date] = mapped_column(Date, index=True)
    date_to: Mapped[dt.date | None] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(20), default="observation")  # event | decision | observation | external
    scopes: Mapped[list] = mapped_column(JSON, default=list)  # barber keys, "team", "shop"
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(40), default="user")
    created: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)


class Hypothesis(Base):
    __tablename__ = "hypotheses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200))
    statement: Mapped[str] = mapped_column(Text, default="")
    metric: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20), default="did")  # did (diff-in-diff) | prepost | offer_ab
    treatment: Mapped[list] = mapped_column(JSON, default=list)
    control: Mapped[list] = mapped_column(JSON, default=list)
    intervention_date: Mapped[dt.date | None] = mapped_column(Date)
    pre_weeks: Mapped[int] = mapped_column(Integer, default=8)
    post_weeks: Mapped[int] = mapped_column(Integer, default=8)
    expected: Mapped[str] = mapped_column(String(10), default="up")  # up | down | none
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | supported | rejected | inconclusive
    result: Mapped[dict | None] = mapped_column(JSON)
    created: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    evaluated: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Tip(Base):
    __tablename__ = "tips"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    tag: Mapped[str] = mapped_column(String(40), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    barbers: Mapped[list] = mapped_column(JSON, default=list)
    created: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(40))
    started: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    window_from: Mapped[dt.date | None] = mapped_column(Date)
    window_to: Mapped[dt.date | None] = mapped_column(Date)
    counts: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="running")
    log: Mapped[str] = mapped_column(Text, default="")
