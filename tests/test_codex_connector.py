"""The Codex connector reads local rollout JSONL, normalizes conversation messages,
and ingests each as one sensory_record — idempotently."""

from __future__ import annotations

import json

from smallink.connectors.codex_client import parse_session, read_sessions
from smallink.providers import AssistantTurn, ModelCapabilities, ProviderClient
from smallink.server import SessionManager


class _Provider(ProviderClient):
    def complete(self, *, model, messages, tools=None, **settings):
        return AssistantTurn(text="ok", finish_reason="stop")

    def capabilities(self, model):
        return ModelCapabilities()


def _write_rollout(root, session_id, lines):
    day = root / "sessions" / "2026" / "08" / "01"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-2026-08-01T10-00-00-{session_id}.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    return path


def _session_lines(session_id, cwd="/proj"):
    return [
        {"timestamp": "t0", "type": "session_meta",
         "payload": {"session_id": session_id, "cwd": cwd, "timestamp": "t0", "model_provider": "openai"}},
        {"timestamp": "t1", "type": "event_msg", "payload": {"type": "task_started"}},
        # noise: environment_context injected as the first user turn
        {"timestamp": "t2", "type": "response_item",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "<environment_context>\n cwd\n</environment_context>"}]}},
        # real user turn
        {"timestamp": "t3", "type": "response_item",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "Build a login page"}]}},
        # developer turn — dropped (not user/assistant)
        {"timestamp": "t4", "type": "response_item",
         "payload": {"type": "message", "role": "developer",
                     "content": [{"type": "input_text", "text": "system scaffolding"}]}},
        # assistant turn
        {"timestamp": "t5", "type": "response_item",
         "payload": {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": "Done, here is the page"}]}},
        # non-message response_item — ignored
        {"timestamp": "t6", "type": "response_item", "payload": {"type": "reasoning"}},
    ]


def test_parse_session_extracts_and_filters(tmp_path):
    path = _write_rollout(tmp_path, "sess-1", _session_lines("sess-1"))
    session = parse_session(path)

    assert session is not None
    assert session.session_id == "sess-1"
    assert session.cwd == "/proj"
    assert session.model_provider == "openai"
    # environment_context + developer + reasoning dropped; only the real user + assistant kept.
    assert [(m.role, m.text) for m in session.messages] == [
        ("user", "Build a login page"),
        ("assistant", "Done, here is the page"),
    ]
    # indexes are stable, 0-based, in order
    assert [m.index for m in session.messages] == [0, 1]


def test_parse_session_none_when_no_messages(tmp_path):
    path = _write_rollout(tmp_path, "empty", [
        {"type": "session_meta", "payload": {"session_id": "empty"}},
        {"type": "event_msg", "payload": {"type": "task_started"}},
    ])
    assert parse_session(path) is None


def test_noise_filters_drop_codex_protocol_traffic(tmp_path):
    """Codex embeds approval-protocol machinery into the message stream; none of it is
    real conversation and must be dropped (measured ~57% of turns on real rollouts)."""
    path = _write_rollout(tmp_path, "noisy", [
        {"type": "session_meta", "payload": {"session_id": "noisy", "cwd": "/p"}},
        # JSON approval verdicts
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": '{"outcome":"allow"}'}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": '{"risk_level":"medium","outcome":"allow"}'}]}},
        # approval preamble
        {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "The following is the Codex agent history whose request action you are assessing…"}]}},
        # AGENTS.md / INSTRUCTIONS scaffolding
        {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "# AGENTS.md instructions\n<INSTRUCTIONS>do x</INSTRUCTIONS>"}]}},
        # recommended_plugins injection
        {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "<recommended_plugins> Box, Jira </recommended_plugins>"}]}},
        # a REAL user turn that happens to start with a heading — must be KEPT
        {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "# Files mentioned by the user:\nplease delete Documents/PPT"}]}},
        # a normal assistant reply — kept
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "已将 PPT 移入废纸篓。"}]}},
    ])
    session = parse_session(path)
    assert session is not None
    kept = [(m.role, m.text) for m in session.messages]
    assert kept == [
        ("user", "# Files mentioned by the user:\nplease delete Documents/PPT"),
        ("assistant", "已将 PPT 移入废纸篓。"),
    ]


def test_parse_session_tolerates_malformed_lines(tmp_path):
    day = tmp_path / "sessions" / "2026" / "08" / "01"
    day.mkdir(parents=True, exist_ok=True)
    path = day / "rollout-2026-08-01T10-00-00-broken.jsonl"
    path.write_text(
        json.dumps({"type": "session_meta", "payload": {"session_id": "broken"}}) + "\n"
        + "{ this is not json\n"
        + json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user",
                      "content": [{"type": "input_text", "text": "hi"}]}}) + "\n",
        encoding="utf-8",
    )
    session = parse_session(path)
    assert session is not None
    assert [m.text for m in session.messages] == ["hi"]


