"""Job registry. A job module registers itself with @job and does its work through other modules' services."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy.orm import Session


@dataclass
class JobContext:
    s: Session
    slot: dt.datetime            # the local time the run was scheduled for (naive, the shop's clock)
    now: dt.datetime
    dry_run: bool = False


@dataclass(frozen=True)
class JobDef:
    key: str
    label: str
    hours: tuple[int, ...]       # local hours at which a slot falls
    weekday: int | None          # None = every day; 0 = Monday
    run: Callable[[JobContext], dict]
    deliver: Callable | None = None   # called once per tick with the results of every slot processed in it


JOBS: dict[str, JobDef] = {}


def job(key: str, label: str, hours: tuple[int, ...] = (9,), weekday: int | None = None, deliver: Callable | None = None):
    def deco(fn):
        JOBS[key] = JobDef(key, label, hours, weekday, fn, deliver)
        return fn
    return deco
