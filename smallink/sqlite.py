"""Shared SQLite connection policy for Smallink's local stores."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect_sqlite(
    path: str | Path,
    *,
    check_same_thread: bool = False,
    foreign_keys: bool = True,
) -> sqlite3.Connection:
    database = str(path)
    if database != ":memory:":
        Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        database,
        check_same_thread=check_same_thread,
        timeout=15.0,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 15000")
    if foreign_keys:
        connection.execute("PRAGMA foreign_keys = ON")
    if database != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
    return connection
