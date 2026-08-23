"""SQLite persistence for BWF Studio inside Smallink.

Single-file database (WAL mode) storing projects, series, video tasks,
and library assets. Thread-safe via internal RLock.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=15000;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    series_id TEXT,
    title TEXT NOT NULL,
    workflow_mode TEXT NOT NULL DEFAULT 'r2v',
    starred INTEGER NOT NULL DEFAULT 0,
    data_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projects_series ON projects(series_id);
CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at DESC);

CREATE TABLE IF NOT EXISTS series (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    data_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS video_tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    frame_id TEXT,
    asset_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    model TEXT,
    data_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vtasks_project ON video_tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_vtasks_status ON video_tasks(status);

CREATE TABLE IF NOT EXISTS runtime_tasks (
    id TEXT PRIMARY KEY,
    group_name TEXT NOT NULL,
    project_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    data_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rtasks_status ON runtime_tasks(status);

CREATE TABLE IF NOT EXISTS library_assets (
    id TEXT PRIMARY KEY,
    asset_type TEXT NOT NULL,
    data_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_library_type ON library_assets(asset_type);
"""


def _connect(path: str | Path) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    return conn


class BWFStore:
    """Thread-safe SQLite store for BWF project data."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = _connect(path)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── Projects ──

    def save_project(self, project_id: str, data: Dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO projects
                   (id, series_id, title, workflow_mode, starred, data_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    data.get("series_id"),
                    data.get("title", ""),
                    data.get("workflow_mode", "r2v"),
                    1 if data.get("starred") else 0,
                    json.dumps(data, ensure_ascii=False),
                    data.get("created_at", time.time()),
                    data.get("updated_at", time.time()),
                ),
            )
            self._conn.commit()

    def load_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT data_json FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        return json.loads(row["data_json"]) if row else None

    def load_all_projects(self) -> Dict[str, Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, data_json FROM projects ORDER BY updated_at DESC"
        ).fetchall()
        return {row["id"]: json.loads(row["data_json"]) for row in rows}

    def delete_project(self, project_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
            self._conn.execute("DELETE FROM video_tasks WHERE project_id=?", (project_id,))
            self._conn.commit()

    def list_projects(self, series_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        if series_id:
            rows = self._conn.execute(
                "SELECT id, title, series_id, workflow_mode, starred, created_at, updated_at "
                "FROM projects WHERE series_id=? ORDER BY updated_at DESC LIMIT ?",
                (series_id, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, title, series_id, workflow_mode, starred, created_at, updated_at "
                "FROM projects ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Series ──

    def save_series(self, series_id: str, data: Dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO series (id, title, data_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    series_id,
                    data.get("title", ""),
                    json.dumps(data, ensure_ascii=False),
                    data.get("created_at", time.time()),
                    data.get("updated_at", time.time()),
                ),
            )
            self._conn.commit()

    def load_series(self, series_id: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT data_json FROM series WHERE id=?", (series_id,)
        ).fetchone()
        return json.loads(row["data_json"]) if row else None

    def load_all_series(self) -> Dict[str, Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, data_json FROM series ORDER BY updated_at DESC"
        ).fetchall()
        return {row["id"]: json.loads(row["data_json"]) for row in rows}

    def delete_series(self, series_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM series WHERE id=?", (series_id,))
            self._conn.commit()

    # ── Video Tasks ──

    def save_video_task(self, task_id: str, project_id: str, data: Dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO video_tasks
                   (id, project_id, frame_id, asset_id, status, model, data_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    project_id,
                    data.get("frame_id"),
                    data.get("asset_id"),
                    data.get("status", "pending"),
                    data.get("model"),
                    json.dumps(data, ensure_ascii=False),
                    data.get("created_at", time.time()),
                    time.time(),
                ),
            )
            self._conn.commit()

    def get_video_tasks(self, project_id: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT data_json FROM video_tasks WHERE project_id=? ORDER BY created_at",
            (project_id,),
        ).fetchall()
        return [json.loads(r["data_json"]) for r in rows]

    def update_video_task_status(self, task_id: str, status: str, **extra: Any) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data_json FROM video_tasks WHERE id=?", (task_id,)
            ).fetchone()
            if row is None:
                return
            data = json.loads(row["data_json"])
            data["status"] = status
            data.update(extra)
            self._conn.execute(
                "UPDATE video_tasks SET status=?, data_json=?, updated_at=? WHERE id=?",
                (status, json.dumps(data, ensure_ascii=False), time.time(), task_id),
            )
            self._conn.commit()

    def recover_orphan_tasks(self) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT id, data_json FROM video_tasks WHERE status IN ('pending', 'processing')"
            )
            count = 0
            for row in cursor.fetchall():
                data = json.loads(row["data_json"])
                data["status"] = "failed"
                data["error"] = "Backend restarted while task was running. Click Retry."
                self._conn.execute(
                    "UPDATE video_tasks SET status='failed', data_json=?, updated_at=? WHERE id=?",
                    (json.dumps(data, ensure_ascii=False), time.time(), row["id"]),
                )
                count += 1
            if count:
                self._conn.commit()
            return count

    # ── Library Assets ──

    def save_library_asset(self, asset_id: str, asset_type: str, data: Dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO library_assets (id, asset_type, data_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (asset_id, asset_type, json.dumps(data, ensure_ascii=False), time.time(), time.time()),
            )
            self._conn.commit()

    def load_library_assets(self, asset_type: Optional[str] = None) -> List[Dict[str, Any]]:
        if asset_type:
            rows = self._conn.execute(
                "SELECT data_json FROM library_assets WHERE asset_type=?", (asset_type,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT data_json FROM library_assets").fetchall()
        return [json.loads(r["data_json"]) for r in rows]

    def delete_library_asset(self, asset_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM library_assets WHERE id=?", (asset_id,))
            self._conn.commit()

    # ── Cleanup ──

    def cleanup_old_tasks(self, max_age_seconds: int = 7 * 24 * 3600) -> int:
        cutoff = time.time() - max(60, max_age_seconds)
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM runtime_tasks WHERE status IN ('completed', 'failed', 'canceled') "
                "AND updated_at < ?",
                (cutoff,),
            )
            self._conn.commit()
            return cursor.rowcount
