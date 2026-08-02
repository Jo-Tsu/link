"""The memory pipeline cleans, tags, and layers raw records into PENDING memories,
never loses a capture on LLM failure, and is idempotent across re-runs."""

from __future__ import annotations

from smallink.memory import MemoryPipeline, Scope, SQLiteMemoryStore
from smallink.providers import AssistantTurn, ModelCapabilities, ProviderClient
from smallink.sensory import SQLiteSensoryStore


class _TypedProvider(ProviderClient):
    """Returns one typed, workspace-scoped fact — the happy path."""

    def __init__(self, text: str):
        self._text = text
        self.calls = 0

    def complete(self, *, model, messages, tools=None, **settings):
        self.calls += 1
        return AssistantTurn(text=self._text, finish_reason="stop")

    def capabilities(self, model):
        return ModelCapabilities()


class _RaisingProvider(ProviderClient):
    def complete(self, *, model, messages, tools=None, **settings):
        raise RuntimeError("model exploded")

    def capabilities(self, model):
        return ModelCapabilities()


def _stores(tmp_path):
    return (
        SQLiteSensoryStore(tmp_path / "smallink.db"),
        SQLiteMemoryStore(tmp_path / "mem.db"),
    )


def _ingest(sensory, *, text="I always deploy with pnpm, never npm.", project="/proj"):
    return sensory.add(
        source_type="notes",
        content_type="document",
        raw_content=text,
        external_id="note-1",
        project_path=project,
    )


def test_pipeline_extracts_typed_scoped_pending_linked_memory(tmp_path):
    sensory, memory = _stores(tmp_path)
    record = _ingest(sensory)
    provider = _TypedProvider(
        '{"facts": [{"content": "Uses pnpm, never npm",'
        ' "memory_type": "user_preference", "scope": "workspace"}]}'
    )
    pipeline = MemoryPipeline(sensory, memory, provider, model="test")

    result = pipeline.process()

    assert result == {"processed_records": 1, "memories_created": 1, "fallbacks": 0}
    # Pending output is invisible to the default (active-only) list...
    assert memory.list() == []
    # ...but present when we ask for everything.
    pending = memory.list(status=None)
    assert len(pending) == 1
    item = pending[0]
    assert item.status == "pending"
    assert item.key == "user_preference"
    assert item.scope is Scope.WORKSPACE
    assert item.workspace == "/proj"
    assert item.source_record_id == record.record_id
    assert "pnpm" in item.content


def test_pipeline_multiple_facts_and_global_scope(tmp_path):
    sensory, memory = _stores(tmp_path)
    _ingest(sensory, text="My name is Alex. I ship on Fridays.", project=None)
    provider = _TypedProvider(
        '```json\n{"facts": ['
        '{"content": "Name is Alex", "memory_type": "life_memory", "scope": "global"},'
        '{"content": "Ships on Fridays", "memory_type": "work_habit", "scope": "global"}'
        ']}\n```'
    )
    pipeline = MemoryPipeline(sensory, memory, provider, model="test")

    result = pipeline.process()

    assert result["memories_created"] == 2
    items = memory.list(status=None)
    assert {i.scope for i in items} == {Scope.GLOBAL}
    assert all(i.workspace is None for i in items)  # global never carries a workspace


def test_pipeline_falls_back_on_bad_json(tmp_path):
    sensory, memory = _stores(tmp_path)
    record = _ingest(sensory, text="raw text that matters")
    pipeline = MemoryPipeline(sensory, memory, _TypedProvider("not json at all"), model="test")

    result = pipeline.process()

    assert result == {"processed_records": 1, "memories_created": 0, "fallbacks": 1}
    items = memory.list(status=None)
    assert len(items) == 1
    assert items[0].status == "pending"
    assert items[0].key is None  # untyped fallback
    assert items[0].source_record_id == record.record_id
    assert items[0].content == "raw text that matters"


def test_pipeline_falls_back_on_provider_exception(tmp_path):
    sensory, memory = _stores(tmp_path)
    _ingest(sensory)
    pipeline = MemoryPipeline(sensory, memory, _RaisingProvider(), model="test")

    result = pipeline.process()

    assert result["fallbacks"] == 1
    assert len(memory.list(status=None)) == 1  # capture never lost


def test_pipeline_is_idempotent(tmp_path):
    sensory, memory = _stores(tmp_path)
    _ingest(sensory)
    provider = _TypedProvider(
        '{"facts": [{"content": "Uses pnpm", "memory_type": "user_preference",'
        ' "scope": "workspace"}]}'
    )
    pipeline = MemoryPipeline(sensory, memory, provider, model="test")

    first = pipeline.process()
    second = pipeline.process()

    assert first["memories_created"] == 1
    assert second == {"processed_records": 0, "memories_created": 0, "fallbacks": 0}
    assert provider.calls == 1  # the already-processed record is not re-sent to the model
    assert len(memory.list(status=None)) == 1


def test_pipeline_empty_facts_creates_nothing(tmp_path):
    sensory, memory = _stores(tmp_path)
    _ingest(sensory, text="hello")
    pipeline = MemoryPipeline(sensory, memory, _TypedProvider('{"facts": []}'), model="test")

    result = pipeline.process()

    assert result == {"processed_records": 1, "memories_created": 0, "fallbacks": 0}
    assert memory.list(status=None) == []
