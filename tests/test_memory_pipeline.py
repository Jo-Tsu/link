"""The governance pipeline creates reviewable candidates without unsafe fallbacks."""

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
    def __init__(self):
        self.calls = 0

    def complete(self, *, model, messages, tools=None, **settings):
        self.calls += 1
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


def test_pipeline_extracts_typed_scoped_pending_linked_candidate(tmp_path):
    sensory, memory = _stores(tmp_path)
    record = _ingest(sensory)
    provider = _TypedProvider(
        '{"facts": [{"content": "Uses pnpm, never npm",'
        ' "memory_type": "user_preference", "scope": "workspace"}]}'
    )
    pipeline = MemoryPipeline(sensory, memory, provider, model="test")

    result = pipeline.process()

    assert result["processed_records"] == 1
    assert result["candidates_created"] == 1
    assert result["failed_records"] == 0
    # Candidates remain isolated from the formal memory store.
    assert memory.list() == []
    assert memory.list(status=None) == []
    pending = pipeline.governance_store.list_candidates()
    assert len(pending) == 1
    item = pending[0]
    assert item.status == "pending"
    assert item.memory_type == "user_preference"
    assert item.scope == Scope.WORKSPACE.value
    assert item.workspace == "/proj"
    assert item.sources == [record.record_id]
    assert "pnpm" in item.content
    assert sensory.get(record.record_id).governance_status == "processed"


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

    assert result["candidates_created"] == 2
    items = pipeline.governance_store.list_candidates()
    assert {item.scope for item in items} == {Scope.GLOBAL.value}
    assert all(item.workspace is None for item in items)


def test_pipeline_marks_bad_json_failed_without_raw_candidate(tmp_path):
    sensory, memory = _stores(tmp_path)
    record = _ingest(sensory, text="raw text that matters")
    pipeline = MemoryPipeline(sensory, memory, _TypedProvider("not json at all"), model="test")

    result = pipeline.process()

    assert result["processed_records"] == 0
    assert result["failed_records"] == 1
    assert pipeline.governance_store.list_candidates() == []
    assert memory.list(status=None) == []
    assert sensory.get(record.record_id).governance_status == "failed"


def test_pipeline_provider_exception_is_retryable(tmp_path):
    sensory, memory = _stores(tmp_path)
    record = _ingest(sensory)
    provider = _RaisingProvider()
    pipeline = MemoryPipeline(sensory, memory, provider, model="test")

    result = pipeline.process()

    assert result["failed_records"] == 1
    assert memory.list(status=None) == []
    assert sensory.get(record.record_id).governance_status == "failed"

    retry = MemoryPipeline(
        sensory,
        memory,
        _TypedProvider(
            '{"facts": [{"content": "Uses pnpm", "memory_type": "user_preference",'
            ' "scope": "workspace"}]}'
        ),
        model="test",
        governance_store=pipeline.governance_store,
    ).process(retry_failed=True)
    assert retry["candidates_created"] == 1
    assert sensory.get(record.record_id).governance_status == "processed"


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

    assert first["candidates_created"] == 1
    assert second["processed_records"] == 0
    assert second["candidates_created"] == 0
    assert provider.calls == 1  # the already-processed record is not re-sent to the model
    assert len(pipeline.governance_store.list_candidates()) == 1


def test_pipeline_empty_facts_creates_nothing(tmp_path):
    sensory, memory = _stores(tmp_path)
    _ingest(sensory, text="hello")
    pipeline = MemoryPipeline(sensory, memory, _TypedProvider('{"facts": []}'), model="test")

    result = pipeline.process()

    assert result["skipped_records"] == 1
    assert result["candidates_created"] == 0
    assert memory.list(status=None) == []

    second = pipeline.process()
    assert second["processed_records"] == 0


def test_pipeline_secret_record_never_reaches_provider(tmp_path):
    sensory, memory = _stores(tmp_path)
    record = sensory.add(
        source_type="notes",
        content_type="document",
        raw_content="password=top-secret",
        external_id="secret-1",
        sensitivity="secret",
    )
    provider = _TypedProvider('{"facts": []}')
    pipeline = MemoryPipeline(sensory, memory, provider, model="test")

    result = pipeline.process()

    assert result["failed_records"] == 1
    assert provider.calls == 0
    assert sensory.get(record.record_id).governance_status == "failed"


def test_pipeline_detects_unlabelled_secret_patterns_before_model_call(tmp_path):
    sensory, memory = _stores(tmp_path)
    _ingest(sensory, text="Use api_key=abc123 for the sample.")
    provider = _TypedProvider('{"facts": []}')

    result = MemoryPipeline(sensory, memory, provider, model="ollama:test").process()

    assert result["failed_records"] == 1
    assert provider.calls == 0


def test_pipeline_bounds_large_model_inputs(tmp_path):
    sensory, memory = _stores(tmp_path)
    _ingest(sensory, text="x" * 100_000)

    class _CapturingProvider(_TypedProvider):
        def complete(self, *, model, messages, tools=None, **settings):
            self.messages = messages
            return super().complete(model=model, messages=messages, tools=tools, **settings)

    provider = _CapturingProvider('{"facts": []}')
    MemoryPipeline(sensory, memory, provider, model="test").process()

    content = provider.messages[-1]["content"]
    assert len(content) < 49_000
    assert "[TRUNCATED" in content
    assert "original_characters=100000" in content


def test_pipeline_session_scope_keeps_conversation_id(tmp_path):
    sensory, memory = _stores(tmp_path)
    sensory.add(
        source_type="smallink",
        content_type="user_input",
        raw_content="Remember this only here",
        external_id="session-fact",
        conversation_id="session-123",
    )
    pipeline = MemoryPipeline(
        sensory,
        memory,
        _TypedProvider(
            '{"facts": [{"content": "Session-only fact", "memory_type": "open_question",'
            ' "scope": "session"}]}'
        ),
        model="test",
    )

    pipeline.process()

    candidate = pipeline.governance_store.list_candidates()[0]
    assert candidate.scope == "session"
    assert candidate.session_id == "session-123"
