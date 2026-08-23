"""Focused tests for the server-side memory application service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from smallink.connectors.sync_store import ConnectorSyncStore
from smallink.knowledge import SQLiteKnowledgeStore
from smallink.memory import Scope, SQLiteGovernanceStore, SQLiteMemoryStore
from smallink.providers import AssistantTurn
from smallink.sensory import SQLiteSensoryStore
from smallink.server import SessionManager
from smallink.server import create_app
from smallink.server.services.memory import MemoryService


class _TypedProvider:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    def complete(self, **kwargs: Any) -> AssistantTurn:
        self.calls.append(kwargs)
        return AssistantTurn(text=self.text, finish_reason="stop")

    def capabilities(self, _model: str) -> Any:
        from smallink.providers import ModelCapabilities

        return ModelCapabilities()


def _service(
    tmp_path: Path,
    *,
    provider: Any | None = None,
    projects: dict[str, dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> tuple[MemoryService, dict[str, Any]]:
    path = tmp_path / "link.db"
    sensory = SQLiteSensoryStore(path)
    memory = SQLiteMemoryStore(path)
    governance = SQLiteGovernanceStore(path)
    knowledge = SQLiteKnowledgeStore(path)
    connector_sync = ConnectorSyncStore(path)
    project_map = projects or {}
    prefs: dict[str, Any] = {}
    saved: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    purposes: list[str] = []

    def model_for_purpose(purpose: str) -> str:
        purposes.append(purpose)
        return "memory-model"

    async def broadcast_event(event: dict[str, Any]) -> None:
        events.append(event)

    service = MemoryService(
        sensory_store=sensory,
        memory_store=memory,
        governance_store=governance,
        knowledge_store=knowledge,
        provider=provider or _TypedProvider('{"facts": []}'),
        model_for_purpose=model_for_purpose,
        get_project=project_map.get,
        get_project_by_workspace=lambda workspace: next(
            (
                project
                for project in project_map.values()
                if project["workspace_path"] == workspace
            ),
            None,
        ),
        preferences=prefs,
        save_preferences=lambda: saved.append(dict(prefs)),
        broadcast_event=broadcast_event,
        connector_sync_store=connector_sync,
        secret_lookup=lambda _name: None,
        now=(lambda: now) if now is not None else None,
    )
    return service, {
        "sensory": sensory,
        "memory": memory,
        "governance": governance,
        "knowledge": knowledge,
        "connector_sync": connector_sync,
        "prefs": prefs,
        "saved": saved,
        "events": events,
        "purposes": purposes,
    }


async def test_session_manager_wires_and_owns_memory_service_lifecycle(
    tmp_path: Path,
) -> None:
    provider = _TypedProvider('{"facts": []}')
    manager = SessionManager(data_dir=tmp_path / "data", provider=provider)
    service = manager.memory_service

    assert service.provider is provider
    assert service.sensory_store is manager.sensory_store
    assert service.memory_store is manager.memory_store
    assert service.governance_store is manager.governance_store
    assert service.knowledge_store is manager.knowledge_store
    assert service._preferences is manager._prefs

    manager.start_governance_scheduler()
    task = service._governance_scheduler_task
    assert task is not None and not task.done()

    await manager.aclose()
    assert task.cancelled()
    assert service._governance_scheduler_task is None


def test_memory_and_knowledge_routers_capture_the_service(tmp_path: Path) -> None:
    manager = SessionManager(
        data_dir=tmp_path / "data", provider=_TypedProvider('{"facts": []}')
    )

    class _FailIfUsed:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(f"router resolved manager fallback: {name}")

    from fastapi.testclient import TestClient

    app = create_app(manager)
    service = manager.memory_service
    client = TestClient(app)
    manager.memory_service = _FailIfUsed()  # routers already captured the real service
    try:
        assert client.get("/v1/memory").status_code == 200
        assert client.get("/v1/sensory-records").status_code == 200
        assert client.get("/v1/knowledge").status_code == 200
    finally:
        manager.memory_service = service
        client.close()


def test_sensory_ingest_query_provenance_and_protected_delete(tmp_path: Path) -> None:
    service, deps = _service(tmp_path)
    data_url = "data:image/png;base64," + "A" * 512
    ingested = service.ingest_sensory_record(
        {
            "source_type": "notes",
            "content_type": "document",
            "raw_content": {
                "text": "api_key=do-not-send",
                "image": data_url,
            },
            "external_id": "note-1",
            "metadata": {"preview": data_url},
        }
    )
    record = deps["sensory"].get(ingested["record_id"])
    assert record is not None
    assert record.sensitivity == "secret"
    assert data_url not in record.raw_content
    assert '"omitted":true' in record.raw_content

    listing = service.sensory_records(
        limit=999, offset=-10, source_type="notes", query="do-not-send"
    )
    assert listing["total"] == 1
    assert listing["limit"] == 500
    assert listing["offset"] == 0
    assert service.sensory_record(record.record_id) == record.to_dict()

    task_id = deps["governance"].create_task(
        [record.record_id], model="test", prompt_version="v1"
    )
    candidate = deps["governance"].add_candidate(
        task_id=task_id,
        content="Never expose credentials.",
        memory_type="user_preference",
        scope=Scope.GLOBAL,
        workspace=None,
        session_id=None,
        model="test",
        prompt_version="v1",
        source_ids=[record.record_id],
    )
    provenance = service.sensory_provenance(record.record_id)
    assert provenance is not None
    assert provenance["candidates"][0]["candidate_id"] == candidate.candidate_id
    with pytest.raises(ValueError, match="referenced by memory governance"):
        service.delete_sensory_records(record_ids=[record.record_id])

    disposable = service.ingest_sensory_record(
        {
            "source_type": "notes",
            "content_type": "document",
            "raw_content": "temporary",
            "external_id": "note-2",
        }
    )
    deleted = service.delete_sensory_records(record_ids=[disposable["record_id"]])
    assert deleted == {
        "ok": True,
        "deleted_records": 1,
        "affected_candidates": [],
        "affected_memories": [],
    }


def test_knowledge_index_search_archive_and_project_validation(tmp_path: Path) -> None:
    project = {"project_id": "project-1", "workspace_path": "/project"}
    service, deps = _service(tmp_path, projects={"project-1": project})
    source = deps["sensory"].add(
        source_type="files",
        content_type="document_text",
        raw_content="Hybrid retrieval keeps transparent source citations.",
        external_id="doc-1",
        project_path="/project",
        source_locator="file:///project/design.md",
    )
    deps["sensory"].add(
        source_type="smallink",
        content_type="user_input",
        raw_content="Not a knowledge source.",
        external_id="chat-1",
        project_path="/project",
    )

    indexed = service.index_project_knowledge("project-1")
    assert indexed["indexed"] == 1
    assert indexed["skipped"] == 1
    item_id = indexed["item_ids"][0]
    item = service.knowledge_item(item_id)
    assert item is not None
    assert item["source_record_id"] == source.record_id
    assert item["project_id"] == "project-1"

    results = service.search_knowledge(
        "transparent source citations", project_id="project-1"
    )
    assert results["results"][0]["item_id"] == item_id
    assert service.knowledge_items(project_id="project-1")[0]["item_id"] == item_id
    archived = service.archive_knowledge_item(item_id, True)
    assert archived["item"]["status"] == "archived"
    assert service.knowledge_items(project_id="project-1") == []
    with pytest.raises(KeyError):
        service.search_knowledge("anything", project_id="missing")


def test_pipeline_candidates_decisions_status_tasks_and_usage(tmp_path: Path) -> None:
    provider = _TypedProvider(
        '{"facts":[{"content":"Uses concise product interfaces.",'
        '"memory_type":"user_preference","scope":"global",'
        '"confidence":0.85}]}'
    )
    service, deps = _service(tmp_path, provider=provider)
    source = deps["sensory"].add(
        source_type="notes",
        content_type="document",
        raw_content="I prefer concise product interfaces.",
        external_id="preference-1",
    )

    pipeline = service.run_memory_pipeline(
        [source.record_id], limit=5, allow_sensitive_cloud=True
    )
    assert pipeline["status"] == "reviewing"
    assert pipeline["candidates_created"] == 1
    assert deps["purposes"] == ["memory"]
    assert provider.calls[0]["model"] == "memory-model"

    candidates = service.memory_candidates()
    candidate_id = candidates[0]["candidate_id"]
    assert service.memory_confidence_summary() == {
        "total_pending": 1,
        "tiers": {"high": 1, "medium": 0, "low": 0, "unscored": 0},
    }
    assert service.memory_candidate(candidate_id)["source_records"][0][
        "record_id"
    ] == source.record_id

    retyped = service.retype_memory_candidates(
        {
            "candidate_ids": [candidate_id, "missing", candidate_id],
            "memory_type": "product_decision",
        }
    )
    assert retyped["requested"] == 2
    assert retyped["processed"][0]["memory_type"] == "product_decision"
    assert retyped["failed"] == [
        {"candidate_id": "missing", "error": "candidate not found"}
    ]

    decided = service.decide_memory_candidates(
        {"candidate_ids": [candidate_id, "missing"], "action": "accept"}
    )
    assert decided["ok"] is False
    memory_id = decided["processed"][0]["memory_id"]
    assert service.governance_task(pipeline["task_id"])["status"] == "completed"

    archived = service.set_memory_status(memory_id, "archived")
    assert archived["memory"]["status"] == "archived"
    assert service.set_memory_status(memory_id, "archived")["idempotent"] is True
    restored = service.set_memory_status(memory_id, "active")
    assert restored["memory"]["status"] == "active"

    deps["governance"].record_usage(
        memory_id, session_id="session-1", workspace="/project"
    )
    usage = service.memory_usage_history(memory_id=memory_id)
    assert usage["records"] == [
        {
            "usage_id": usage["records"][0]["usage_id"],
            "memory_id": memory_id,
            "session_id": "session-1",
            "workspace": "/project",
            "used_at": usage["records"][0]["used_at"],
            "content": "Uses concise product interfaces.",
            "key": "product_decision",
        }
    ]


def test_auto_accept_requires_confirmation_at_service_boundary(tmp_path: Path) -> None:
    provider = _TypedProvider(
        '{"facts":[{"content":"Uses concise product interfaces.",'
        '"memory_type":"user_preference","scope":"global",'
        '"confidence":0.95}]}'
    )
    service, deps = _service(tmp_path, provider=provider)
    source = deps["sensory"].add(
        source_type="notes",
        content_type="document",
        raw_content="I prefer concise product interfaces.",
        external_id="preference-1",
    )
    service.run_memory_pipeline([source.record_id])

    with pytest.raises(PermissionError, match="explicit confirmation"):
        service.auto_accept_high_confidence(0.9)
    assert service.memory_candidates()[0]["status"] == "pending"
    assert deps["memory"].list() == []

    result = service.auto_accept_high_confidence(0.9, confirmed=True)
    assert result["auto_accepted"] == 1
    assert len(deps["memory"].list()) == 1


async def test_scheduled_governance_persists_result_and_broadcasts(tmp_path: Path) -> None:
    fixed_now = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    provider = _TypedProvider(
        '{"facts":[{"content":"Uses Smallink daily.",'
        '"memory_type":"work_habit","scope":"global",'
        '"confidence":0.95}]}'
    )
    service, deps = _service(tmp_path, provider=provider, now=fixed_now)
    deps["sensory"].add(
        source_type="notes",
        content_type="document",
        raw_content="I use Smallink every day.",
        external_id="daily-1",
    )

    configured = service.set_governance_schedule(
        {"enabled": True, "interval_minutes": 60, "batch_limit": 10}
    )
    assert configured["enabled"] is True
    assert configured["next_run_at"] == "2026-08-23T13:00:00+00:00"
    assert len(deps["saved"]) == 1

    result = await service.run_scheduled_governance_once(force=True)
    assert result["status"] == "ran"
    assert result["result"]["auto_accepted"] == 0
    assert service.memory_candidates()[0]["status"] == "pending"
    assert deps["memory"].list() == []
    assert deps["prefs"]["governance_schedule"]["last_run_at"] == (
        "2026-08-23T12:00:00+00:00"
    )
    assert deps["events"] == [
        {"type": "governance_task_updated", "data": result["result"]}
    ]
    assert service.governance_schedule()["running"] is False
    assert await service.run_scheduled_governance_once(force=True) == {
        "status": "skipped",
        "reason": "no_pending_records",
    }


@dataclass
class _Message:
    role: str


@dataclass
class _Turn:
    index: int
    text: str
    timestamp: str | None = None

    @property
    def messages(self) -> list[_Message]:
        return [_Message("user"), _Message("assistant")]

    def as_text(self) -> str:
        return self.text


@dataclass
class _Session:
    session_id: str
    path: Path
    cwd: str
    started_at: str
    model_provider: str = "trae"
    originator: str = "cli"

    def turns(self) -> list[_Turn]:
        return [_Turn(0, "user: hello\nassistant: hi")]


def test_rollout_sync_is_idempotent_and_records_job(tmp_path: Path) -> None:
    service, deps = _service(tmp_path)
    source_file = tmp_path / "rollout.jsonl"
    source_file.write_text("{}\n", encoding="utf-8")
    session = _Session(
        session_id="session-1",
        path=source_file,
        cwd="/project",
        started_at="2026-08-23T10:00:00+00:00",
    )

    first = service._run_rollout_sync(
        source_type="traex",
        content_type="traex_turn",
        root=tmp_path,
        files=[source_file],
        sessions_iter=[session],
    )
    second = service._run_rollout_sync(
        source_type="traex",
        content_type="traex_turn",
        root=tmp_path,
        files=[source_file],
        sessions_iter=[session],
    )

    assert first["records_ingested"] == 1
    assert second["records_ingested"] == 0
    assert first["sync"]["status"] == "completed"
    latest = service.connector_sync_status("traex")
    assert latest is not None
    assert latest["job_id"] == second["job_id"]
    assert latest["watermark"]["last_file"] == str(source_file)
