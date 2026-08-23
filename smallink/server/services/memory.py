"""Memory, sensory, knowledge, and governance application service.

The service deliberately owns orchestration only. Stores and integration callbacks are
provided by the composition root, keeping this module independent from SessionManager
while preserving the manager's existing response contracts.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, MutableMapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from ...memory import MemoryPipeline, MemoryStore
from ...runtime import sensory_safe, sensory_sensitivity


logger = logging.getLogger("smallink.memory_service")


class MemoryService:
    """Coordinate memory-domain stores without depending on the server manager."""

    INGEST_OPTIONAL = (
        "external_id",
        "normalized_content",
        "occurred_at",
        "connector_id",
        "account_id",
        "project_path",
        "conversation_id",
        "sensitivity",
        "source_locator",
    )

    KNOWLEDGE_CONTENT_TYPES = {
        "app_capability_result",
        "document",
        "document_text",
        "artifact",
        "file_content",
        "web_page",
        "meeting_transcript",
    }

    def __init__(
        self,
        *,
        sensory_store: Any,
        memory_store: MemoryStore,
        governance_store: Any,
        knowledge_store: Any,
        provider: Any,
        model_for_purpose: Callable[[str], str],
        get_project: Callable[[str], Any | None],
        get_project_by_workspace: Callable[[str], Any | None],
        preferences: MutableMapping[str, Any],
        save_preferences: Callable[[], None],
        broadcast_event: Callable[[dict[str, Any]], Awaitable[None]],
        connector_sync_store: Any | None = None,
        secret_lookup: Callable[[str], dict[str, Any] | None] | None = None,
        pipeline_factory: Callable[..., Any] = MemoryPipeline,
        sanitize_sensory: Callable[[Any], Any] = sensory_safe,
        classify_sensitivity: Callable[[Any], str] = sensory_sensitivity,
        now: Callable[[], datetime] | None = None,
        scheduler_interval_seconds: float = 15.0,
    ) -> None:
        self.sensory_store = sensory_store
        self.memory_store = memory_store
        self.governance_store = governance_store
        self.knowledge_store = knowledge_store
        self.provider = provider
        self._model_for_purpose = model_for_purpose
        self._get_project = get_project
        self._get_project_by_workspace = get_project_by_workspace
        self._preferences = preferences
        self._save_preferences = save_preferences
        self._broadcast_event = broadcast_event
        self.connector_sync_store = connector_sync_store
        self._secret_lookup = secret_lookup
        self._pipeline_factory = pipeline_factory
        self._sanitize_sensory = sanitize_sensory
        self._classify_sensitivity = classify_sensitivity
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._scheduler_interval_seconds = scheduler_interval_seconds
        self._governance_scheduler_task: asyncio.Task[None] | None = None
        self._governance_schedule_running = False

    # -- Sensory records -----------------------------------------------------

    def sensory_records(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        source_type: Optional[str] = None,
        governance_status: Optional[str] = None,
        conversation_id: Optional[str] = None,
        project_path: Optional[str] = None,
        query: Optional[str] = None,
    ) -> dict[str, Any]:
        filters = {
            "source_type": source_type,
            "governance_status": governance_status,
            "conversation_id": conversation_id,
            "project_path": project_path,
            "query": query,
        }
        records = self.sensory_store.list(limit=limit, offset=offset, **filters)
        return {
            "records": [record.to_dict() for record in records],
            "total": self.sensory_store.count(**filters),
            "limit": max(1, min(int(limit), 500)),
            "offset": max(0, int(offset)),
        }

    def sensory_record(self, record_id: str) -> Optional[dict[str, Any]]:
        record = self.sensory_store.get(record_id)
        return record.to_dict() if record else None

    def sensory_provenance(self, record_id: str) -> Optional[dict[str, Any]]:
        record = self.sensory_store.get(record_id)
        if record is None:
            return None
        return {
            "source": record.to_dict(),
            **self.governance_store.provenance_for_record(record_id),
        }

    def ingest_sensory_record(self, body: dict[str, Any]) -> dict[str, Any]:
        """Validate, sanitize, classify, and idempotently ingest one source record."""
        for required in ("source_type", "content_type", "raw_content"):
            if not body.get(required):
                raise ValueError(f"missing required field: {required}")
        kwargs: dict[str, Any] = {
            "source_type": str(body["source_type"]),
            "content_type": str(body["content_type"]),
            "raw_content": self._sanitize_sensory(body["raw_content"]),
            "sensitivity": self._classify_sensitivity(body["raw_content"]),
        }
        for field in self.INGEST_OPTIONAL:
            if body.get(field) is not None:
                kwargs[field] = body[field]
        metadata = body.get("metadata")
        if isinstance(metadata, dict):
            kwargs["metadata"] = self._sanitize_sensory(metadata)
        record = self.sensory_store.add(**kwargs)
        return {
            "record_id": record.record_id,
            "external_id": record.external_id,
            "content_hash": record.content_hash,
            "governance_status": record.governance_status,
            "ingested_at": record.ingested_at,
        }

    def delete_sensory_records(
        self,
        *,
        record_ids: Optional[list[str]] = None,
        source_type: Optional[str] = None,
        before: Optional[str] = None,
    ) -> dict[str, Any]:
        ids = list(dict.fromkeys(record_ids or []))
        affected_candidates: set[str] = set()
        affected_memories: set[int] = set()
        selected_ids = self.sensory_store.matching_ids(
            record_ids=ids, source_type=source_type, before=before
        )
        if selected_ids:
            references = self.governance_store.source_references(selected_ids)
            affected_candidates = set(references["candidate_ids"])
            affected_memories = set(references["memory_ids"])
            if affected_candidates or affected_memories:
                raise ValueError(
                    "source record is referenced by memory governance and cannot be deleted"
                )
        deleted = 0
        if selected_ids:
            if ids:
                for start in range(0, len(ids), 500):
                    deleted += self.sensory_store.delete(
                        record_ids=ids[start : start + 500],
                        source_type=source_type,
                        before=before,
                    )
            else:
                deleted = self.sensory_store.delete(
                    source_type=source_type, before=before
                )
        return {
            "ok": True,
            "deleted_records": deleted,
            "affected_candidates": sorted(affected_candidates),
            "affected_memories": sorted(affected_memories),
        }

    # -- Project knowledge ---------------------------------------------------

    def knowledge_items(
        self, *, project_id: Optional[str] = None, status: Optional[str] = "active"
    ) -> list[dict[str, Any]]:
        if project_id is not None and self._get_project(project_id) is None:
            raise KeyError(project_id)
        return self.knowledge_store.list(
            project_id=project_id, status=status, limit=500
        )

    def knowledge_item(self, item_id: str) -> Optional[dict[str, Any]]:
        return self.knowledge_store.get(item_id)

    def index_knowledge_source(
        self,
        record_id: str,
        *,
        project_id: Optional[str] = None,
        title: str = "",
    ) -> dict[str, Any]:
        record = self.sensory_store.get(record_id)
        if record is None:
            raise KeyError(record_id)
        project = self._get_project(project_id) if project_id else None
        if project_id and project is None:
            raise KeyError(project_id)
        if project is None and record.project_path:
            project = self._get_project_by_workspace(record.project_path)
        content = record.normalized_content or record.raw_content
        inferred = " ".join(content.replace("\n", " ").split())[:120]
        item = self.knowledge_store.upsert(
            project_id=self._project_value(project, "project_id") or project_id,
            source_type=f"sensory:{record.source_type}",
            external_id=record.record_id,
            title=title.strip() or inferred or record.content_type,
            content=content,
            source_record_id=record.record_id,
            metadata={
                "content_type": record.content_type,
                "source_type": record.source_type,
                "source_locator": record.source_locator,
                "conversation_id": record.conversation_id,
            },
        )
        return {"ok": True, "item": item}

    def index_project_knowledge(self, project_id: str) -> dict[str, Any]:
        project = self._get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        records = self.sensory_store.list(
            project_path=self._project_value(project, "workspace_path"), limit=500
        )
        indexed: list[str] = []
        skipped = 0
        for record in records:
            if record.content_type not in self.KNOWLEDGE_CONTENT_TYPES:
                skipped += 1
                continue
            result = self.index_knowledge_source(
                record.record_id, project_id=project_id
            )
            indexed.append(str(result["item"]["item_id"]))
        return {
            "ok": True,
            "project_id": project_id,
            "indexed": len(set(indexed)),
            "skipped": skipped,
            "item_ids": list(dict.fromkeys(indexed)),
        }

    def search_knowledge(
        self,
        query: str,
        *,
        project_id: Optional[str] = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        if project_id is not None and self._get_project(project_id) is None:
            raise KeyError(project_id)
        return self.knowledge_store.search(
            query, project_id=project_id, limit=limit
        )

    def archive_knowledge_item(
        self, item_id: str, archived: bool
    ) -> dict[str, Any]:
        if self.knowledge_store.get(item_id) is None:
            raise KeyError(item_id)
        self.knowledge_store.archive(item_id, archived=archived)
        return {"ok": True, "item": self.knowledge_store.get(item_id)}

    # -- Pipeline and schedule ----------------------------------------------

    def run_memory_pipeline(
        self,
        record_ids: Optional[list[str]] = None,
        limit: int = 50,
        retry_failed: bool = False,
        allow_sensitive_cloud: bool = False,
    ) -> dict[str, Any]:
        pipeline = self._pipeline_factory(
            self.sensory_store,
            self.memory_store,
            self.provider,
            model=self._model_for_purpose("memory"),
            governance_store=self.governance_store,
            allow_sensitive_cloud=allow_sensitive_cloud,
        )
        return pipeline.process(
            record_ids=record_ids, limit=limit, retry_failed=retry_failed
        )

    def governance_schedule(self) -> dict[str, Any]:
        raw = self._preferences.get("governance_schedule")
        config = raw if isinstance(raw, dict) else {}
        interval = max(
            15, min(int(config.get("interval_minutes", 1440)), 10080)
        )
        last_run_at = config.get("last_run_at")
        next_run_at: Optional[str] = None
        if bool(config.get("enabled", False)):
            try:
                last = (
                    datetime.fromisoformat(str(last_run_at))
                    if last_run_at
                    else self._utc_now()
                )
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                next_run_at = (last + timedelta(minutes=interval)).isoformat()
            except (TypeError, ValueError):
                next_run_at = self._utc_now().isoformat()
        return {
            "enabled": bool(config.get("enabled", False)),
            "interval_minutes": interval,
            "batch_limit": max(
                1, min(int(config.get("batch_limit", 50)), 500)
            ),
            "last_run_at": last_run_at,
            "next_run_at": next_run_at,
            "last_result": config.get("last_result"),
            "running": self._governance_schedule_running,
        }

    def set_governance_schedule(self, body: dict[str, Any]) -> dict[str, Any]:
        current = self.governance_schedule()
        enabled = bool(body.get("enabled", current["enabled"]))
        try:
            interval = int(
                body.get("interval_minutes", current["interval_minutes"])
            )
            batch_limit = int(body.get("batch_limit", current["batch_limit"]))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "governance schedule values must be integers"
            ) from exc
        if not 15 <= interval <= 10080:
            raise ValueError("interval_minutes must be between 15 and 10080")
        if not 1 <= batch_limit <= 500:
            raise ValueError("batch_limit must be between 1 and 500")
        previous = self._preferences.get("governance_schedule")
        preserved = previous if isinstance(previous, dict) else {}
        self._preferences["governance_schedule"] = {
            **preserved,
            "enabled": enabled,
            "interval_minutes": interval,
            "batch_limit": batch_limit,
        }
        self._save_preferences()
        return self.governance_schedule()

    def start_governance_scheduler(self) -> None:
        task = self._governance_scheduler_task
        if task is None or task.done():
            self._governance_scheduler_task = asyncio.create_task(
                self._governance_scheduler_loop(),
                name="smallink-governance-scheduler",
            )

    async def stop_governance_scheduler(self) -> None:
        task = self._governance_scheduler_task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._governance_scheduler_task = None

    async def _governance_scheduler_loop(self) -> None:
        while True:
            try:
                await self.run_scheduled_governance_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduled memory governance failed")
            await asyncio.sleep(self._scheduler_interval_seconds)

    async def run_scheduled_governance_once(
        self, *, force: bool = False
    ) -> dict[str, Any]:
        config = self.governance_schedule()
        if self._governance_schedule_running:
            return {"status": "skipped", "reason": "already_running"}
        if not force and not config["enabled"]:
            return {"status": "skipped", "reason": "disabled"}
        if not force and config["next_run_at"]:
            try:
                due = datetime.fromisoformat(str(config["next_run_at"]))
                if due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
                if due > self._utc_now():
                    return {"status": "skipped", "reason": "not_due"}
            except ValueError:
                pass
        pending = self.sensory_store.count(governance_status="pending")
        if pending == 0:
            return {"status": "skipped", "reason": "no_pending_records"}
        self._governance_schedule_running = True
        try:
            result = await asyncio.to_thread(
                self.run_memory_pipeline,
                None,
                int(config["batch_limit"]),
                False,
                False,
            )
            # Scheduled extraction only creates reviewable candidates. Promotion to formal
            # memory always requires an explicit user action through a decision endpoint.
            result["auto_accepted"] = 0
            stored = self._preferences.get("governance_schedule")
            schedule = stored if isinstance(stored, dict) else {}
            schedule["last_run_at"] = self._utc_now().isoformat()
            schedule["last_result"] = result
            self._preferences["governance_schedule"] = schedule
            self._save_preferences()
            await self._broadcast_event(
                {"type": "governance_task_updated", "data": result}
            )
            return {"status": "ran", "result": result}
        finally:
            self._governance_schedule_running = False

    # -- Candidates, decisions, and formal memory ---------------------------

    def list_memory(
        self, *, status: Optional[str] = "active"
    ) -> list[dict[str, Any]]:
        """List formal memories; pending candidates never enter this store."""
        return [
            self._memory_to_dict(memory)
            for memory in self.memory_store.list(status=status)
        ]

    def memory_candidates(
        self,
        status: Optional[str] = "pending",
        *,
        min_confidence: Optional[float] = None,
        max_confidence: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        return [
            candidate.to_dict()
            for candidate in self.governance_store.list_candidates(
                status=status,
                min_confidence=min_confidence,
                max_confidence=max_confidence,
            )
        ]

    def auto_accept_high_confidence(
        self, threshold: float = 0.9, *, confirmed: bool = False
    ) -> dict[str, Any]:
        if not confirmed:
            raise PermissionError("explicit confirmation is required")
        return self.governance_store.auto_accept_high_confidence(
            self.memory_store, threshold=threshold
        )

    def memory_confidence_summary(self) -> dict[str, Any]:
        candidates = self.governance_store.list_candidates("pending")
        tiers = {"high": 0, "medium": 0, "low": 0, "unscored": 0}
        for candidate in candidates:
            if candidate.confidence is None:
                tiers["unscored"] += 1
            elif candidate.confidence >= 0.8:
                tiers["high"] += 1
            elif candidate.confidence >= 0.5:
                tiers["medium"] += 1
            else:
                tiers["low"] += 1
        return {"total_pending": len(candidates), "tiers": tiers}

    def memory_candidate(self, candidate_id: str) -> Optional[dict[str, Any]]:
        candidate = self.governance_store.get_candidate(candidate_id)
        if candidate is None:
            return None
        data = candidate.to_dict()
        data["source_records"] = [
            record.to_dict()
            for source_id in candidate.sources
            if (record := self.sensory_store.get(source_id)) is not None
        ]
        return data

    def decide_memory_candidate(
        self, candidate_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        return self.governance_store.decide(
            candidate_id,
            str(body.get("action", "")),
            self.memory_store,
            content=body.get("content"),
            merge_memory_id=(
                int(body["merge_memory_id"])
                if body.get("merge_memory_id") is not None
                else None
            ),
        )

    def decide_memory_candidates(self, body: dict[str, Any]) -> dict[str, Any]:
        raw_ids = body.get("candidate_ids")
        if not isinstance(raw_ids, list):
            raise ValueError("candidate_ids must be a list")
        candidate_ids = list(
            dict.fromkeys(
                str(value).strip() for value in raw_ids if str(value).strip()
            )
        )
        if not candidate_ids:
            raise ValueError("candidate_ids must not be empty")
        action = str(body.get("action", ""))
        if action not in {"accept", "ignore"}:
            raise ValueError("batch action must be accept or ignore")

        processed: list[dict[str, Any]] = []
        failed: list[dict[str, str]] = []
        for candidate_id in candidate_ids:
            try:
                processed.append(
                    {
                        "candidate_id": candidate_id,
                        **self.decide_memory_candidate(
                            candidate_id, {"action": action}
                        ),
                    }
                )
            except KeyError:
                failed.append(
                    {"candidate_id": candidate_id, "error": "candidate not found"}
                )
            except ValueError as exc:
                failed.append({"candidate_id": candidate_id, "error": str(exc)})
        return {
            "ok": not failed,
            "action": action,
            "requested": len(candidate_ids),
            "processed": processed,
            "failed": failed,
        }

    def retype_memory_candidates(self, body: dict[str, Any]) -> dict[str, Any]:
        raw_ids = body.get("candidate_ids")
        if not isinstance(raw_ids, list):
            raise ValueError("candidate_ids must be a list")
        candidate_ids = list(
            dict.fromkeys(
                str(value).strip() for value in raw_ids if str(value).strip()
            )
        )
        if not candidate_ids:
            raise ValueError("candidate_ids must not be empty")
        memory_type = str(body.get("memory_type", "")).strip()
        processed: list[dict[str, Any]] = []
        failed: list[dict[str, str]] = []
        for candidate_id in candidate_ids:
            try:
                candidate = self.governance_store.set_candidate_type(
                    candidate_id, memory_type
                )
                processed.append(candidate.to_dict())
            except KeyError:
                failed.append(
                    {"candidate_id": candidate_id, "error": "candidate not found"}
                )
            except ValueError as exc:
                failed.append({"candidate_id": candidate_id, "error": str(exc)})
        return {
            "ok": not failed,
            "memory_type": memory_type,
            "requested": len(candidate_ids),
            "processed": processed,
            "failed": failed,
        }

    def governance_tasks(
        self, *, status: Optional[str] = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        return self.governance_store.list_tasks(status=status, limit=limit)

    def governance_task(self, task_id: str) -> Optional[dict[str, Any]]:
        task = self.governance_store.get_task(task_id)
        if task is None:
            return None
        task["candidates"] = [
            candidate.to_dict()
            for candidate in self.governance_store.list_candidates(status=None)
            if candidate.task_id == task_id
        ]
        return task

    def set_memory_status(self, memory_id: int, status: str) -> dict[str, Any]:
        result = self.governance_store.set_memory_status(
            self.memory_store, memory_id, status
        )
        memory = result["memory"]
        return {
            "ok": True,
            "idempotent": result["idempotent"],
            "memory": self._memory_to_dict(memory),
        }

    def memory_usage_history(
        self, *, limit: int = 50, memory_id: Optional[int] = None
    ) -> dict[str, Any]:
        rows = self.governance_store.query_usage_history(
            limit=limit, memory_id=memory_id
        )
        return {
            "records": [
                {
                    "usage_id": row["usage_id"],
                    "memory_id": row["memory_id"],
                    "session_id": row["session_id"],
                    "workspace": row["workspace"],
                    "used_at": row["used_at"],
                    "content": (row.get("content") or "")[:120],
                    "key": row.get("key"),
                }
                for row in rows
            ]
        }

    # -- Conversation-source sync -------------------------------------------

    def sync_codex(self, limit_sessions: Optional[int] = None) -> dict[str, Any]:
        from ...connectors.codex_client import (
            iter_session_files,
            read_sessions,
            resolve_sessions_root,
        )

        profile = self._lookup_secret("codex:default")
        root = (
            resolve_sessions_root(profile.get("sessions_path"))
            if profile.get("sessions_path")
            else None
        )
        return self._run_rollout_sync(
            source_type="codex",
            content_type="codex_turn",
            root=root,
            files=iter_session_files(root),
            sessions_iter=read_sessions(limit=limit_sessions, root=root),
        )

    def sync_traex(self, limit_sessions: Optional[int] = None) -> dict[str, Any]:
        from ...connectors.codex_client import iter_session_files
        from ...connectors.traex_client import read_sessions, resolve_sessions_root

        profile = self._lookup_secret("traex:default")
        root = (
            resolve_sessions_root(profile.get("sessions_path"))
            if profile.get("sessions_path")
            else None
        )
        return self._run_rollout_sync(
            source_type="traex",
            content_type="traex_turn",
            root=root,
            files=iter_session_files(root),
            sessions_iter=read_sessions(limit=limit_sessions, root=root),
        )

    def _run_rollout_sync(
        self,
        *,
        source_type: str,
        content_type: str,
        root: Optional[Path],
        files: list[Path],
        sessions_iter: Iterable[Any],
    ) -> dict[str, Any]:
        sync_store = self._require_connector_sync_store()
        job_id = sync_store.start(
            source_type, str(root) if root is not None else None
        )
        try:
            result = self._sync_rollout_sessions(
                sessions_iter,
                source_type=source_type,
                content_type=content_type,
            )
            last_file = str(files[0]) if files else None
            last_mtime = files[0].stat().st_mtime if files else None
            job = sync_store.finish(
                job_id,
                status="completed",
                files_scanned=len(files),
                sessions_read=result["sessions_read"],
                records_seen=result["turns_seen"],
                records_ingested=result["records_ingested"],
                last_file=last_file,
                last_file_mtime=last_mtime,
                details={"source_type": source_type},
            )
            return {**result, "job_id": job_id, "sync": job}
        except Exception as exc:
            sync_store.fail(job_id, exc)
            raise

    def connector_sync_status(self, name: str) -> Optional[dict[str, Any]]:
        return self._require_connector_sync_store().latest(name)

    def _sync_rollout_sessions(
        self,
        sessions_iter: Iterable[Any],
        *,
        source_type: str,
        content_type: str,
    ) -> dict[str, Any]:
        before = self.sensory_store.count(source_type=source_type)
        sessions = 0
        turns_seen = 0
        for session in sessions_iter:
            sessions += 1
            for turn in session.turns():
                turns_seen += 1
                self.ingest_sensory_record(
                    {
                        "source_type": source_type,
                        "connector_id": source_type,
                        "content_type": content_type,
                        "raw_content": turn.as_text(),
                        "external_id": f"{session.session_id}:{turn.index}",
                        "occurred_at": turn.timestamp or session.started_at,
                        "project_path": session.cwd,
                        "conversation_id": session.session_id,
                        "source_locator": str(session.path),
                        "metadata": {
                            "roles": [message.role for message in turn.messages],
                            "message_count": len(turn.messages),
                            "model_provider": session.model_provider,
                            "originator": session.originator,
                        },
                    }
                )
        after = self.sensory_store.count(source_type=source_type)
        return {
            "sessions_read": sessions,
            "turns_seen": turns_seen,
            "records_ingested": after - before,
        }

    # -- Internal helpers ----------------------------------------------------

    def _utc_now(self) -> datetime:
        value = self._now()
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    @staticmethod
    def _project_value(project: Any | None, field: str) -> Any:
        if project is None:
            return None
        if isinstance(project, dict):
            return project.get(field)
        return getattr(project, field, None)

    @staticmethod
    def _memory_to_dict(memory: Any) -> dict[str, Any]:
        return {
            "id": memory.id,
            "scope": memory.scope.value,
            "content": memory.content,
            "key": memory.key,
            "workspace": memory.workspace,
            "session_id": memory.session_id,
            "created_at": memory.created_at,
            "status": memory.status,
            "updated_at": memory.updated_at,
            "source_record_id": memory.source_record_id,
        }

    def _lookup_secret(self, name: str) -> dict[str, Any]:
        return (self._secret_lookup(name) if self._secret_lookup else None) or {}

    def _require_connector_sync_store(self) -> Any:
        if self.connector_sync_store is None:
            raise RuntimeError("connector_sync_store is required for conversation sync")
        return self.connector_sync_store
