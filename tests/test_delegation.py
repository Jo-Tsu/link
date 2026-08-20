"""Generic specialist delegation tests."""

from __future__ import annotations

from smallink.agent import build_engine
from smallink.agents import link_agent
from smallink.permissions import Mode
from smallink.providers import AssistantTurn, ModelCapabilities, ProviderClient, ToolCall
from smallink.task import AgentRunObserver, SQLiteTaskRuntimeStore
from smallink.tools import ToolRegistry
from smallink.tools.delegation import build_specialist_engine, delegation_tools


def _text_turn(text: str) -> AssistantTurn:
    return AssistantTurn(text=text, finish_reason="stop")


def _tool_turn(name: str, args: dict, call_id: str = "call_1") -> AssistantTurn:
    return AssistantTurn(
        tool_calls=[ToolCall(id=call_id, name=name, arguments=args)],
        finish_reason="tool_calls",
    )


class ScriptedProvider(ProviderClient):
    def __init__(self, turns: list[AssistantTurn]) -> None:
        self._turns = list(turns)

    def complete(self, *, model, messages, tools=None, **settings):
        return self._turns.pop(0)

    def capabilities(self, model):
        return ModelCapabilities()


def test_specialist_engine_is_read_only_and_non_recursive(tmp_path):
    def knowledge_search(query: str) -> dict:
        return {"query": query, "results": []}

    engine = build_specialist_engine(
        workspace=tmp_path,
        provider=ScriptedProvider([]),
        model="gpt-test",
        role="researcher",
        read_tools=[knowledge_search],
    )
    names = set(engine.registry.names())
    assert {"list_files", "read_file", "grep", "knowledge_search"} <= names
    assert "write_file" not in names
    assert "run_shell" not in names
    assert "delegate_to_agent" not in names
    assert "explore" not in names
    assert engine.permissions.mode is Mode.PLAN


def test_delegate_validates_role_and_exposes_role_enum(tmp_path):
    registry = ToolRegistry()
    registry.register_all(
        delegation_tools(
            workspace=tmp_path,
            provider=ScriptedProvider([]),
            model="gpt-test",
        )
    )
    spec = registry.get("delegate_to_agent")
    assert spec is not None
    role_schema = spec.schema["function"]["parameters"]["properties"]["role"]
    assert role_schema["enum"] == ["researcher", "analyst", "reviewer"]
    assert spec.metadata.risk_level == "low"

    result = registry.execute(
        "delegate_to_agent", {"role": "writer", "task": "change the files"}
    )
    assert result["allowed_roles"] == ["researcher", "analyst", "reviewer"]


def test_delegate_returns_report_and_records_real_child_run(tmp_path):
    store = SQLiteTaskRuntimeStore(tmp_path / "smallink.db")
    task_run, root = store.start_root_run(
        session_id="session-delegate",
        title="Evaluate an option",
        trigger="user",
        agent_role="link",
        model="gpt-test",
        mode="interactive",
        input_value="evaluate",
    )
    registry = ToolRegistry()
    registry.register_all(
        delegation_tools(
            workspace=tmp_path,
            provider=ScriptedProvider([_text_turn("Evidence supports option B.")]),
            model="gpt-test",
            run_observer=AgentRunObserver(store, "session-delegate"),
        )
    )

    result = registry.execute(
        "delegate_to_agent",
        {
            "role": "analyst",
            "task": "Compare options A and B",
            "expected_output": "Recommendation with tradeoffs",
        },
    )
    assert result["agent_role"] == "analyst"
    assert result["report"] == "Evidence supports option B."
    assert result["agent_run_id"]

    runs = store.list_agent_runs(task_run.task_run_id)
    child = next(run for run in runs if run.agent_role == "analyst")
    assert child.parent_agent_run_id == root.agent_run_id
    assert child.root_agent_run_id == root.agent_run_id
    assert child.input["expected_output"] == "Recommendation with tradeoffs"
    assert child.output["report"] == "Evidence supports option B."
    assert child.status == "completed"


def test_specialist_cannot_write_even_when_model_requests_it(tmp_path):
    registry = ToolRegistry()
    registry.register_all(
        delegation_tools(
            workspace=tmp_path,
            provider=ScriptedProvider(
                [
                    _tool_turn("write_file", {"path": "unsafe.txt", "content": "no"}),
                    _text_turn("The write was unavailable; review only."),
                ]
            ),
            model="gpt-test",
        )
    )
    result = registry.execute(
        "delegate_to_agent", {"role": "reviewer", "task": "Review this workspace"}
    )
    assert not (tmp_path / "unsafe.txt").exists()
    assert result["report"] == "The write was unavailable; review only."


def test_workspace_backed_link_registers_generic_delegation(tmp_path):
    class StubProvider:
        def complete(self, **kwargs):  # pragma: no cover
            raise NotImplementedError

        def capabilities(self, model):
            return ModelCapabilities()

    engine = build_engine(
        agent=link_agent(), workspace=tmp_path, provider=StubProvider()
    )
    try:
        assert "delegate_to_agent" in engine.registry.names()
    finally:
        engine.executor.close()
