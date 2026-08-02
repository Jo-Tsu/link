"""Durable connector sync jobs and watermarks."""

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


class ConnectorSyncStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = connect_sqlite(path)
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS connector_sync_jobs (
                job_id TEXT PRIMARY KEY,
                connector TEXT NOT NULL,
                status TEXT NOT NULL,
                root_path TEXT,
                files_scanned INTEGER NOT NULL DEFAULT 0,
                sessions_read INTEGER NOT NULL DEFAULT 0,
                records_seen INTEGER NOT NULL DEFAULT 0,
                records_ingested INTEGER NOT NULL DEFAULT 0,
                files_failed INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                error TEXT,
                details_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_connector_sync_jobs
                ON connector_sync_jobs(connector, started_at DESC);
            CREATE TABLE IF NOT EXISTS connector_sync_watermarks (
                connector TEXT PRIMARY KEY,
                root_path TEXT,
                last_success_at TEXT,
                last_file TEXT,
                last_file_mtime REAL,
                last_job_id TEXT,
                updated_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def start(self, connector: str, root_path: Optional[str]) -> str:
        job_id = "sync-" + uuid.uuid4().hex
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO connector_sync_jobs (
                    job_id, connector, status, root_path, started_at
                ) VALUES (?, ?, 'running', ?, ?)
                """,
                (job_id, connector, root_path, _now()),
            )
            self._conn.commit()
        return job_id

    def finish(
        self,
        job_id: str,
        *,
        status: str,
        files_scanned: int = 0,
        sessions_read: int = 0,
        records_seen: int = 0,
        records_ingested: int = 0,
        files_failed: int = 0,
        error: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        last_file: Optional[str] = None,
        last_file_mtime: Optional[float] = None,
    ) -> dict[str, Any]:
        now = _now()
        with self._lock:
            self._conn.execute(
                """
                UPDATE connector_sync_jobs
                SET status=?, files_scanned=?, sessions_read=?, records_seen=?,
                    records_ingested=?, files_failed=?, finished_at=?, error=?,
                    details_json=?
                WHERE job_id=?
                """,
                (
                    status,
                    int(files_scanned),
                    int(sessions_read),
                    int(records_seen),
                    int(records_ingested),
                    int(files_failed),
                    now,
                    error,
                    json.dumps(details or {}, ensure_ascii=False),
                    job_id,
                ),
            )
            row = self._conn.execute(
                "SELECT connector, root_path FROM connector_sync_jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
            if row is not None and status == "completed":
                self._conn.execute(
                    """
                    INSERT INTO connector_sync_watermarks (
                        connector, root_path, last_success_at, last_file,
                        last_file_mtime, last_job_id, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(connector) DO UPDATE SET
                        root_path=excluded.root_path,
                        last_success_at=excluded.last_success_at,
                        last_file=excluded.last_file,
                        last_file_mtime=excluded.last_file_mtime,
                        last_job_id=excluded.last_job_id,
                        updated_at=excluded.updated_at
                    """,
                    (
                        row["connector"],
                        row["root_path"],
                        now,
                        last_file,
                        last_file_mtime,
                        job_id,
                        now,
                    ),
                )
            self._conn.commit()
        return self.get(job_id) or {}

    def fail(self, job_id: str, error: Exception | str) -> dict[str, Any]:
        return self.finish(
            job_id,
            status="failed",
            error=f"{type(error).__name__}: {error}" if isinstance(error, Exception) else str(error),
        )

    def get(self, job_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM connector_sync_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        return self._row(row) if row else None

    def latest(self, connector: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM connector_sync_jobs
                WHERE connector=? ORDER BY started_at DESC LIMIT 1
                """,
                (connector,),
            ).fetchone()
            watermark = self._conn.execute(
                "SELECT * FROM connector_sync_watermarks WHERE connector=?",
                (connector,),
            ).fetchone()
        if row is None:
            return None
        result = self._row(row)
        result["watermark"] = dict(watermark) if watermark else None
        return result

    @staticmethod
    def _row(row) -> dict[str, Any]:
        result = dict(row)
        result["details"] = json.loads(result.pop("details_json") or "{}")
        return result

    def close(self) -> None:
        with self._lock:
            self._conn.close()
