"""SQLite-backed memory store (the default adapter)."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Optional

from .base import MemoryItem, MemoryStore, Scope


class SQLiteMemoryStore(MemoryStore):
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the server runs the WS handler on a different thread
        # than the store was created on; a lock serializes access.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL,
                key TEXT,
                content TEXT NOT NULL,
                workspace TEXT,
                session_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """)
        # Additive migration (house style — see conversations.py): older DBs miss the
        # lifecycle/provenance columns. `status` defaults to 'active' so every pre-existing
        # row stays visible and injectable exactly as before.
        for ddl in (
            "ALTER TABLE memories ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
            "ALTER TABLE memories ADD COLUMN updated_at TEXT",
            "ALTER TABLE memories ADD COLUMN source_record_id TEXT",
        ):
            try:
                self._conn.execute(ddl)
            except sqlite3.OperationalError:
                pass
        # Append-only version history (modeled on mem0's history table): every add/update/delete
        # writes one row, so a memory's full evolution is recoverable.
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id INTEGER NOT NULL,
                old_content TEXT,
                new_content TEXT,
                event TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memory_history_memory "
            "ON memory_history(memory_id, id)"
        )
        self._conn.commit()

    def _record_history(
        self,
        item_id: int,
        *,
        old: Optional[str],
        new: Optional[str],
        event: str,
    ) -> None:
        # RLock is re-entrant, so callers already holding self._lock can call this safely.
        with self._lock:
            self._conn.execute(
                "INSERT INTO memory_history (memory_id, old_content, new_content, event) "
                "VALUES (?, ?, ?, ?)",
                (item_id, old, new, event),
            )
            self._conn.commit()

    def add(
        self,
        content: str,
        *,
        scope: Scope = Scope.WORKSPACE,
        key: Optional[str] = None,
        workspace: Optional[str] = None,
        session_id: Optional[str] = None,
        status: str = "active",
        source_record_id: Optional[str] = None,
    ) -> MemoryItem:
        scope = Scope(scope)
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO memories (scope, key, content, workspace, session_id, status, "
                "source_record_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    scope.value,
                    key,
                    content,
                    workspace,
                    session_id,
                    status,
                    source_record_id,
                ),
            )
            self._conn.commit()
            item = self.get(cursor.lastrowid)
        assert item is not None
        self._record_history(item.id, old=None, new=content, event="ADD")
        return item

    def get(self, item_id: int) -> Optional[MemoryItem]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memories WHERE id = ?", (item_id,)
            ).fetchone()
        return _row_to_item(row) if row else None

    def list(
        self,
        *,
        scope: Optional[Scope] = None,
        workspace: Optional[str] = None,
        session_id: Optional[str] = None,
        status: Optional[str] = "active",
    ) -> list[MemoryItem]:
        query = "SELECT * FROM memories WHERE 1 = 1"
        params: list[object] = []
        if scope is not None:
            query += " AND scope = ?"
            params.append(Scope(scope).value)
        if workspace is not None:
            query += " AND workspace = ?"
            params.append(workspace)
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(session_id)
        # Default status="active" keeps pipeline-produced "pending" memories out of every
        # prompt-injection and confirmed-memory query. Pass status=None to include all.
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY id"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [_row_to_item(row) for row in rows]

    def list_history(self, memory_id: Optional[int] = None) -> list[dict]:
        query = "SELECT * FROM memory_history"
        params: list[object] = []
        if memory_id is not None:
            query += " WHERE memory_id = ?"
            params.append(memory_id)
        query += " ORDER BY id"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def update(self, item_id: int, content: str) -> Optional[MemoryItem]:
        with self._lock:
            existing = self._conn.execute(
                "SELECT content FROM memories WHERE id = ?", (item_id,)
            ).fetchone()
            if existing is None:
                return None
            old = existing["content"]
            self._conn.execute(
                "UPDATE memories SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (content, item_id),
            )
            self._conn.commit()
        self._record_history(item_id, old=old, new=content, event="UPDATE")
        return self.get(item_id)

    def delete(self, item_id: int) -> bool:
        with self._lock:
            existing = self._conn.execute(
                "SELECT content FROM memories WHERE id = ?", (item_id,)
            ).fetchone()
            cursor = self._conn.execute("DELETE FROM memories WHERE id = ?", (item_id,))
            self._conn.commit()
            deleted = cursor.rowcount > 0
        if deleted:
            old = existing["content"] if existing is not None else None
            self._record_history(item_id, old=old, new=None, event="DELETE")
        return deleted

    def close(self) -> None:
        self._conn.close()


def _row_to_item(row: sqlite3.Row) -> MemoryItem:
    keys = row.keys()
    return MemoryItem(
        id=row["id"],
        scope=Scope(row["scope"]),
        content=row["content"],
        key=row["key"],
        workspace=row["workspace"],
        session_id=row["session_id"],
        created_at=row["created_at"],
        status=row["status"] if "status" in keys else "active",
        updated_at=row["updated_at"] if "updated_at" in keys else None,
        source_record_id=(
            row["source_record_id"] if "source_record_id" in keys else None
        ),
    )
