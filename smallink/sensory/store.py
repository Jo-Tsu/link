"""SQLite implementation of the immutable sensory record pool."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..sqlite import connect_sqlite
from .models import SensoryRecord


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class SQLiteSensoryStore:
    """Append-only source records with content-hash idempotency."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = connect_sqlite(self.path)
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sensory_records (
                record_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                connector_id TEXT,
                account_id TEXT,
                external_id TEXT NOT NULL,
                content_type TEXT NOT NULL,
                raw_content TEXT NOT NULL,
                normalized_content TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                project_path TEXT,
                conversation_id TEXT,
                content_hash TEXT NOT NULL,
                sensitivity TEXT NOT NULL DEFAULT 'unknown',
                governance_status TEXT NOT NULL DEFAULT 'pending',
                governance_task_id TEXT,
                governance_attempts INTEGER NOT NULL DEFAULT 0,
                governance_claimed_at TEXT,
                governance_processed_at TEXT,
                governance_error TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                source_locator TEXT,
                UNIQUE(source_type, external_id, content_hash)
            );
            CREATE INDEX IF NOT EXISTS idx_sensory_occurred
                ON sensory_records(occurred_at DESC, record_id DESC);
            CREATE INDEX IF NOT EXISTS idx_sensory_governance
                ON sensory_records(governance_status, occurred_at DESC);
            CREATE INDEX IF NOT EXISTS idx_sensory_conversation
                ON sensory_records(conversation_id, occurred_at DESC);
            CREATE INDEX IF NOT EXISTS idx_sensory_source
                ON sensory_records(source_type, occurred_at DESC);
            """
        )
        for ddl in (
            "ALTER TABLE sensory_records ADD COLUMN governance_task_id TEXT",
            "ALTER TABLE sensory_records ADD COLUMN governance_attempts INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE sensory_records ADD COLUMN governance_claimed_at TEXT",
            "ALTER TABLE sensory_records ADD COLUMN governance_processed_at TEXT",
            "ALTER TABLE sensory_records ADD COLUMN governance_error TEXT",
        ):
            try:
                self._conn.execute(ddl)
            except Exception:
                pass
        self._conn.commit()

    def add(
        self,
        *,
        source_type: str,
        content_type: str,
        raw_content: Any,
        external_id: Optional[str] = None,
        normalized_content: Optional[str] = None,
        occurred_at: Optional[str] = None,
        connector_id: Optional[str] = None,
        account_id: Optional[str] = None,
        project_path: Optional[str] = None,
        conversation_id: Optional[str] = None,
        sensitivity: str = "unknown",
        metadata: Optional[dict[str, Any]] = None,
        source_locator: Optional[str] = None,
    ) -> SensoryRecord:
        raw = _text(raw_content)
        normalized = normalized_content if normalized_content is not None else raw
        digest = hashlib.sha256(
            f"{source_type}\0{content_type}\0{raw}".encode("utf-8")
        ).hexdigest()
        stable_external_id = str(external_id or digest)
        record_id = "sensory-" + uuid.uuid4().hex
        timestamp = occurred_at or _now()
        ingested = _now()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO sensory_records (
                    record_id, source_type, connector_id, account_id, external_id,
                    content_type, raw_content, normalized_content, occurred_at, ingested_at,
                    project_path, conversation_id, content_hash, sensitivity,
                    governance_status, metadata_json, source_locator
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    record_id,
                    source_type,
                    connector_id,
                    account_id,
                    stable_external_id,
                    content_type,
                    raw,
                    normalized,
                    timestamp,
                    ingested,
                    project_path,
                    conversation_id,
                    digest,
                    sensitivity,
                    metadata_json,
                    source_locator,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                """
                SELECT * FROM sensory_records
                WHERE source_type=? AND external_id=? AND content_hash=?
                """,
                (source_type, stable_external_id, digest),
            ).fetchone()
        return self._record(row)

    def get(self, record_id: str) -> Optional[SensoryRecord]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sensory_records WHERE record_id=?", (record_id,)
            ).fetchone()
        return self._record(row) if row else None

    def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        source_type: Optional[str] = None,
        governance_status: Optional[str] = None,
        conversation_id: Optional[str] = None,
        query: Optional[str] = None,
    ) -> list[SensoryRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("source_type", source_type),
            ("governance_status", governance_status),
            ("conversation_id", conversation_id),
        ):
            if value:
                clauses.append(f"{column}=?")
                params.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        if query:
            search = f"%{query.strip().lower()}%"
            clauses.append(
                """
                (
                    LOWER(raw_content) LIKE ? OR LOWER(normalized_content) LIKE ?
                    OR LOWER(COALESCE(project_path, '')) LIKE ?
                    OR LOWER(COALESCE(conversation_id, '')) LIKE ?
                    OR LOWER(external_id) LIKE ? OR LOWER(source_type) LIKE ?
                )
                """
            )
            params.extend([search] * 6)
            where = " WHERE " + " AND ".join(clauses)
        params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM sensory_records{where} ORDER BY occurred_at DESC, record_id DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._record(row) for row in rows]

    def count(
        self,
        *,
        source_type: Optional[str] = None,
        governance_status: Optional[str] = None,
        conversation_id: Optional[str] = None,
        query: Optional[str] = None,
    ) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("source_type", source_type),
            ("governance_status", governance_status),
            ("conversation_id", conversation_id),
        ):
            if value:
                clauses.append(f"{column}=?")
                params.append(value)
        if query:
            search = f"%{query.strip().lower()}%"
            clauses.append(
                """
                (
                    LOWER(raw_content) LIKE ? OR LOWER(normalized_content) LIKE ?
                    OR LOWER(COALESCE(project_path, '')) LIKE ?
                    OR LOWER(COALESCE(conversation_id, '')) LIKE ?
                    OR LOWER(external_id) LIKE ? OR LOWER(source_type) LIKE ?
                )
                """
            )
            params.extend([search] * 6)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._lock:
            row = self._conn.execute(
                f"SELECT COUNT(*) AS total FROM sensory_records{where}", params
            ).fetchone()
        return int(row["total"])

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = int(
                self._conn.execute("SELECT COUNT(*) FROM sensory_records").fetchone()[0]
            )
            pending = int(
                self._conn.execute(
                    "SELECT COUNT(*) FROM sensory_records WHERE governance_status='pending'"
                ).fetchone()[0]
            )
            sources = {
                row["source_type"]: int(row["count"])
                for row in self._conn.execute(
                    "SELECT source_type, COUNT(*) AS count FROM sensory_records GROUP BY source_type"
                ).fetchall()
            }
        return {"total": total, "pending": pending, "sources": sources}

    def claim_for_governance(
        self,
        task_id: str,
        *,
        record_ids: Optional[list[str]] = None,
        limit: int = 50,
        retry_failed: bool = False,
    ) -> list[SensoryRecord]:
        statuses = ["pending", *(["failed"] if retry_failed else [])]
        placeholders = ",".join("?" for _ in statuses)
        clauses = [f"governance_status IN ({placeholders})"]
        params: list[Any] = list(statuses)
        if record_ids:
            ids = list(dict.fromkeys(str(record_id) for record_id in record_ids if record_id))
            if not ids:
                return []
            clauses.append("record_id IN (" + ",".join("?" for _ in ids) + ")")
            params.extend(ids)
        query = (
            "SELECT record_id FROM sensory_records WHERE "
            + " AND ".join(clauses)
            + " ORDER BY occurred_at, record_id LIMIT ?"
        )
        params.append(max(1, min(int(limit), 500)))
        now = _now()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                rows = self._conn.execute(query, params).fetchall()
                ids = [str(row["record_id"]) for row in rows]
                if ids:
                    self._conn.execute(
                        """
                        UPDATE sensory_records
                        SET governance_status='processing', governance_task_id=?,
                            governance_claimed_at=?, governance_error=NULL
                        WHERE record_id IN ("""
                        + ",".join("?" for _ in ids)
                        + ")",
                        [task_id, now, *ids],
                    )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            if not ids:
                return []
            claimed = self._conn.execute(
                "SELECT * FROM sensory_records WHERE record_id IN ("
                + ",".join("?" for _ in ids)
                + ") ORDER BY occurred_at, record_id",
                ids,
            ).fetchall()
        return [self._record(row) for row in claimed]

    def finish_governance(
        self,
        record_id: str,
        task_id: str,
        status: str,
        *,
        error: Optional[str] = None,
    ) -> bool:
        if status not in {"processed", "skipped", "failed"}:
            raise ValueError("invalid governance status")
        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE sensory_records
                SET governance_status=?, governance_attempts=governance_attempts+1,
                    governance_processed_at=?, governance_error=?
                WHERE record_id=? AND governance_task_id=? AND governance_status='processing'
                """,
                (status, _now(), error, record_id, task_id),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def release_governance_task(self, task_id: str) -> int:
        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE sensory_records
                SET governance_status='pending', governance_task_id=NULL,
                    governance_claimed_at=NULL
                WHERE governance_task_id=? AND governance_status='processing'
                """,
                (task_id,),
            )
            self._conn.commit()
        return int(cursor.rowcount)

    def delete(
        self,
        *,
        record_ids: Optional[list[str]] = None,
        source_type: Optional[str] = None,
        before: Optional[str] = None,
    ) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if record_ids:
            ids = list(dict.fromkeys(str(record_id) for record_id in record_ids if record_id))
            if ids:
                clauses.append("record_id IN (" + ",".join("?" for _ in ids) + ")")
                params.extend(ids)
        if source_type:
            clauses.append("source_type=?")
            params.append(source_type)
        if before:
            clauses.append("occurred_at<?")
            params.append(before)
        if not clauses:
            raise ValueError("a record, source, or time boundary is required")
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM sensory_records WHERE " + " AND ".join(clauses), params
            )
            self._conn.commit()
        return int(cursor.rowcount)

    @staticmethod
    def _record(row) -> SensoryRecord:
        return SensoryRecord(
            record_id=row["record_id"],
            source_type=row["source_type"],
            connector_id=row["connector_id"],
            account_id=row["account_id"],
            external_id=row["external_id"],
            content_type=row["content_type"],
            raw_content=row["raw_content"],
            normalized_content=row["normalized_content"],
            occurred_at=row["occurred_at"],
            ingested_at=row["ingested_at"],
            project_path=row["project_path"],
            conversation_id=row["conversation_id"],
            content_hash=row["content_hash"],
            sensitivity=row["sensitivity"],
            governance_status=row["governance_status"],
            metadata=json.loads(row["metadata_json"] or "{}"),
            source_locator=row["source_locator"],
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
