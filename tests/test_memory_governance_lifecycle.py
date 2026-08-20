from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from smallink.memory import Scope, SQLiteGovernanceStore, SQLiteMemoryStore
from smallink.providers.base import AssistantTurn, ModelCapabilities, ProviderClient
from smallink.server import SessionManager, create_app


class NoopProvider(ProviderClient):
    def complete(self, **kwargs) -> AssistantTurn:
        return AssistantTurn(text="")

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities()


class TypedProvider(NoopProvider):
    def complete(self, **kwargs) -> AssistantTurn:
        return AssistantTurn(
            text='{"facts":[{"content":"Uses Smallink daily",'
            '"memory_type":"work_habit","scope":"global"}]}'
        )


def _candidate(governance: SQLiteGovernanceStore, task_id: str):
    return governance.add_candidate(
        task_id=task_id,
        content="Uses concise product interfaces.",
        memory_type="user_preference",
        scope=Scope.GLOBAL,
        workspace=None,
        session_id=None,
        model="test",
        prompt_version="v1",
        source_ids=["source-1"],
    )


def test_governance_task_waits_for_human_and_completes_after_last_decision(tmp_path):
    path = tmp_path / "memory.db"
    memory = SQLiteMemoryStore(path)
    governance = SQLiteGovernanceStore(path)
    task_id = governance.create_task(
        ["source-1"], model="test", prompt_version="v1"
    )
    candidate = _candidate(governance, task_id)
    governance.mark_record(task_id, "source-1", "processed")

    task = governance.finish_task(task_id)
    assert task["status"] == "reviewing"
    assert governance.get_task(task_id)["pending_candidates"] == 1

    changed = governance.set_candidate_type(candidate.candidate_id, "product_decision")
    assert changed.memory_type == "product_decision"
    decided = governance.decide(candidate.candidate_id, "accept", memory)
    assert decided["task_status"] == "completed"
    assert decided["pending_count"] == 0
    assert governance.get_task(task_id)["status"] == "completed"


def test_memory_archive_restore_is_versioned_and_excluded_from_active_retrieval(tmp_path):
    path = tmp_path / "memory.db"
    memory = SQLiteMemoryStore(path)
    governance = SQLiteGovernanceStore(path)
    task_id = governance.create_task(
        ["source-1"], model="test", prompt_version="v1"
    )
    candidate = _candidate(governance, task_id)
    item_id = governance.decide(candidate.candidate_id, "accept", memory)["memory_id"]

    archived = governance.set_memory_status(memory, item_id, "archived")
    assert archived["memory"].status == "archived"
    assert memory.list() == []
    assert [item.id for item in memory.list(status="archived")] == [item_id]

    restored = governance.set_memory_status(memory, item_id, "active")
    assert restored["memory"].status == "active"
    assert [item.id for item in memory.list()] == [item_id]
    assert [row["event"] for row in memory.list_history(item_id)] == [
        "ADD",
        "ARCHIVE",
        "RESTORE",
    ]
    versions = governance._conn.execute(
        "SELECT status FROM memory_versions WHERE memory_id=? ORDER BY version",
        (item_id,),
    ).fetchall()
    assert [row["status"] for row in versions] == ["active", "archived", "active"]


def test_memory_lifecycle_and_batch_type_apis(tmp_path):
    manager = SessionManager(data_dir=tmp_path / "data", provider=NoopProvider())
    task_id = manager.governance_store.create_task(
        ["source-1"], model="test", prompt_version="v1"
    )
    candidate = _candidate(manager.governance_store, task_id)
    manager.governance_store.mark_record(task_id, "source-1", "processed")
    manager.governance_store.finish_task(task_id)
    client = TestClient(create_app(manager))

    changed = client.patch(
        "/v1/memory/candidates/batch/type",
        json={
            "candidate_ids": [candidate.candidate_id],
            "memory_type": "product_decision",
        },
    )
    assert changed.status_code == 200
    assert changed.json()["processed"][0]["memory_type"] == "product_decision"

    accepted = client.post(
        f"/v1/memory/candidates/{candidate.candidate_id}/decision",
        json={"action": "accept"},
    ).json()
    memory_id = accepted["memory_id"]
    assert accepted["task_status"] == "completed"
    assert client.get("/v1/memory/governance/tasks").json()["tasks"][0][
        "status"
    ] == "completed"

    assert client.post(f"/v1/memory/{memory_id}/archive").status_code == 200
    assert client.get("/v1/memory").json()["memory"] == []
    assert client.get("/v1/memory", params={"status": "archived"}).json()[
        "memory"
    ][0]["id"] == memory_id
    restored = client.post(f"/v1/memory/{memory_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["memory"]["status"] == "active"


def test_scheduled_governance_processes_only_pending_incremental_records(tmp_path):
    manager = SessionManager(data_dir=tmp_path / "data", provider=TypedProvider())
    manager.sensory_store.add(
        source_type="notes",
        content_type="document",
        raw_content="I use Smallink every day.",
        external_id="note-1",
    )
    configured = manager.set_governance_schedule(
        {"enabled": True, "interval_minutes": 60, "batch_limit": 10}
    )
    assert configured["enabled"] is True

    first = asyncio.run(manager.run_scheduled_governance_once(force=True))
    assert first["status"] == "ran"
    assert first["result"]["status"] == "reviewing"
    assert manager.governance_tasks()[0]["pending_candidates"] == 1
    assert manager.governance_schedule()["last_result"]["task_id"] == first["result"][
        "task_id"
    ]

    second = asyncio.run(manager.run_scheduled_governance_once(force=True))
    assert second == {"status": "skipped", "reason": "no_pending_records"}
