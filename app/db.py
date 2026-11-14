import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

from . import config

T = TypeVar("T")
Db = sqlite3.Connection


def connect(path: str | None = None) -> Db:
    # isolation_level=None: autocommit; transactions are explicit through tx().
    conn = sqlite3.connect(path or config.database_path(), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_db() -> Iterator[Db]:
    """FastAPI dependency: one connection per request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def tx(db: Db, fn: Callable[[], T]) -> T:
    """Runs fn in a write transaction (all or nothing)."""
    db.execute("BEGIN IMMEDIATE")
    try:
        result = fn()
    except BaseException:
        db.execute("ROLLBACK")
        raise
    db.execute("COMMIT")
    return result


def one(db: Db, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
    row = db.execute(sql, params).fetchone()
    return dict(row) if row else None


def all_(db: Db, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in db.execute(sql, params).fetchall()]
