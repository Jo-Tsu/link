"""Model purpose tags (chat/memory/title) let a model be assigned to specific uses;
the memory pipeline routes to the model tagged 'memory', falling back to the default."""

from __future__ import annotations

from smallink.providers import AssistantTurn, ModelCapabilities, ProviderClient
from smallink.server import SessionManager


class _RecordingProvider(ProviderClient):
    """Records the model name each complete() call used, so tests can assert routing."""

    def __init__(self):
        self.models_seen: list[str] = []

    def complete(self, *, model, messages, tools=None, **settings):
        self.models_seen.append(model)
        return AssistantTurn(text='{"facts": []}', finish_reason="stop")

    def capabilities(self, model):
        return ModelCapabilities()


def _manager(tmp_path):
    return SessionManager(data_dir=tmp_path / "data", provider=_RecordingProvider())


def test_set_and_get_model_purposes(tmp_path):
    mgr = _manager(tmp_path)
    res = mgr.set_model_purposes("ollama:qwen3", ["memory", "chat"])
    assert res["ok"] is True
    assert res["model_purposes"] == {"ollama:qwen3": ["memory", "chat"]}
    assert "memory" in res["purposes"] and "chat" in res["purposes"] and "title" in res["purposes"]


def test_unknown_purposes_are_rejected(tmp_path):
    mgr = _manager(tmp_path)
    res = mgr.set_model_purposes("m1", ["memory", "bogus"])
    assert res["model_purposes"] == {"m1": ["memory"]}  # bogus dropped


def test_clearing_all_tags_removes_the_entry(tmp_path):
    mgr = _manager(tmp_path)
    mgr.set_model_purposes("m1", ["memory"])
    res = mgr.set_model_purposes("m1", [])
    assert "m1" not in res["model_purposes"]


def test_model_for_purpose_resolution(tmp_path):
    mgr = _manager(tmp_path)
    default = mgr.model
    # No tags → fall back to the global default.
    assert mgr.model_for_purpose("memory") == default
    # One tagged model → that model.
    mgr.set_model_purposes("ollama:qwen3", ["memory"])
    assert mgr.model_for_purpose("memory") == "ollama:qwen3"
    # An untagged purpose still falls back.
    assert mgr.model_for_purpose("title") == default
    # If the default model is itself tagged, it wins over another tagged model.
    mgr.set_model_purposes(default, ["memory"])
    assert mgr.model_for_purpose("memory") == default


def test_pipeline_uses_memory_tagged_model(tmp_path):
    mgr = _manager(tmp_path)
    mgr.set_model_purposes("ollama:qwen3", ["memory"])
    # Ingest one raw record so the pipeline has something to process.
    mgr.ingest_sensory_record(
        {"source_type": "t", "content_type": "doc", "raw_content": "hello", "external_id": "1"}
    )
    mgr.run_memory_pipeline(limit=5)
    # The pipeline called the memory-tagged model, not the global default.
    assert mgr.provider.models_seen == ["ollama:qwen3"]


def test_pipeline_falls_back_to_default_when_untagged(tmp_path):
    mgr = _manager(tmp_path)
    mgr.ingest_sensory_record(
        {"source_type": "t", "content_type": "doc", "raw_content": "hello", "external_id": "1"}
    )
    mgr.run_memory_pipeline(limit=5)
    assert mgr.provider.models_seen == [mgr.model]
