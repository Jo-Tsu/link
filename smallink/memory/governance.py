"""Durable governance tasks, candidates, decisions, versions, and provenance."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..sqlite import connect_sqlite
from .base import MemoryStore, Scope
from .types import MEMORY_TYPES


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


@dataclass(frozen=True)
class MemoryCandidate:
    candidate_id: str
    task_id: str
    content: str
    memory_type: Optional[str]
    scope: str
    workspace: Optional[str]
    session_id: Optional[str]
    status: str
    confidence: Optional[float]
    model: str
    prompt_version: str
    created_at: str
    updated_at: str
    sources: list[str]
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SQLiteGovernanceStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = connect_sqlite(path)
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS governance_tasks (
                task_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                total_records INTEGER NOT NULL DEFAULT 0,
                processed_records INTEGER NOT NULL DEFAULT 0,
                candidates_created INTEGER NOT NULL DEFAULT 0,
                skipped_records INTEGER NOT NULL DEFAULT 0,
                failed_records INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS governance_task_records (
                task_id TEXT NOT NULL REFERENCES governance_tasks(task_id) ON DELETE CASCADE,
                record_id TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                claimed_at TEXT,
                processed_at TEXT,
                error TEXT,
                PRIMARY KEY (task_id, record_id)
            );
            CREATE INDEX IF NOT EXISTS idx_governance_records_status
                ON governance_task_records(status, record_id);
            CREATE TABLE IF NOT EXISTS memory_candidates (
                candidate_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES governance_tasks(task_id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                memory_type TEXT,
                scope TEXT NOT NULL,
                workspace TEXT,
                session_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                confidence REAL,
                model TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS candidate_sources (
                candidate_id TEXT NOT NULL REFERENCES memory_candidates(candidate_id) ON DELETE CASCADE,
                record_id TEXT NOT NULL,
                PRIMARY KEY (candidate_id, record_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_candidate_source_content
                ON memory_candidates(task_id, content, scope, COALESCE(workspace, ''), COALESCE(session_id, ''));
            CREATE TABLE IF NOT EXISTS governance_decisions (
                decision_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL REFERENCES memory_candidates(candidate_id) ON DELETE CASCADE,
                action TEXT NOT NULL,
                original_content TEXT NOT NULL,
                final_content TEXT,
                memory_id INTEGER,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS memory_versions (
                version_id TEXT PRIMARY KEY,
                memory_id INTEGER NOT NULL,
                version INTEGER NOT NULL,
                content TEXT NOT NULL,
                memory_type TEXT,
                scope TEXT NOT NULL,
                workspace TEXT,
                session_id TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                decision_id TEXT,
                UNIQUE(memory_id, version)
            );
            CREATE TABLE IF NOT EXISTS memory_sources (
                memory_id INTEGER NOT NULL,
                record_id TEXT NOT NULL,
                candidate_id TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (memory_id, record_id)
            );
            CREATE TABLE IF NOT EXISTS memory_usage (
                usage_id TEXT PRIMARY KEY,
                memory_id INTEGER NOT NULL,
                version_id TEXT,
                session_id TEXT,
                workspace TEXT,
                used_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def create_task(self, record_ids: list[str], *, model: str, prompt_version: str) -> str:
        task_id = _id("governance")
        now = _now()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO governance_tasks (
                    task_id, status, model, prompt_version, total_records, created_at, updated_at
                ) VALUES (?, 'running', ?, ?, ?, ?, ?)
                """,
                (task_id, model, prompt_version, len(record_ids), now, now),
            )
            self._conn.executemany(
                """
                INSERT INTO governance_task_records (task_id, record_id, status)
                VALUES (?, ?, 'pending')
                """,
                [(task_id, record_id) for record_id in record_ids],
            )
            self._conn.commit()
        return task_id

    def attach_records(self, task_id: str, record_ids: list[str]) -> None:
        with self._lock:
            self._conn.executemany(
                """
                INSERT OR IGNORE INTO governance_task_records (task_id, record_id, status)
                VALUES (?, ?, 'pending')
                """,
                [(task_id, record_id) for record_id in record_ids],
            )
            self._conn.execute(
                "UPDATE governance_tasks SET total_records=?, updated_at=? WHERE task_id=?",
                (len(record_ids), _now(), task_id),
            )
            self._conn.commit()

    def mark_record(
        self,
        task_id: str,
        record_id: str,
        status: str,
        *,
        error: Optional[str] = None,
    ) -> None:
        now = _now()
        with self._lock:
            self._conn.execute(
                """
                UPDATE governance_task_records
                SET status=?, attempts=attempts+1, claimed_at=COALESCE(claimed_at, ?),
                    processed_at=?, error=?
                WHERE task_id=? AND record_id=?
                """,
                (status, now, now, error, task_id, record_id),
            )
            self._conn.commit()

    def add_candidate(
        self,
        *,
        task_id: str,
        content: str,
        memory_type: Optional[str],
        scope: Scope,
        workspace: Optional[str],
        session_id: Optional[str],
        model: str,
        prompt_version: str,
        source_ids: list[str],
        confidence: Optional[float] = None,
    ) -> MemoryCandidate:
        candidate_id = _id("candidate")
        now = _now()
        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT INTO memory_candidates (
                        candidate_id, task_id, content, memory_type, scope, workspace,
                        session_id, status, confidence, model, prompt_version, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate_id,
                        task_id,
                        content,
                        memory_type,
                        scope.value,
                        workspace,
                        session_id,
                        confidence,
                        model,
                        prompt_version,
                        now,
                        now,
                    ),
                )
            except Exception:
                row = self._conn.execute(
                    """
                    SELECT candidate_id FROM memory_candidates
                    WHERE task_id=? AND content=? AND scope=?
                      AND COALESCE(workspace, '')=COALESCE(?, '')
                      AND COALESCE(session_id, '')=COALESCE(?, '')
                    """,
                    (task_id, content, scope.value, workspace, session_id),
                ).fetchone()
                if row is None:
                    raise
                candidate_id = str(row["candidate_id"])
            self._conn.executemany(
                "INSERT OR IGNORE INTO candidate_sources (candidate_id, record_id) VALUES (?, ?)",
                [(candidate_id, source_id) for source_id in source_ids],
            )
            self._conn.commit()
        candidate = self.get_candidate(candidate_id)
        assert candidate is not None
        return candidate

    def list_candidates(
        self,
        status: Optional[str] = "pending",
        *,
        min_confidence: Optional[float] = None,
        max_confidence: Optional[float] = None,
    ) -> list[MemoryCandidate]:
        query = "SELECT * FROM memory_candidates"
        conditions: list[str] = []
        params: list[Any] = []
        if status is not None:
            conditions.append("status=?")
            params.append(status)
        if min_confidence is not None:
            conditions.append("confidence >= ?")
            params.append(min_confidence)
        if max_confidence is not None:
            conditions.append("confidence < ?")
            params.append(max_confidence)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY confidence DESC, created_at DESC, candidate_id DESC"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._candidate(row) for row in rows]

    def auto_accept_high_confidence(
        self,
        memory_store: MemoryStore,
        *,
        threshold: float = 0.9,
    ) -> dict[str, Any]:
        """Auto-accept pending candidates with confidence >= threshold."""
        candidates = self.list_candidates("pending", min_confidence=threshold)
        accepted = 0
        failed: list[str] = []
        for candidate in candidates:
            try:
                self.decide(candidate.candidate_id, "accept", memory_store)
                accepted += 1
            except Exception:
                failed.append(candidate.candidate_id)
        return {
            "auto_accepted": accepted,
            "failed": len(failed),
            "threshold": threshold,
        }

    def get_candidate(self, candidate_id: str) -> Optional[MemoryCandidate]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memory_candidates WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
        return self._candidate(row) if row else None

    def set_candidate_type(
        self, candidate_id: str, memory_type: str
    ) -> MemoryCandidate:
        if memory_type not in MEMORY_TYPES:
            raise ValueError("unsupported memory type")
        with self._lock:
            row = self._conn.execute(
                "SELECT status, memory_type FROM memory_candidates WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
            if row is None:
                raise KeyError(candidate_id)
            if row["status"] != "pending":
                raise ValueError("only pending candidates can change type")
            if row["memory_type"] != memory_type:
                self._conn.execute(
                    "UPDATE memory_candidates SET memory_type=?, updated_at=? WHERE candidate_id=?",
                    (memory_type, _now(), candidate_id),
                )
                self._conn.commit()
        candidate = self.get_candidate(candidate_id)
        assert candidate is not None
        return candidate

    def list_tasks(
        self, *, status: Optional[str] = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        where = " WHERE t.status=?" if status else ""
        params: list[Any] = [status] if status else []
        params.append(max(1, min(int(limit), 500)))
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT t.*,
                    (SELECT COUNT(*) FROM memory_candidates c WHERE c.task_id=t.task_id)
                        AS candidate_total,
                    (SELECT COUNT(*) FROM memory_candidates c
                     WHERE c.task_id=t.task_id AND c.status='pending') AS pending_candidates,
                    (SELECT COUNT(*) FROM memory_candidates c
                     WHERE c.task_id=t.task_id AND c.status='accepted') AS accepted_candidates,
                    (SELECT COUNT(*) FROM memory_candidates c
                     WHERE c.task_id=t.task_id AND c.status='ignored') AS ignored_candidates
                FROM governance_tasks t{where}
                ORDER BY t.created_at DESC, t.task_id DESC LIMIT ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        tasks = [task for task in self.list_tasks(limit=500) if task["task_id"] == task_id]
        if not tasks:
            return None
        task = tasks[0]
        with self._lock:
            task["records"] = [
                dict(row)
                for row in self._conn.execute(
                    """
                    SELECT * FROM governance_task_records
                    WHERE task_id=? ORDER BY record_id
                    """,
                    (task_id,),
                ).fetchall()
            ]
        return task

    def source_references(self, record_ids: list[str]) -> dict[str, list[Any]]:
        """Return governance and formal-memory references for source records.

        Source deletion uses this public boundary instead of reaching into the store's private
        SQLite connection. Keeping referenced records preserves the provenance shown during
        candidate review and in confirmed-memory details.
        """
        ids = list(dict.fromkeys(str(record_id) for record_id in record_ids if record_id))
        if not ids:
            return {"candidate_ids": [], "memory_ids": []}
        candidate_ids: set[str] = set()
        memory_ids: set[int] = set()
        with self._lock:
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                placeholders = ",".join("?" for _ in chunk)
                candidate_ids.update(
                    str(row["candidate_id"])
                    for row in self._conn.execute(
                        f"SELECT DISTINCT candidate_id FROM candidate_sources "
                        f"WHERE record_id IN ({placeholders})",
                        chunk,
                    ).fetchall()
                )
                memory_ids.update(
                    int(row["memory_id"])
                    for row in self._conn.execute(
                        f"SELECT DISTINCT memory_id FROM memory_sources "
                        f"WHERE record_id IN ({placeholders})",
                        chunk,
                    ).fetchall()
                )
        return {
            "candidate_ids": sorted(candidate_ids),
            "memory_ids": sorted(memory_ids),
        }

    def provenance_for_record(self, record_id: str) -> dict[str, Any]:
        """Return the complete durable chain rooted at one immutable source record."""
        with self._lock:
            candidates = [
                dict(row)
                for row in self._conn.execute(
                    """
                    SELECT c.* FROM memory_candidates c
                    JOIN candidate_sources cs ON cs.candidate_id=c.candidate_id
                    WHERE cs.record_id=? ORDER BY c.created_at, c.candidate_id
                    """,
                    (record_id,),
                ).fetchall()
            ]
            candidate_ids = [str(row["candidate_id"]) for row in candidates]
            decisions: list[dict[str, Any]] = []
            if candidate_ids:
                placeholders = ",".join("?" for _ in candidate_ids)
                decisions = [
                    {
                        **dict(row),
                        "metadata": json.loads(row["metadata_json"] or "{}"),
                    }
                    for row in self._conn.execute(
                        f"""
                        SELECT * FROM governance_decisions
                        WHERE candidate_id IN ({placeholders})
                        ORDER BY created_at, decision_id
                        """,
                        candidate_ids,
                    ).fetchall()
                ]
                for decision in decisions:
                    decision.pop("metadata_json", None)
            memories = [
                dict(row)
                for row in self._conn.execute(
                    """
                    SELECT m.*, ms.candidate_id, ms.created_at AS linked_at
                    FROM memory_sources ms
                    JOIN memories m ON m.id=ms.memory_id
                    WHERE ms.record_id=? ORDER BY m.id
                    """,
                    (record_id,),
                ).fetchall()
            ]
            memory_ids = [int(row["id"]) for row in memories]
            usages: list[dict[str, Any]] = []
            if memory_ids:
                placeholders = ",".join("?" for _ in memory_ids)
                usages = [
                    dict(row)
                    for row in self._conn.execute(
                        f"""
                        SELECT * FROM memory_usage WHERE memory_id IN ({placeholders})
                        ORDER BY used_at DESC
                        """,
                        memory_ids,
                    ).fetchall()
                ]
        return {
            "record_id": record_id,
            "candidates": candidates,
            "decisions": decisions,
            "memories": memories,
            "usages": usages,
        }

    def source_summary(self, project_path: str) -> dict[str, Any]:
        """Aggregate governance output for records captured inside one project."""
        with self._lock:
            candidate_rows = self._conn.execute(
                """
                SELECT c.status, COUNT(DISTINCT c.candidate_id) AS count
                FROM memory_candidates c
                JOIN candidate_sources cs ON cs.candidate_id=c.candidate_id
                JOIN sensory_records sr ON sr.record_id=cs.record_id
                WHERE sr.project_path=? GROUP BY c.status
                """,
                (project_path,),
            ).fetchall()
            memory_rows = self._conn.execute(
                """
                SELECT COALESCE(m.key, 'untyped') AS memory_type,
                       COUNT(DISTINCT m.id) AS count
                FROM memories m
                JOIN memory_sources ms ON ms.memory_id=m.id
                JOIN sensory_records sr ON sr.record_id=ms.record_id
                WHERE sr.project_path=? AND m.status='active'
                GROUP BY COALESCE(m.key, 'untyped')
                """,
                (project_path,),
            ).fetchall()
        candidates = {str(row["status"]): int(row["count"]) for row in candidate_rows}
        memory_types = {
            str(row["memory_type"]): int(row["count"]) for row in memory_rows
        }
        return {
            "candidates": candidates,
            "candidate_total": sum(candidates.values()),
            "memory_types": memory_types,
            "memory_total": sum(memory_types.values()),
        }

    def project_items(self, project_path: str, *, limit: int = 100) -> dict[str, Any]:
        bounded = max(1, min(int(limit), 500))
        with self._lock:
            candidates = [
                dict(row)
                for row in self._conn.execute(
                    """
                    SELECT DISTINCT c.* FROM memory_candidates c
                    JOIN candidate_sources cs ON cs.candidate_id=c.candidate_id
                    JOIN sensory_records sr ON sr.record_id=cs.record_id
                    WHERE sr.project_path=?
                    ORDER BY c.created_at DESC, c.candidate_id DESC LIMIT ?
                    """,
                    (project_path, bounded),
                ).fetchall()
            ]
            memories = [
                dict(row)
                for row in self._conn.execute(
                    """
                    SELECT DISTINCT m.* FROM memories m
                    JOIN memory_sources ms ON ms.memory_id=m.id
                    JOIN sensory_records sr ON sr.record_id=ms.record_id
                    WHERE sr.project_path=? AND m.status='active'
                    ORDER BY m.id DESC LIMIT ?
                    """,
                    (project_path, bounded),
                ).fetchall()
            ]
        return {"candidates": candidates, "memories": memories}

    def decide(
        self,
        candidate_id: str,
        action: str,
        memory_store: MemoryStore,
        *,
        content: Optional[str] = None,
        merge_memory_id: Optional[int] = None,
    ) -> dict[str, Any]:
        candidate = self.get_candidate(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        if candidate.status != "pending":
            task = self.get_task(candidate.task_id)
            return {
                "ok": True,
                "candidate": candidate.to_dict(),
                "idempotent": True,
                "task_status": task["status"] if task else None,
                "pending_count": task["pending_candidates"] if task else 0,
            }
        if action not in {"accept", "edit_accept", "ignore", "merge"}:
            raise ValueError("unsupported governance action")
        final_content = (content or candidate.content).strip()
        if action in {"accept", "edit_accept", "merge"} and not final_content:
            raise ValueError("memory content is required")

        decision_id = _id("decision")
        now = _now()
        status = "ignored" if action == "ignore" else "accepted"
        memory_id: Optional[int] = None
        same_database = (
            getattr(memory_store, "path", None) is not None
            and str(getattr(memory_store, "path")) == self.path
        )
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                if action == "merge":
                    if merge_memory_id is None:
                        raise ValueError("merge_memory_id is required")
                    memory_id = int(merge_memory_id)
                    if same_database:
                        existing = self._conn.execute(
                            "SELECT content FROM memories WHERE id=?", (memory_id,)
                        ).fetchone()
                        if existing is None:
                            raise KeyError(memory_id)
                        self._conn.execute(
                            """
                            UPDATE memories
                            SET content=?, updated_at=CURRENT_TIMESTAMP WHERE id=?
                            """,
                            (final_content, memory_id),
                        )
                        self._conn.execute(
                            """
                            INSERT INTO memory_history (
                                memory_id, old_content, new_content, event
                            ) VALUES (?, ?, ?, 'UPDATE')
                            """,
                            (memory_id, existing["content"], final_content),
                        )
                    else:
                        memory = memory_store.update(memory_id, final_content)
                        if memory is None:
                            raise KeyError(memory_id)
                elif action != "ignore":
                    if same_database:
                        cursor = self._conn.execute(
                            """
                            INSERT INTO memories (
                                scope, key, content, workspace, session_id, status,
                                source_record_id
                            ) VALUES (?, ?, ?, ?, ?, 'active', ?)
                            """,
                            (
                                candidate.scope,
                                candidate.memory_type,
                                final_content,
                                candidate.workspace,
                                candidate.session_id,
                                candidate.sources[0] if candidate.sources else None,
                            ),
                        )
                        memory_id = int(cursor.lastrowid)
                        self._conn.execute(
                            """
                            INSERT INTO memory_history (
                                memory_id, old_content, new_content, event
                            ) VALUES (?, NULL, ?, 'ADD')
                            """,
                            (memory_id, final_content),
                        )
                    else:
                        memory = memory_store.add(
                            final_content,
                            scope=Scope(candidate.scope),
                            key=candidate.memory_type,
                            workspace=candidate.workspace,
                            session_id=candidate.session_id,
                            status="active",
                            source_record_id=(
                                candidate.sources[0] if candidate.sources else None
                            ),
                        )
                        memory_id = memory.id
                self._conn.execute(
                    """
                    INSERT INTO governance_decisions (
                        decision_id, candidate_id, action, original_content, final_content,
                        memory_id, created_at, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision_id,
                        candidate_id,
                        action,
                        candidate.content,
                        final_content if action != "ignore" else None,
                        memory_id,
                        now,
                        json.dumps({"merge_memory_id": merge_memory_id}),
                    ),
                )
                self._conn.execute(
                    "UPDATE memory_candidates SET status=?, updated_at=? WHERE candidate_id=?",
                    (status, now, candidate_id),
                )
                task_status, pending_count = self._refresh_task_status_locked(
                    candidate.task_id
                )
                if memory_id is not None:
                    self._append_version_locked(
                        memory_store,
                        memory_id,
                        decision_id=decision_id,
                        memory_override=(
                            {
                                "content": final_content,
                                "key": candidate.memory_type,
                                "scope": candidate.scope,
                                "workspace": candidate.workspace,
                                "session_id": candidate.session_id,
                                "status": "active",
                            }
                            if same_database
                            else None
                        ),
                    )
                    self._conn.executemany(
                        """
                        INSERT OR IGNORE INTO memory_sources (
                            memory_id, record_id, candidate_id, created_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        [
                            (memory_id, source_id, candidate_id, now)
                            for source_id in candidate.sources
                        ],
                    )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                if not same_database and action != "merge" and memory_id is not None:
                    memory_store.delete(memory_id)
                raise
        updated = self.get_candidate(candidate_id)
        return {
            "ok": True,
            "candidate": updated.to_dict() if updated else None,
            "memory_id": memory_id,
            "decision_id": decision_id,
            "task_status": task_status,
            "pending_count": pending_count,
        }

    def set_memory_status(
        self, memory_store: MemoryStore, memory_id: int, status: str
    ) -> dict[str, Any]:
        if status not in {"active", "archived"}:
            raise ValueError("memory status must be active or archived")
        same_database = (
            getattr(memory_store, "path", None) is not None
            and str(getattr(memory_store, "path")) == self.path
        )
        if not same_database:
            item = memory_store.set_status(memory_id, status)
            if item is None:
                raise KeyError(memory_id)
            with self._lock:
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    self._append_version_locked(
                        memory_store, memory_id, decision_id=None
                    )
                    self._conn.commit()
                except Exception:
                    self._conn.rollback()
                    raise
            return {"memory": item, "idempotent": False}

        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memories WHERE id=?", (memory_id,)
            ).fetchone()
            if row is None:
                raise KeyError(memory_id)
            if row["status"] == status:
                item = memory_store.get(memory_id)
                return {"memory": item, "idempotent": True}
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute(
                    "UPDATE memories SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (status, memory_id),
                )
                self._conn.execute(
                    """
                    INSERT INTO memory_history (
                        memory_id, old_content, new_content, event
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        memory_id,
                        row["content"],
                        row["content"],
                        "ARCHIVE" if status == "archived" else "RESTORE",
                    ),
                )
                self._append_version_locked(
                    memory_store,
                    memory_id,
                    decision_id=None,
                    memory_override={
                        "content": row["content"],
                        "key": row["key"],
                        "scope": row["scope"],
                        "workspace": row["workspace"],
                        "session_id": row["session_id"],
                        "status": status,
                    },
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        item = memory_store.get(memory_id)
        return {"memory": item, "idempotent": False}

    def record_usage(
        self,
        memory_id: int,
        *,
        session_id: Optional[str],
        workspace: Optional[str],
    ) -> None:
        with self._lock:
            version = self._conn.execute(
                """
                SELECT version_id FROM memory_versions
                WHERE memory_id=? ORDER BY version DESC LIMIT 1
                """,
                (memory_id,),
            ).fetchone()
            self._conn.execute(
                """
                INSERT INTO memory_usage (
                    usage_id, memory_id, version_id, session_id, workspace, used_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    _id("usage"),
                    memory_id,
                    version["version_id"] if version else None,
                    session_id,
                    workspace,
                    _now(),
                ),
            )
            self._conn.commit()

    def query_usage_history(
        self, *, limit: int = 50, memory_id: Optional[int] = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            if memory_id is not None:
                rows = self._conn.execute(
                    """
                    SELECT u.usage_id, u.memory_id, u.session_id, u.workspace, u.used_at,
                           m.content, m.key
                    FROM memory_usage u
                    LEFT JOIN memories m ON m.id = u.memory_id
                    WHERE u.memory_id = ?
                    ORDER BY u.used_at DESC LIMIT ?
                    """,
                    (memory_id, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT u.usage_id, u.memory_id, u.session_id, u.workspace, u.used_at,
                           m.content, m.key
                    FROM memory_usage u
                    LEFT JOIN memories m ON m.id = u.memory_id
                    ORDER BY u.used_at DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def finish_task(self, task_id: str) -> dict[str, Any]:
        with self._lock:
            counts = {
                row["status"]: int(row["count"])
                for row in self._conn.execute(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM governance_task_records WHERE task_id=? GROUP BY status
                    """,
                    (task_id,),
                ).fetchall()
            }
            candidates = int(
                self._conn.execute(
                    "SELECT COUNT(*) FROM memory_candidates WHERE task_id=?", (task_id,)
                ).fetchone()[0]
            )
            pending_candidates = int(
                self._conn.execute(
                    "SELECT COUNT(*) FROM memory_candidates WHERE task_id=? AND status='pending'",
                    (task_id,),
                ).fetchone()[0]
            )
            status = "failed" if counts.get("failed", 0) and not (
                counts.get("processed", 0) or counts.get("skipped", 0)
            ) else ("reviewing" if pending_candidates else "completed")
            now = _now()
            self._conn.execute(
                """
                UPDATE governance_tasks
                SET status=?, processed_records=?, candidates_created=?, skipped_records=?,
                    failed_records=?, updated_at=?
                WHERE task_id=?
                """,
                (
                    status,
                    counts.get("processed", 0),
                    candidates,
                    counts.get("skipped", 0),
                    counts.get("failed", 0),
                    now,
                    task_id,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM governance_tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        return dict(row)

    def _append_version_locked(
        self,
        memory_store: MemoryStore,
        memory_id: int,
        *,
        decision_id: Optional[str],
        memory_override: Optional[dict[str, Any]] = None,
    ) -> None:
        memory = memory_store.get(memory_id) if memory_override is None else None
        if memory is None and memory_override is None:
            raise KeyError(memory_id)
        version = int(
            self._conn.execute(
                "SELECT COALESCE(MAX(version), 0) FROM memory_versions WHERE memory_id=?",
                (memory_id,),
            ).fetchone()[0]
        ) + 1
        self._conn.execute(
            """
            INSERT INTO memory_versions (
                version_id, memory_id, version, content, memory_type, scope, workspace,
                session_id, status, created_at, decision_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _id("memory-version"),
                memory_id,
                version,
                memory_override["content"] if memory_override else memory.content,
                memory_override["key"] if memory_override else memory.key,
                memory_override["scope"] if memory_override else memory.scope.value,
                memory_override["workspace"] if memory_override else memory.workspace,
                memory_override["session_id"] if memory_override else memory.session_id,
                memory_override["status"] if memory_override else memory.status,
                _now(),
                decision_id,
            ),
        )

    def _refresh_task_status_locked(self, task_id: str) -> tuple[str, int]:
        pending = int(
            self._conn.execute(
                "SELECT COUNT(*) FROM memory_candidates WHERE task_id=? AND status='pending'",
                (task_id,),
            ).fetchone()[0]
        )
        status = "reviewing" if pending else "completed"
        self._conn.execute(
            "UPDATE governance_tasks SET status=?, updated_at=? WHERE task_id=?",
            (status, _now(), task_id),
        )
        return status, pending

    def _candidate(self, row) -> MemoryCandidate:
        with self._lock:
            sources = [
                str(source["record_id"])
                for source in self._conn.execute(
                    "SELECT record_id FROM candidate_sources WHERE candidate_id=? ORDER BY record_id",
                    (row["candidate_id"],),
                ).fetchall()
            ]
        return MemoryCandidate(
            candidate_id=row["candidate_id"],
            task_id=row["task_id"],
            content=row["content"],
            memory_type=row["memory_type"],
            scope=row["scope"],
            workspace=row["workspace"],
            session_id=row["session_id"],
            status=row["status"],
            confidence=row["confidence"],
            model=row["model"],
            prompt_version=row["prompt_version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            sources=sources,
            error=row["error"],
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
