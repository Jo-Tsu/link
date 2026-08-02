"""Sensory records are immutable, idempotent and traceable to their source."""

from __future__ import annotations

from fastapi.testclient import TestClient

from smallink.events import Event, EventType
from smallink.providers import AssistantTurn, ModelCapabilities, ProviderClient
from smallink.sensory import SQLiteSensoryStore
from smallink.server import SessionManager, create_app


class _Provider(ProviderClient):
    def complete(self, *, model, messages, tools=None, **settings):
        return AssistantTurn(text="done", finish_reason="stop")

    def capabilities(self, model):
        return ModelCapabilities()


def test_sensory_store_is_idempotent_and_filterable(tmp_path):
    store = SQLiteSensoryStore(tmp_path / "smallink.db")
    first = store.add(
        source_type="codex",
        external_id="thread-1:message-1",
        content_type="user_input",
        raw_content={"text": "Build it"},
        conversation_id="thread-1",
    )
    second = store.add(
        source_type="codex",
        external_id="thread-1:message-1",
        content_type="user_input",
        raw_content={"text": "Build it"},
        conversation_id="thread-1",
    )

    assert first.record_id == second.record_id
    assert store.count(source_type="codex") == 1
    assert store.list(conversation_id="thread-1")[0].governance_status == "pending"


async def test_runtime_captures_input_output_and_tool_records(tmp_path):
    manager = SessionManager(workspace=tmp_path, provider=_Provider())
    engine = manager.get_engine("sensory-session", workspace=str(tmp_path), agent="code")

    async def fake_run(_content, source=None):
        yield Event(EventType.TOOL_PROPOSED, {"name": "run_command", "arguments": {"command": "pwd"}})
        yield Event(EventType.TOOL_FINISHED, {"name": "run_command", "status": "ok", "result_preview": str(tmp_path)})
        yield Event(EventType.ASSISTANT_MESSAGE, {"text": "Finished"})
        yield Event(EventType.TURN_END, {"status": "completed"})

    engine.run = fake_run
    async for _ in manager.tracked_engine_events(
        "sensory-session", engine, content="Inspect this project"
    ):
        pass

    records = manager.sensory_store.list(conversation_id="sensory-session")
    assert {record.content_type for record in records} == {
        "user_input",
        "tool_call",
        "tool_result",
        "assistant_output",
    }
    tool_call = next(record for record in records if record.content_type == "tool_call")
    assert "pwd" in tool_call.raw_content
    assert tool_call.source_locator.startswith("/v1/agent-runs/")


def test_sensory_rest_lists_and_opens_source_records(tmp_path):
    manager = SessionManager(data_dir=tmp_path / "data", provider=_Provider())
    record = manager.sensory_store.add(
        source_type="file",
        external_id="file-1",
        content_type="document",
        raw_content="hello",
        source_locator="/tmp/hello.md",
    )
    client = TestClient(create_app(manager))

    listing = client.get("/v1/sensory-records?source_type=file").json()
    assert listing["total"] == 1
    assert listing["records"][0]["record_id"] == record.record_id
    assert client.get(f"/v1/sensory-records/{record.record_id}").json()["raw_content"] == "hello"
    assert client.get("/v1/sensory-records/stats").json()["pending"] == 1


def test_ingest_endpoint_writes_record(tmp_path):
    manager = SessionManager(data_dir=tmp_path / "data", provider=_Provider())
    client = TestClient(create_app(manager))

    resp = client.post(
        "/v1/sensory-records",
        json={
            "source_type": "notes",
            "content_type": "document",
            "raw_content": "Deploy with pnpm.",
            "external_id": "note-1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["record_id"]
    assert body["governance_status"] == "pending"

    fetched = client.get(f"/v1/sensory-records/{body['record_id']}").json()
    assert fetched["raw_content"] == "Deploy with pnpm."
    assert fetched["source_type"] == "notes"


def test_ingest_endpoint_is_idempotent(tmp_path):
    manager = SessionManager(data_dir=tmp_path / "data", provider=_Provider())
    client = TestClient(create_app(manager))
    payload = {
        "source_type": "notes",
        "content_type": "document",
        "raw_content": "same content",
        "external_id": "dup-1",
    }

    first = client.post("/v1/sensory-records", json=payload).json()
    second = client.post("/v1/sensory-records", json=payload).json()

    assert first["record_id"] == second["record_id"]
    assert client.get("/v1/sensory-records/stats").json()["total"] == 1


def test_ingest_endpoint_rejects_missing_fields(tmp_path):
    manager = SessionManager(data_dir=tmp_path / "data", provider=_Provider())
    client = TestClient(create_app(manager))

    resp = client.post("/v1/sensory-records", json={"source_type": "notes"})
    assert resp.status_code == 400
    assert "raw_content" in resp.json()["detail"] or "content_type" in resp.json()["detail"]
