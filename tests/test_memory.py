"""P4 gate tests — memory store + sessions."""

from __future__ import annotations

import aisuite as ai
from smallink.conversations import ConversationStore
from smallink.memory import Scope, SQLiteMemoryStore, format_memories, memory_tools
from smallink.sessions import SessionRecord
from smallink.tools import ToolRegistry


def _store(tmp_path):
    return SQLiteMemoryStore(tmp_path / "mem.db")


# -- memory store ---------------------------------------------------------------


def test_memory_round_trip(tmp_path):
    store = _store(tmp_path)
    item = store.add(
        "prefers tabs over spaces", scope=Scope.WORKSPACE, workspace="/proj"
    )
    assert store.get(item.id).content == "prefers tabs over spaces"
    assert [m.content for m in store.list(workspace="/proj")] == [
        "prefers tabs over spaces"
    ]


def test_workspace_scope_isolation(tmp_path):
    store = _store(tmp_path)
    store.add("A secret", scope=Scope.WORKSPACE, workspace="/proj/a")
    assert store.list(workspace="/proj/b") == []
    assert len(store.list(workspace="/proj/a")) == 1


def test_global_scope_visible_regardless_of_workspace(tmp_path):
    store = _store(tmp_path)
    store.add("use 2-space indent everywhere", scope=Scope.GLOBAL)
    assert len(store.list(scope=Scope.GLOBAL)) == 1


def test_memory_listable_and_editable(tmp_path):
    store = _store(tmp_path)
    item = store.add("old note", scope=Scope.WORKSPACE, workspace="/proj")
    updated = store.update(item.id, "new note")
    assert updated.content == "new note"
    assert store.delete(item.id) is True
    assert store.get(item.id) is None


def test_format_memories_shows_ids(tmp_path):
    store = _store(tmp_path)
    item = store.add("fact one", workspace="/proj")
    rendered = format_memories(store.list(workspace="/proj"))
    assert "fact one" in rendered and "Known memories" in rendered
    assert f"[#{item.id}]" in rendered  # ids let the agent update/forget


def test_new_memories_default_to_active(tmp_path):
    store = _store(tmp_path)
    item = store.add("a confirmed fact", scope=Scope.GLOBAL)
    assert item.status == "active"
    # The default list is active-only, so a plain add is immediately visible.
    assert [m.id for m in store.list(scope=Scope.GLOBAL)] == [item.id]


def test_pending_memories_excluded_from_default_list(tmp_path):
    store = _store(tmp_path)
    active = store.add("active fact", scope=Scope.GLOBAL)
    pending = store.add("pending fact", scope=Scope.GLOBAL, status="pending")

    # Default (active-only) hides pending — the invariant that keeps pipeline output out of
    # prompts and the confirmed-memory view.
    listed = store.list(scope=Scope.GLOBAL)
    assert [m.id for m in listed] == [active.id]
    # status=None surfaces everything; status="pending" isolates the queue.
    assert {m.id for m in store.list(scope=Scope.GLOBAL, status=None)} == {
        active.id,
        pending.id,
    }
    assert [m.id for m in store.list(scope=Scope.GLOBAL, status="pending")] == [
        pending.id
    ]


