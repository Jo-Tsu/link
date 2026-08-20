"""SQLite persistence for app instances, capability runs, and stable asset references."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..sqlite import connect_sqlite


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteAppStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = connect_sqlite(path)
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_instances (
                app_id TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                install_state TEXT NOT NULL DEFAULT 'unknown',
                runtime_state TEXT NOT NULL DEFAULT 'offline',
                app_version TEXT,
                protocol_version TEXT,
                status_json TEXT NOT NULL DEFAULT '{}',
                last_checked_at TEXT,
                last_error TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS app_capability_runs (
                capability_run_id TEXT PRIMARY KEY,
                app_id TEXT NOT NULL,
                project_id TEXT,
                session_id TEXT,
                capability TEXT NOT NULL,
                arguments_json TEXT NOT NULL,
                result_json TEXT,
                status TEXT NOT NULL,
                error TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_app_runs_app_time
                ON app_capability_runs(app_id, started_at DESC);
            CREATE TABLE IF NOT EXISTS app_asset_refs (
                asset_ref_id TEXT PRIMARY KEY,
                app_id TEXT NOT NULL,
                project_id TEXT,
                external_asset_id TEXT NOT NULL,
                external_code TEXT,
                asset_type TEXT,
                version_id TEXT NOT NULL DEFAULT '',
                title TEXT,
                preview_ref TEXT,
                content_hash TEXT,
                sensory_record_id TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                UNIQUE(app_id, external_asset_id, version_id)
            );
            CREATE INDEX IF NOT EXISTS idx_app_assets_project
                ON app_asset_refs(project_id, last_seen_at DESC);
            """
        )
        self._conn.commit()

    def ensure_instance(self, app_id: str, *, enabled: bool = True) -> dict[str, Any]:
        now = _now()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO app_instances (app_id, enabled, updated_at)
                VALUES (?, ?, ?)
                """,
                (app_id, 1 if enabled else 0, now),
            )
            self._conn.commit()
        return self.get_instance(app_id) or {}

    def close(self) -> None:
        """Release the database connection when the desktop sidecar shuts down."""
        with self._lock:
            self._conn.close()

    def get_instance(self, app_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM app_instances WHERE app_id=?", (app_id,)
            ).fetchone()
        return self._instance(row) if row else None

    def update_instance(self, app_id: str, **values: Any) -> dict[str, Any]:
        allowed = {
            "enabled",
            "install_state",
            "runtime_state",
            "app_version",
            "protocol_version",
            "status",
            "last_checked_at",
            "last_error",
        }
        self.ensure_instance(app_id)
        sets: list[str] = []
        params: list[Any] = []
        for key, value in values.items():
            if key not in allowed:
                continue
            column = "status_json" if key == "status" else key
            if key == "enabled":
                value = 1 if value else 0
            if key == "status":
                value = json.dumps(value or {}, ensure_ascii=False, sort_keys=True)
            sets.append(f"{column}=?")
            params.append(value)
        if sets:
            sets.append("updated_at=?")
            params.append(_now())
            with self._lock:
                self._conn.execute(
                    f"UPDATE app_instances SET {', '.join(sets)} WHERE app_id=?",
                    (*params, app_id),
                )
                self._conn.commit()
        return self.get_instance(app_id) or {}

    def record_capability_run(
        self,
        *,
        app_id: str,
        project_id: Optional[str],
        session_id: Optional[str],
        capability: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        run_id = "app-run-" + uuid.uuid4().hex
        now = _now()
        ok = bool(result.get("ok"))
        error = None if ok else str(result.get("error") or "Application command failed")
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO app_capability_runs (
                    capability_run_id, app_id, project_id, session_id, capability,
                    arguments_json, result_json, status, error, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    app_id,
                    project_id,
                    session_id,
                    capability,
                    json.dumps(arguments, ensure_ascii=False, sort_keys=True),
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                    "completed" if ok else "failed",
                    error,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        return {
            "capability_run_id": run_id,
            "status": "completed" if ok else "failed",
            "error": error,
            "started_at": now,
            "finished_at": now,
        }

    def list_runs(self, app_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM app_capability_runs WHERE app_id=?
                ORDER BY started_at DESC LIMIT ?
                """,
                (app_id, max(1, min(int(limit), 200))),
            ).fetchall()
        return [
            {
                "capability_run_id": row["capability_run_id"],
                "app_id": row["app_id"],
                "project_id": row["project_id"],
                "session_id": row["session_id"],
                "capability": row["capability"],
                "arguments": json.loads(row["arguments_json"] or "{}"),
                "status": row["status"],
                "error": row["error"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
            }
            for row in rows
        ]

    def upsert_asset(
        self,
        *,
        app_id: str,
        project_id: Optional[str],
        external_asset_id: str,
        external_code: Optional[str],
        asset_type: Optional[str],
        version_id: Optional[str],
        title: Optional[str],
        preview_ref: Optional[str],
        content_hash: Optional[str],
        sensory_record_id: Optional[str] = None,
    ) -> dict[str, Any]:
        stable_version = str(version_id or "")
        now = _now()
        with self._lock:
            row = self._conn.execute(
                """
                SELECT asset_ref_id, first_seen_at FROM app_asset_refs
                WHERE app_id=? AND external_asset_id=? AND version_id=?
                """,
                (app_id, external_asset_id, stable_version),
            ).fetchone()
            asset_ref_id = str(row["asset_ref_id"]) if row else "asset-ref-" + uuid.uuid4().hex
            first_seen = str(row["first_seen_at"]) if row else now
            self._conn.execute(
                """
                INSERT INTO app_asset_refs (
                    asset_ref_id, app_id, project_id, external_asset_id, external_code,
                    asset_type, version_id, title, preview_ref, content_hash,
                    sensory_record_id, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(app_id, external_asset_id, version_id) DO UPDATE SET
                    project_id=excluded.project_id,
                    external_code=COALESCE(excluded.external_code, app_asset_refs.external_code),
                    asset_type=COALESCE(excluded.asset_type, app_asset_refs.asset_type),
                    title=COALESCE(excluded.title, app_asset_refs.title),
                    preview_ref=COALESCE(excluded.preview_ref, app_asset_refs.preview_ref),
                    content_hash=COALESCE(excluded.content_hash, app_asset_refs.content_hash),
                    sensory_record_id=COALESCE(excluded.sensory_record_id, app_asset_refs.sensory_record_id),
                    last_seen_at=excluded.last_seen_at
                """,
                (
                    asset_ref_id,
                    app_id,
                    project_id,
                    external_asset_id,
                    external_code,
                    asset_type,
                    stable_version,
                    title,
                    preview_ref,
                    content_hash,
                    sensory_record_id,
                    first_seen,
                    now,
                ),
            )
            self._conn.commit()
        return self.get_asset_ref(app_id, external_asset_id, stable_version) or {}

    def get_asset_ref(
        self, app_id: str, external_asset_id: str, version_id: str = ""
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM app_asset_refs
                WHERE app_id=? AND external_asset_id=? AND version_id=?
                """,
                (app_id, external_asset_id, version_id),
            ).fetchone()
        return dict(row) if row else None

    def list_assets(
        self, app_id: str, *, project_id: Optional[str] = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM app_asset_refs WHERE app_id=?"
        params: list[Any] = [app_id]
        if project_id:
            query += " AND project_id=?"
            params.append(project_id)
        query += " ORDER BY last_seen_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def count_assets(self, app_id: str, *, project_id: Optional[str] = None) -> int:
        query = "SELECT COUNT(*) FROM app_asset_refs WHERE app_id=?"
        params: list[Any] = [app_id]
        if project_id:
            query += " AND project_id=?"
            params.append(project_id)
        with self._lock:
            row = self._conn.execute(query, params).fetchone()
        return int(row[0])

    @staticmethod
    def _instance(row: Any) -> dict[str, Any]:
        return {
            "app_id": row["app_id"],
            "enabled": bool(row["enabled"]),
            "install_state": row["install_state"],
            "runtime_state": row["runtime_state"],
            "app_version": row["app_version"],
            "protocol_version": row["protocol_version"],
            "status": json.loads(row["status_json"] or "{}"),
            "last_checked_at": row["last_checked_at"],
            "last_error": row["last_error"],
            "updated_at": row["updated_at"],
        }
