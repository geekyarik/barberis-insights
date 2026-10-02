from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings


@lru_cache
def engine(url: str | None = None) -> Engine:
    url = url or settings.db_url
    if url.startswith("sqlite:///"):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
    eng = create_engine(url, future=True)

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_conn, _):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    return eng


def session_factory(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(engine(url), expire_on_commit=False)


@contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    s = session_factory(url)()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


FTS_DDL = [
    "CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(title, body, tags, content='notes', content_rowid='id')",
    "CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN INSERT INTO notes_fts(rowid,title,body,tags) VALUES (new.id,new.title,new.body,new.tags); END",
    "CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN INSERT INTO notes_fts(notes_fts,rowid,title,body,tags) VALUES('delete',old.id,old.title,old.body,old.tags); END",
    "CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN INSERT INTO notes_fts(notes_fts,rowid,title,body,tags) VALUES('delete',old.id,old.title,old.body,old.tags); INSERT INTO notes_fts(rowid,title,body,tags) VALUES (new.id,new.title,new.body,new.tags); END",
]


def ensure_fts(eng: Engine) -> None:
    with eng.begin() as c:
        for ddl in FTS_DDL:
            c.execute(text(ddl))