def test_migration_backfills_status_active(tmp_path):
    import sqlite3

    # Simulate a pre-migration DB: the original schema with no status column and one row.
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL, key TEXT,
            content TEXT NOT NULL, workspace TEXT, session_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)"""
    )
    conn.execute(
        "INSERT INTO memories (scope, content, workspace) VALUES ('global', 'legacy fact', NULL)"
    )
    conn.commit()
    conn.close()

    # Opening via the store runs the additive migration; the legacy row backfills to active.
    store = SQLiteMemoryStore(path)
    listed = store.list(scope=Scope.GLOBAL)
    assert [m.content for m in listed] == ["legacy fact"]
    assert listed[0].status == "active"


def test_history_records_add_update_delete(tmp_path):
    store = _store(tmp_path)
    item = store.add("v1", scope=Scope.GLOBAL)
    store.update(item.id, "v2")
    store.delete(item.id)

    events = [(h["event"], h["old_content"], h["new_content"]) for h in store.list_history(item.id)]
    assert events == [
        ("ADD", None, "v1"),
        ("UPDATE", "v1", "v2"),
        ("DELETE", "v2", None),
    ]


# -- remember tool --------------------------------------------------------------


def test_remember_tool_persists(tmp_path):
    store = _store(tmp_path)
    reg = ToolRegistry()
    reg.register_all(memory_tools(store, workspace="/proj"))
    assert "remember" in reg.names()

    result = reg.execute("remember", {"content": "deploys on Fridays are banned"})
    assert result["saved"] is True
    assert any(
        m.content == "deploys on Fridays are banned"
        for m in store.list(workspace="/proj")
    )


def test_memory_update_and_forget_tools(tmp_path):
    store = _store(tmp_path)
    reg = ToolRegistry()
    reg.register_all(memory_tools(store, workspace="/proj"))
    assert {"remember", "memory_update", "memory_forget"} <= set(reg.names())

    saved = reg.execute("remember", {"content": "uses npm"})
    updated = reg.execute(
        "memory_update", {"memory_id": saved["id"], "content": "uses pnpm, not npm"}
    )
    assert updated["updated"] is True
    assert store.get(saved["id"]).content == "uses pnpm, not npm"

    gone = reg.execute("memory_forget", {"memory_id": saved["id"]})
    assert gone["deleted"] is True
    assert store.get(saved["id"]) is None


def test_memory_update_and_forget_unknown_id(tmp_path):
    store = _store(tmp_path)
    reg = ToolRegistry()
    reg.register_all(memory_tools(store, workspace="/proj"))
    assert (
        "no memory"
        in reg.execute("memory_update", {"memory_id": 99, "content": "x"})["error"]
    )
    assert "no memory" in reg.execute("memory_forget", {"memory_id": 99})["error"]


# -- sessions -------------------------------------------------------------------


def test_session_save_and_resume(tmp_path):
    store = ConversationStore(tmp_path)
    messages = [
        {"role": "system", "content": "be helpful"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    store.save(
        SessionRecord(
            session_id="s1",
            workspace="/proj",
            model="gpt-5.5",
            mode="interactive",
            messages=messages,
        )
    )
    loaded = store.load("s1")
    assert loaded is not None
    assert loaded.messages == messages
    assert loaded.model == "gpt-5.5"
    # messages live in an append-only jsonl, not the index db
    assert (tmp_path / "conversations" / "s1.jsonl").exists()


class _StubProvider:
    def complete(self, **kwargs):  # pragma: no cover - not invoked
        raise NotImplementedError

    def capabilities(self, model):  # pragma: no cover
        raise NotImplementedError


def test_build_code_engine_injects_memory(tmp_path):
    from smallink.agent import build_code_engine

    workspace = str(tmp_path.resolve())
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    store.add(
        "always run black before committing", scope=Scope.WORKSPACE, workspace=workspace
    )

    engine = build_code_engine(
        workspace=tmp_path, provider=_StubProvider(), memory_store=store
    )
    try:
        assert {"remember", "memory_update", "memory_forget"}.isdisjoint(
            engine.registry.names()
        )
        assert engine.messages[0]["role"] == "system"
        assert "always run black" in engine.messages[0]["content"]
        assert "read-only context" in engine.messages[0]["content"]
        assert "confirmed by the user" in engine.messages[0]["content"]
    finally:
        engine.executor.close()


def test_session_append_only_and_list(tmp_path):
    store = ConversationStore(tmp_path)
    store.save(
        SessionRecord(
            "s1", "/proj", "gpt-5.5", "interactive", [{"role": "user", "content": "a"}]
        )
    )
    store.save(
        SessionRecord(
            "s1",
            "/proj",
            "gpt-5.5",
            "interactive",
            [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}],
        )
    )
    loaded = store.load("s1")
    assert len(loaded.messages) == 2  # appended, not duplicated
    listed = store.list(workspace="/proj")
    assert len(listed) == 1
    assert listed[0].message_count == 2
    assert listed[0].title == "a"
