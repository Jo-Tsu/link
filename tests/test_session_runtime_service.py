"""Focused coverage for durable session-turn projection."""

from __future__ import annotations

from types import SimpleNamespace

from smallink.conversations import ConversationStore
from smallink.events import Event, EventType
from smallink.lifecycle import AgentPhase, LifecycleTracker
from smallink.permissions import Mode
from smallink.runtime import SessionRuntimeService
from smallink.sensory import SQLiteSensoryStore
from smallink.task import SQLiteTaskRuntimeStore


class StubEngine:
    def __init__(self, workspace, events):
        self.messages = []
        self.permissions = SimpleNamespace(mode=Mode.INTERACTIVE)
        self.executor = SimpleNamespace(cwd=workspace)
        self.agent_name = "code"
        self.model = "test-model"
        self.cited_memories = []
        self._events = list(events)
        self.run_calls = 0
        self.resume_calls = 0

    async def run(self, content, source=None, client_message_id=None):
        self.run_calls += 1
        for event in self._events:
            yield event

    async def retry(self):
        for event in self._events:
            yield event

    async def resume(self):
        self.resume_calls += 1
        for event in self._events:
            yield event


def _service(tmp_path):
    sessions = ConversationStore(tmp_path)
    runtime = SQLiteTaskRuntimeStore(tmp_path / "link.db")
    sensory = SQLiteSensoryStore(tmp_path / "link.db")
    trackers: dict[str, LifecycleTracker] = {}

    def lifecycle_for(session_id: str) -> LifecycleTracker:
        return trackers.setdefault(session_id, LifecycleTracker(session_id))

    return (
        SessionRuntimeService(
            runtime_store=runtime,
            sensory_store=sensory,
            session_store=sessions,
            lifecycle_for=lifecycle_for,
        ),
        runtime,
        sensory,
    )


def _root_run(runtime: SQLiteTaskRuntimeStore, session_id: str):
    task = runtime.get_task_by_session(session_id)
    assert task is not None
    task_run = runtime.list_task_runs(task.task_id)[0]
    return runtime.list_agent_runs(task_run.task_run_id)[0]


async def test_non_streaming_turn_records_output_and_projects_phase(tmp_path):
    service, runtime, sensory = _service(tmp_path)
    engine = StubEngine(
        tmp_path,
        [
            Event(EventType.TURN_START, {"input": "hello"}),
            Event(EventType.ASSISTANT_MESSAGE, {"text": "done"}),
            Event(EventType.TURN_END, {"status": "completed"}),
        ],
    )

    emitted = [
        event
        async for event in service.tracked_engine_events(
            "plain", engine, content="hello"
        )
    ]

    root = _root_run(runtime, "plain")
    assert root.status == "completed"
    assert root.output == {"text": "done", "engine_status": "completed"}
    assert service.get_phase("plain") is AgentPhase.COMPLETING
    assert [
        event.data["phase"]
        for event in emitted
        if event.type is EventType.PHASE_CHANGED
    ] == ["starting", "thinking", "completing"]
    assert {record.content_type for record in sensory.list(conversation_id="plain")} == {
        "user_input",
        "assistant_output",
    }


async def test_tool_events_are_durable_and_captured_as_sensory_records(tmp_path):
    service, runtime, sensory = _service(tmp_path)
    engine = StubEngine(
        tmp_path,
        [
            Event(EventType.TURN_START, {}),
            Event(EventType.TOOL_PROPOSED, {"name": "read_file"}),
            Event(EventType.TOOL_STARTED, {"name": "read_file"}),
            Event(
                EventType.TOOL_FINISHED,
                {"name": "read_file", "status": "ok"},
            ),
            Event(EventType.ASSISTANT_MESSAGE, {"text": "inspected"}),
            Event(EventType.TURN_END, {"status": "completed"}),
        ],
    )

    async for _ in service.tracked_engine_events("tool", engine, content="inspect"):
        pass

    root = _root_run(runtime, "tool")
    assert [event.event_type for event in runtime.list_events(root.agent_run_id)] == [
        "turn_start",
        "tool_proposed",
        "tool_started",
        "tool_finished",
        "assistant_message",
        "turn_end",
    ]
    assert {record.content_type for record in sensory.list(conversation_id="tool")} == {
        "user_input",
        "tool_call",
        "tool_result",
        "assistant_output",
    }


async def test_error_event_finishes_failed_run_and_captures_error(tmp_path):
    service, runtime, sensory = _service(tmp_path)
    engine = StubEngine(
        tmp_path,
        [
            Event(EventType.TURN_START, {}),
            Event(EventType.ERROR, {"error": "provider unavailable"}),
        ],
    )

    async for _ in service.tracked_engine_events("failed", engine, content="hello"):
        pass

    root = _root_run(runtime, "failed")
    assert root.status == "failed"
    assert root.error == "provider unavailable"
    assert service.get_phase("failed") is AgentPhase.ERRORED
    errors = [
        record
        for record in sensory.list(conversation_id="failed")
        if record.content_type == "runtime_error"
    ]
    assert len(errors) == 1
    assert "provider unavailable" in errors[0].raw_content


async def test_resume_reuses_waiting_root_run(tmp_path):
    service, runtime, sensory = _service(tmp_path)
    task_run, waiting = runtime.start_root_run(
        session_id="resume",
        title="Approval required",
        trigger="user",
        agent_role="code",
        model="test-model",
        mode="interactive",
        input_value="write it",
    )
    runtime.append_event(
        waiting.agent_run_id, "permission_required", {"tool": "write_file"}
    )
    engine = StubEngine(
        tmp_path,
        [
            Event(EventType.TURN_START, {"input": "(resumed)"}),
            Event(EventType.TOOL_PROPOSED, {"name": "write_file"}),
            Event(EventType.TOOL_STARTED, {"name": "write_file"}),
            Event(
                EventType.TOOL_FINISHED,
                {"name": "write_file", "status": "ok"},
            ),
            Event(EventType.ASSISTANT_MESSAGE, {"text": "written"}),
            Event(EventType.TURN_END, {"status": "completed"}),
        ],
    )

    async for _ in service.tracked_engine_events("resume", engine, resume=True):
        pass

    task = runtime.get_task_by_session("resume")
    assert task is not None
    assert len(runtime.list_task_runs(task.task_id)) == 1
    root = runtime.get_agent_run(waiting.agent_run_id)
    assert root.task_run_id == task_run.task_run_id
    assert root.status == "completed"
    assert engine.resume_calls == 1
    assert engine.run_calls == 0
    resume_input = next(
        record
        for record in sensory.list(conversation_id="resume")
        if record.content_type == "user_input"
    )
    assert "resume" in resume_input.raw_content
