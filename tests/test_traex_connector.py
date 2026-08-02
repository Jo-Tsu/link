"""TraeX connector imports user-owned TRAE CLI sessions and skips subagents."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from smallink.connectors.setup import connect_connector
from smallink.connectors.traex_client import read_sessions, resolve_sessions_root
from smallink.providers import AssistantTurn, ModelCapabilities, ProviderClient
from smallink.server import SessionManager, create_app


class _Provider(ProviderClient):
    def complete(self, *, model, messages, tools=None, **settings):
        return AssistantTurn(text="ok", finish_reason="stop")

    def capabilities(self, model):
        return ModelCapabilities()


def _write_session(
    root,
    session_id,
    *,
    thread_source="user",
    timestamp="10-00-00",
    live_tail=False,
):
    day = root / "cli" / "sessions" / "2026" / "08" / "01"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-2026-08-01T{timestamp}-{session_id}.jsonl"
    source = (
        thread_source
        if thread_source == "user"
        else {
            "subagent": {
                "thread_spawn": {
                    "parent_thread_id": "parent",
                    "agent_nickname": "Explorer",
                }
            }
        }
    )
    lines = [
        {
            "timestamp": "t0",
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "cwd": "/proj",
                "timestamp": "t0",
                "originator": "codex-tui",
                "model_provider": "trae",
                "thread_source": source,
            },
        },
        {
            "timestamp": "t1",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "<system-reminder>skip me</system-reminder>"}],
            },
        },
        {
            "timestamp": "t2",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Audit this project"}],
            },
        },
        {
            "timestamp": "t3",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "The audit is complete"}],
            },
        },
        {
            "timestamp": "t4",
            "type": "event_msg",
            "payload": {"type": "task_complete", "turn_id": "turn-1"},
        },
    ]
    if live_tail:
        lines.extend(
            [
                {
                    "timestamp": "t5",
                    "type": "event_msg",
                    "payload": {"type": "task_started", "turn_id": "turn-2"},
                },
                {
                    "timestamp": "t6",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "Continue working"}],
                    },
                },
                {
                    "timestamp": "t7",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Still in progress"}],
                    },
                },
            ]
        )
    path.write_text("\n".join(json.dumps(line) for line in lines), encoding="utf-8")
    return path


def test_read_sessions_excludes_subagents_and_limits_main_threads(tmp_path):
    _write_session(tmp_path, "main", timestamp="09-00-00", live_tail=True)
    _write_session(tmp_path, "worker", thread_source="subagent", timestamp="11-00-00")

    sessions = list(read_sessions(root=tmp_path / "cli" / "sessions", limit=1))

    assert [session.session_id for session in sessions] == ["main"]
    assert sessions[0].originator == "codex-tui"
    assert [message.text for message in sessions[0].messages] == [
        "Audit this project",
        "The audit is complete",
    ]


def test_resolve_traex_sessions_root(tmp_path):
    sessions = tmp_path / "cli" / "sessions"
    sessions.mkdir(parents=True)

    assert resolve_sessions_root(str(tmp_path)) == sessions
    assert resolve_sessions_root(str(tmp_path / "cli")) == sessions
    assert resolve_sessions_root(str(sessions)) == sessions


def test_connect_and_sync_traex_is_idempotent(tmp_path):
    _write_session(tmp_path / "trae", "main")
    _write_session(tmp_path / "trae", "worker", thread_source="subagent", timestamp="11-00-00")
    manager = SessionManager(data_dir=tmp_path / "data", provider=_Provider())

    connected = connect_connector(
        manager.secrets,
        "traex",
        {"sessions_path": str(tmp_path / "trae")},
    )
    first = manager.sync_traex()
    second = manager.sync_traex()

    assert connected["ok"] is True
    assert connected["sessions_path"].endswith("cli/sessions")
    assert first == {"sessions_read": 1, "turns_seen": 1, "records_ingested": 1}
    assert second["records_ingested"] == 0
    record = manager.sensory_store.list(source_type="traex")[0]
    assert record.connector_id == "traex"
    assert record.content_type == "traex_turn"
    assert record.conversation_id == "main"
    assert "Audit this project" in record.raw_content
    assert record.metadata["originator"] == "codex-tui"


def test_traex_sync_endpoint(tmp_path):
    root = tmp_path / "trae"
    _write_session(root, "main")
    manager = SessionManager(data_dir=tmp_path / "data", provider=_Provider())
    connect_connector(manager.secrets, "traex", {"sessions_path": str(root)})
    client = TestClient(create_app(manager))

    response = client.post("/v1/connectors/traex/sync", json={})

    assert response.status_code == 200
    assert response.json()["records_ingested"] == 1