def test_read_sessions_limit_newest_first(tmp_path):
    root = tmp_path
    day = root / "sessions" / "2026" / "08" / "01"
    day.mkdir(parents=True, exist_ok=True)
    for ts, sid in (("09-00-00", "old"), ("11-00-00", "new")):
        (day / f"rollout-2026-08-01T{ts}-{sid}.jsonl").write_text(
            "\n".join(json.dumps(x) for x in _session_lines(sid)), encoding="utf-8"
        )
    got = list(read_sessions(limit=1, root=root / "sessions"))
    assert len(got) == 1
    assert got[0].session_id == "new"  # newest by filename


def test_sync_codex_ingests_per_turn_and_is_idempotent(tmp_path, monkeypatch):
    codex_home = tmp_path / "codex"
    _write_rollout(codex_home, "sess-1", _session_lines("sess-1"))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    manager = SessionManager(data_dir=tmp_path / "data", provider=_Provider())
    first = manager.sync_codex(limit_sessions=None)

    assert first["sessions_read"] == 1
    # env noise + developer dropped → user "Build a login page" + assistant "Done…" = 1 turn.
    assert first["turns_seen"] == 1
    assert first["records_ingested"] == 1

    records = manager.sensory_store.list(source_type="codex")
    assert len(records) == 1
    rec = records[0]
    assert rec.content_type == "codex_turn"
    assert rec.conversation_id == "sess-1"
    assert rec.project_path == "/proj"
    assert rec.external_id == "sess-1:0"
    # The turn transcript pairs the user prompt with its assistant reply.
    assert "User: Build a login page" in rec.raw_content
    assert "Assistant: Done, here is the page" in rec.raw_content

    # Re-sync: dedupe means no new rows.
    second = manager.sync_codex(limit_sessions=None)
    assert second["records_ingested"] == 0
    assert manager.sensory_store.count(source_type="codex") == 1


def test_turns_group_user_with_following_assistants(tmp_path):
    """A user prompt + its trailing assistant replies form one turn (UAAUA → 2 turns)."""
    path = _write_rollout(tmp_path, "multi", [
        {"type": "session_meta", "payload": {"session_id": "multi", "cwd": "/p"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "q1"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "a1a"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "a1b"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "q2"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
            "content": [{"type": "output_text", "text": "a2"}]}},
    ])
    session = parse_session(path)
    turns = session.turns()
    assert len(turns) == 2
    assert [len(t.messages) for t in turns] == [3, 2]  # q1+a1a+a1b, q2+a2
    assert turns[0].as_text() == "User: q1\n\nAssistant: a1a\n\nAssistant: a1b"
    assert [t.index for t in turns] == [0, 1]


def test_resolve_sessions_root_normalizes_picked_path(tmp_path):
    from smallink.connectors.codex_client import resolve_sessions_root

    # Picking the sessions dir itself → used as-is.
    sess = tmp_path / "sessions"
    sess.mkdir()
    assert resolve_sessions_root(str(sess)) == sess
    # Picking the Codex home (has a sessions subdir) → resolves into it.
    home = tmp_path / "dotcodex"
    (home / "sessions").mkdir(parents=True)
    assert resolve_sessions_root(str(home)) == home / "sessions"
    # Empty/None → None (caller falls back to default).
    assert resolve_sessions_root("") is None
    assert resolve_sessions_root(None) is None


def test_connect_codex_stores_path_and_sync_reads_it(tmp_path):
    from smallink.connectors.setup import connect_connector

    # A granted Codex home with one real session.
    codex_home = tmp_path / "granted"
    _write_rollout(codex_home, "g1", _session_lines("g1"))

    manager = SessionManager(data_dir=tmp_path / "data", provider=_Provider())
    result = connect_connector(manager.secrets, "codex", {"sessions_path": str(codex_home)})

    assert result["ok"] is True
    # The picked home resolved to its sessions subdir and was persisted.
    assert result["sessions_path"] == str(codex_home / "sessions")
    assert manager.secrets.get("codex:default")["sessions_path"] == str(codex_home / "sessions")

    # sync_codex reads from the granted path (not the default ~/.codex).
    synced = manager.sync_codex()
    assert synced["sessions_read"] == 1
    assert synced["records_ingested"] == 1
    assert manager.sensory_store.list(source_type="codex")[0].conversation_id == "g1"


def test_oversized_rollout_is_skipped(tmp_path, monkeypatch):
    from smallink.connectors import codex_client

    path = _write_rollout(tmp_path, "huge", _session_lines("huge"))
    # Force the size guard to trip on this small file.
    monkeypatch.setattr(codex_client, "_MAX_ROLLOUT_BYTES", 10)
    assert codex_client.parse_session(path) is None


def test_cli_sync_codex_connects_and_reuses_grant(tmp_path, monkeypatch, capsys):
    from smallink.connectors.cli import main

    codex_home = tmp_path / "codex"
    _write_rollout(codex_home, "cli-1", _session_lines("cli-1"))
    monkeypatch.setenv("LINK_STATE_DIR", str(tmp_path / "state"))

    assert main(["sync-codex", "--folder", str(codex_home)]) == 0
    first = capsys.readouterr().out
    assert "Connected Codex folder:" in first
    assert "ingested 1 new records" in first

    assert main(["sync-codex"]) == 0
    second = capsys.readouterr().out
    assert "Connected Codex folder:" not in second
    assert "ingested 0 new records" in second
