"""SQLite adapter for Smallink's durable task and agent-run runtime.

The domain API is intentionally storage-agnostic. SQLite keeps the first vertical
slice lightweight; a Postgres adapter can replace it without changing TurnEngine.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..sqlite import connect_sqlite
from .models import AgentRunRecord, RunEventRecord, TaskRecord, TaskRunRecord

_ACTIVE_STATUSES = {"running", "waiting_approval"}
_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _load(value: Optional[str]) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


class SQLiteTaskRuntimeStore:
    """Thread-safe durable runtime records stored alongside the existing Smallink DB."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = connect_sqlite(self.db_path)
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runtime_tasks (
                task_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                project_id TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runtime_task_runs (
                task_run_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES runtime_tasks(task_id) ON DELETE CASCADE,
                trigger TEXT NOT NULL,
                status TEXT NOT NULL,
                model TEXT,
                mode TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS runtime_agent_runs (
                agent_run_id TEXT PRIMARY KEY,
                task_run_id TEXT NOT NULL
                    REFERENCES runtime_task_runs(task_run_id) ON DELETE CASCADE,
                parent_agent_run_id TEXT
                    REFERENCES runtime_agent_runs(agent_run_id) ON DELETE CASCADE,
                root_agent_run_id TEXT NOT NULL,
                agent_role TEXT NOT NULL,
                status TEXT NOT NULL,
                model TEXT,
                input_json TEXT,
                output_json TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                error TEXT
            );
            CREATE TABLE IF NOT EXISTS runtime_agent_run_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                agent_run_id TEXT NOT NULL
                    REFERENCES runtime_agent_runs(agent_run_id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                data_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_runtime_tasks_updated
                ON runtime_tasks(updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_runtime_task_runs_task
                ON runtime_task_runs(task_id, started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_runtime_agent_runs_task_run
                ON runtime_agent_runs(task_run_id, started_at);
            CREATE INDEX IF NOT EXISTS idx_runtime_agent_events_run
                ON runtime_agent_run_events(agent_run_id, sequence);
            """
        )
        self._conn.commit()

    def ensure_task(
        self,
        *,
        session_id: str,
        title: str,
        project_id: Optional[str] = None,
    ) -> TaskRecord:
        clean_title = " ".join((title or "").split())[:120] or "New task"
        now = _now()
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runtime_tasks WHERE session_id = ?", (session_id,)
            ).fetchone()
            if row is None:
                self._conn.execute(
                    """
                    INSERT INTO runtime_tasks (
                        task_id, session_id, title, project_id, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    (_id("task"), session_id, clean_title, project_id, now, now),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE runtime_tasks
                    SET title = ?, project_id = COALESCE(?, project_id), updated_at = ?
                    WHERE session_id = ?
                    """,
                    (clean_title, project_id, now, session_id),
                )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM runtime_tasks WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._task(row)

    def repair_legacy_project_ids(self) -> int:
        """Replace legacy workspace paths in runtime_tasks.project_id with project UUIDs.

        Older builds stored the executor cwd in this column. Sessions and projects live in the
        same database, so the migration can resolve a stable UUID without guessing by title.
        Unresolvable non-UUID values become NULL instead of pretending to reference a project.
        """
        with self._lock:
            tables = {
                row["name"]
                for row in self._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if not {"sessions", "projects"}.issubset(tables):
                return 0
            cursor = self._conn.execute(
                """
                UPDATE runtime_tasks
                SET project_id = COALESCE(
                    (SELECT s.project_id FROM sessions s
                     WHERE s.session_id = runtime_tasks.session_id
                       AND s.project_id IS NOT NULL),
                    (SELECT p.project_id FROM projects p
                     WHERE p.workspace_path = runtime_tasks.project_id)
                )
                WHERE project_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM projects p WHERE p.project_id = runtime_tasks.project_id
                  )
                """
            )
            self._conn.commit()
            return max(cursor.rowcount, 0)

    def start_root_run(
        self,
        *,
        session_id: str,
        title: str,
        trigger: str,
        agent_role: str,
        model: Optional[str],
        mode: Optional[str],
        input_value: Any,
        project_id: Optional[str] = None,
    ) -> tuple[TaskRunRecord, AgentRunRecord]:
        task = self.ensure_task(
            session_id=session_id, title=title, project_id=project_id
        )
        now = _now()
        task_run_id = _id("run")
        agent_run_id = _id("agent")
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO runtime_task_runs (
                    task_run_id, task_id, trigger, status, model, mode, started_at
                ) VALUES (?, ?, ?, 'running', ?, ?, ?)
                """,
                (task_run_id, task.task_id, trigger, model, mode, now),
            )
            self._conn.execute(
                """
                INSERT INTO runtime_agent_runs (
                    agent_run_id, task_run_id, parent_agent_run_id, root_agent_run_id,
                    agent_role, status, model, input_json, started_at
                ) VALUES (?, ?, NULL, ?, ?, 'running', ?, ?, ?)
                """,
                (
                    agent_run_id,
                    task_run_id,
                    agent_run_id,
                    agent_role,
                    model,
                    _dump(input_value),
                    now,
                ),
            )
            self._conn.execute(
                """
                UPDATE runtime_tasks SET status = 'running', updated_at = ?
                WHERE task_id = ?
                """,
                (now, task.task_id),
            )
            self._conn.commit()
        return self.get_task_run(task_run_id), self.get_agent_run(agent_run_id)

    def start_child_run(
        self,
        *,
        parent_agent_run_id: str,
        agent_role: str,
        model: Optional[str],
        input_value: Any,
    ) -> AgentRunRecord:
        parent = self.get_agent_run(parent_agent_run_id)
        if parent.status not in _ACTIVE_STATUSES:
            raise ValueError("parent agent run is not active")
        now = _now()
        agent_run_id = _id("agent")
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO runtime_agent_runs (
                    agent_run_id, task_run_id, parent_agent_run_id, root_agent_run_id,
                    agent_role, status, model, input_json, started_at
                ) VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?)
                """,
                (
                    agent_run_id,
                    parent.task_run_id,
                    parent.agent_run_id,
                    parent.root_agent_run_id,
                    agent_role,
                    model,
                    _dump(input_value),
                    now,
                ),
            )
            self._conn.commit()
        return self.get_agent_run(agent_run_id)

    def active_root_for_session(self, session_id: str) -> Optional[AgentRunRecord]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT ar.*
                FROM runtime_agent_runs ar
                JOIN runtime_task_runs tr ON tr.task_run_id = ar.task_run_id
                JOIN runtime_tasks t ON t.task_id = tr.task_id
                WHERE t.session_id = ?
                  AND ar.parent_agent_run_id IS NULL
                  AND ar.status IN ('running', 'waiting_approval')
                ORDER BY ar.started_at DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        return self._agent_run(row) if row else None

    def resume_waiting_root(self, session_id: str) -> Optional[AgentRunRecord]:
        root = self.active_root_for_session(session_id)
        if root is None or root.status != "waiting_approval":
            return None
        now = _now()
        with self._lock:
            self._conn.execute(
                """
                UPDATE runtime_agent_runs SET status='running', error=NULL
                WHERE agent_run_id=? AND status='waiting_approval'
                """,
                (root.agent_run_id,),
            )
            self._conn.execute(
                """
                UPDATE runtime_task_runs SET status='running', error=NULL
                WHERE task_run_id=? AND status='waiting_approval'
                """,
                (root.task_run_id,),
            )
            self._conn.execute(
                """
                UPDATE runtime_tasks SET status='running', updated_at=?
                WHERE task_id=(
                    SELECT task_id FROM runtime_task_runs WHERE task_run_id=?
                )
                """,
                (now, root.task_run_id),
            )
            self._conn.commit()
        return self.get_agent_run(root.agent_run_id)

    def recover_incomplete_runs(
        self, *, reason: str = "Smallink restarted before the run completed"
    ) -> int:
        """Cancel active execution while preserving resumable approval suspensions."""
        now = _now()
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT agent_run_id FROM runtime_agent_runs
                WHERE status = 'running'
                """
            ).fetchall()
            if not rows:
                return 0
            self._conn.execute(
                """
                UPDATE runtime_agent_runs
                SET status = 'cancelled', finished_at = ?, error = COALESCE(error, ?)
                WHERE status = 'running'
                """,
                (now, reason),
            )
            self._conn.execute(
                """
                UPDATE runtime_task_runs
                SET status = 'cancelled', finished_at = ?, error = COALESCE(error, ?)
                WHERE status = 'running'
                  AND NOT EXISTS (
                      SELECT 1 FROM runtime_agent_runs ar
                      WHERE ar.task_run_id = runtime_task_runs.task_run_id
                        AND ar.status = 'waiting_approval'
                  )
                """,
                (now, reason),
            )
            self._conn.execute(
                """
                UPDATE runtime_tasks
                SET status = CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM runtime_task_runs tr
                        JOIN runtime_agent_runs ar ON ar.task_run_id = tr.task_run_id
                        WHERE tr.task_id = runtime_tasks.task_id
                          AND ar.status = 'waiting_approval'
                    ) THEN 'waiting_approval'
                    ELSE 'cancelled'
                END,
                updated_at = ?
                WHERE status IN ('running', 'waiting_approval')
                """,
                (now,),
            )
            self._conn.commit()
        return len(rows)

    def append_event(
        self, agent_run_id: str, event_type: str, data: Optional[dict[str, Any]] = None
    ) -> RunEventRecord:
        now = _now()
        event_id = _id("event")
        payload = data or {}
        waiting = event_type in {
            "permission_required",
            "directory_requested",
            "question_requested",
            "plan_proposed",
        }
        with self._lock:
            self._require_agent_run(agent_run_id)
            cursor = self._conn.execute(
                """
                INSERT INTO runtime_agent_run_events (
                    event_id, agent_run_id, event_type, data_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (event_id, agent_run_id, event_type, _dump(payload), now),
            )
            if waiting:
                self._set_running_status(agent_run_id, "waiting_approval", now)
            elif event_type in {"turn_start", "tool_started", "assistant_delta"}:
                self._set_running_status(agent_run_id, "running", now)
            self._conn.commit()
            sequence = int(cursor.lastrowid)
        return RunEventRecord(
            event_id=event_id,
            agent_run_id=agent_run_id,
            sequence=sequence,
            event_type=event_type,
            data=payload,
            created_at=now,
        )

    def finish_agent_run(
        self,
        agent_run_id: str,
        *,
        status: str,
        output: Any = None,
        error: Optional[str] = None,
    ) -> AgentRunRecord:
        if status not in _TERMINAL_STATUSES:
            raise ValueError(f"invalid terminal status: {status}")
        now = _now()
        with self._lock:
            row = self._require_agent_run(agent_run_id)
            self._conn.execute(
                """
                UPDATE runtime_agent_runs
                SET status = ?, output_json = ?, finished_at = ?, error = ?
                WHERE agent_run_id = ?
                """,
                (status, _dump(output), now, error, agent_run_id),
            )
            if row["parent_agent_run_id"] is None:
                self._conn.execute(
                    """
                    UPDATE runtime_task_runs
                    SET status = ?, finished_at = ?, error = ?
                    WHERE task_run_id = ?
                    """,
                    (status, now, error, row["task_run_id"]),
                )
                self._conn.execute(
                    """
                    UPDATE runtime_tasks
                    SET status = ?, updated_at = ?
                    WHERE task_id = (
                        SELECT task_id FROM runtime_task_runs WHERE task_run_id = ?
                    )
                    """,
                    (status, now, row["task_run_id"]),
                )
            self._conn.commit()
        return self.get_agent_run(agent_run_id)

    def list_tasks(
        self, *, limit: int = 100, project_id: Optional[str] = None
    ) -> list[TaskRecord]:
        query = "SELECT * FROM runtime_tasks"
        params: list[Any] = []
        if project_id is not None:
            query += " WHERE project_id=?"
            params.append(project_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._task(row) for row in rows]

    def list_collaborative_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return task runs that contain at least one delegated child agent.

        The client uses this compact projection for the collaboration index. Keeping the
        aggregation in SQLite avoids fetching every task and run just to discover whether a
        child AgentRun exists.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT
                    t.task_id,
                    t.session_id,
                    t.title,
                    t.project_id,
                    tr.task_run_id,
                    tr.trigger,
                    tr.status,
                    tr.model,
                    tr.mode,
                    tr.started_at,
                    tr.finished_at,
                    tr.error,
                    COUNT(ar.agent_run_id) AS agent_count,
                    SUM(CASE WHEN ar.parent_agent_run_id IS NOT NULL THEN 1 ELSE 0 END)
                        AS child_agent_count,
                    GROUP_CONCAT(DISTINCT ar.agent_role) AS agent_roles
                FROM runtime_task_runs tr
                JOIN runtime_tasks t ON t.task_id = tr.task_id
                JOIN runtime_agent_runs ar ON ar.task_run_id = tr.task_run_id
                GROUP BY tr.task_run_id
                HAVING child_agent_count > 0
                ORDER BY tr.started_at DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [
            {
                **dict(row),
                "agent_count": int(row["agent_count"] or 0),
                "child_agent_count": int(row["child_agent_count"] or 0),
                "agent_roles": [
                    role for role in str(row["agent_roles"] or "").split(",") if role
                ],
            }
            for row in rows
        ]

    def get_task(self, task_id: str) -> TaskRecord:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runtime_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._task(row)

    def get_task_by_session(self, session_id: str) -> Optional[TaskRecord]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runtime_tasks WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._task(row) if row else None

    def list_task_runs(self, task_id: str) -> list[TaskRunRecord]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM runtime_task_runs
                WHERE task_id = ? ORDER BY started_at DESC
                """,
                (task_id,),
            ).fetchall()
        return [self._task_run(row) for row in rows]

    def get_task_run(self, task_run_id: str) -> TaskRunRecord:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runtime_task_runs WHERE task_run_id = ?",
                (task_run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(task_run_id)
        return self._task_run(row)

    def list_agent_runs(self, task_run_id: str) -> list[AgentRunRecord]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM runtime_agent_runs
                WHERE task_run_id = ? ORDER BY started_at, agent_run_id
                """,
                (task_run_id,),
            ).fetchall()
        return [self._agent_run(row) for row in rows]

    def get_agent_run(self, agent_run_id: str) -> AgentRunRecord:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM runtime_agent_runs WHERE agent_run_id = ?",
                (agent_run_id,),
            ).fetchone()
        if row is None:
            raise KeyError(agent_run_id)
        return self._agent_run(row)

    def list_events(self, agent_run_id: str) -> list[RunEventRecord]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM runtime_agent_run_events
                WHERE agent_run_id = ? ORDER BY sequence
                """,
                (agent_run_id,),
            ).fetchall()
        return [self._event(row) for row in rows]

    def _set_running_status(self, agent_run_id: str, status: str, now: str) -> None:
        self._conn.execute(
            """
            UPDATE runtime_agent_runs SET status = ?
            WHERE agent_run_id = ? AND status IN ('running', 'waiting_approval')
            """,
            (status, agent_run_id),
        )
        self._conn.execute(
            """
            UPDATE runtime_task_runs SET status = ?
            WHERE task_run_id = (
                SELECT task_run_id FROM runtime_agent_runs WHERE agent_run_id = ?
            ) AND status IN ('running', 'waiting_approval')
            """,
            (status, agent_run_id),
        )
        self._conn.execute(
            """
            UPDATE runtime_tasks SET status = ?, updated_at = ?
            WHERE task_id = (
                SELECT tr.task_id
                FROM runtime_task_runs tr
                JOIN runtime_agent_runs ar ON ar.task_run_id = tr.task_run_id
                WHERE ar.agent_run_id = ?
            )
            """,
            (status, now, agent_run_id),
        )

    def _require_agent_run(self, agent_run_id: str) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM runtime_agent_runs WHERE agent_run_id = ?",
            (agent_run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(agent_run_id)
        return row

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _task(row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            task_id=row["task_id"],
            session_id=row["session_id"],
            title=row["title"],
            status=row["status"],
            project_id=row["project_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _task_run(row: sqlite3.Row) -> TaskRunRecord:
        return TaskRunRecord(
            task_run_id=row["task_run_id"],
            task_id=row["task_id"],
            trigger=row["trigger"],
            status=row["status"],
            model=row["model"],
            mode=row["mode"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            error=row["error"],
        )

    @staticmethod
    def _agent_run(row: sqlite3.Row) -> AgentRunRecord:
        return AgentRunRecord(
            agent_run_id=row["agent_run_id"],
            task_run_id=row["task_run_id"],
            parent_agent_run_id=row["parent_agent_run_id"],
            root_agent_run_id=row["root_agent_run_id"],
            agent_role=row["agent_role"],
            status=row["status"],
            model=row["model"],
            input=_load(row["input_json"]),
            output=_load(row["output_json"]),
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            error=row["error"],
        )

    @staticmethod
    def _event(row: sqlite3.Row) -> RunEventRecord:
        return RunEventRecord(
            event_id=row["event_id"],
            agent_run_id=row["agent_run_id"],
            sequence=int(row["sequence"]),
            event_type=row["event_type"],
            data=_load(row["data_json"]) or {},
            created_at=row["created_at"],
        )
