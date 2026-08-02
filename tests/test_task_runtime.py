"""Durable Link task/runtime records and their server read API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from smallink.providers import AssistantTurn, ModelCapabilities, ProviderClient
from smallink.server import SessionManager, create_app
from smallink.task import SQLiteTaskRuntimeStore


class _Provider(ProviderClient):
    def complete(self, *, model, messages, tools=None, **settings):
        return AssistantTurn(text="runtime complete", finish_reason="stop")

    def capabilities(self, model):
        return ModelCapabilities()


def test_runtime_store_persists_task_run_agent_and_events(tmp_path):
    path = tmp_path / "link.db"
    store = SQLiteTaskRuntimeStore(path)
    task_run, agent_run = store.start_root_run(
        session_id="session-1",
        title="Build the runtime",
        trigger="user",
        agent_role="link",
        model="gpt-test",
        mode="interactive",
        input_value={"text": "start"},
        project_id="/workspace",
    )

    first = store.append_event(
        agent_run.agent_run_id, "turn_start", {"input": "start"}
    )
    second = store.append_event(
        agent_run.agent_run_id,
        "permission_required",
        {"tool": "write_file"},
    )
    assert first.sequence < second.sequence
    assert store.get_agent_run(agent_run.agent_run_id).status == "waiting_approval"
    assert store.get_task_run(task_run.task_run_id).status == "waiting_approval"

    finished = store.finish_agent_run(
        agent_run.agent_run_id,
        status="completed",
        output={"text": "done"},
    )
    assert finished.status == "completed"
    assert finished.output == {"text": "done"}

    reopened = SQLiteTaskRuntimeStore(path)
    task = reopened.get_task_by_session("session-1")
    assert task is not None
    assert task.title == "Build the runtime"
    assert task.status == "completed"
    assert [event.event_type for event in reopened.list_events(agent_run.agent_run_id)] == [
        "turn_start",
        "permission_required",
    ]


def test_runtime_store_links_child_agent_to_root(tmp_path):
    store = SQLiteTaskRuntimeStore(tmp_path / "link.db")
    task_run, root = store.start_root_run(
        session_id="session-2",
        title="Explore architecture",
        trigger="user",
        agent_role="link",
        model="gpt-test",
        mode="interactive",
        input_value="inspect",
    )
    child = store.start_child_run(
        parent_agent_run_id=root.agent_run_id,
        agent_role="explorer",
        model="gpt-test",
        input_value="find the retry path",
    )

    assert child.task_run_id == task_run.task_run_id
    assert child.parent_agent_run_id == root.agent_run_id
    assert child.root_agent_run_id == root.agent_run_id
    assert store.active_root_for_session("session-2") == root

    store.finish_agent_run(child.agent_run_id, status="completed", output="report")
    store.finish_agent_run(root.agent_run_id, status="completed", output="answer")
    runs = store.list_agent_runs(task_run.task_run_id)
    assert [run.agent_role for run in runs] == ["link", "explorer"]
    collaborations = store.list_collaborative_runs()
    assert len(collaborations) == 1
    assert collaborations[0]["task_run_id"] == task_run.task_run_id
    assert collaborations[0]["agent_count"] == 2
    assert collaborations[0]["child_agent_count"] == 1
    assert set(collaborations[0]["agent_roles"]) == {"link", "explorer"}


def test_runtime_store_cancels_running_but_preserves_waiting_approval(tmp_path):
    store = SQLiteTaskRuntimeStore(tmp_path / "link.db")
    task_run, root = store.start_root_run(
        session_id="session-restart",
        title="Interrupted work",
        trigger="user",
        agent_role="link",
        model="gpt-test",
        mode="interactive",
        input_value="work",
    )
    child = store.start_child_run(
        parent_agent_run_id=root.agent_run_id,
        agent_role="explorer",
        model="gpt-test",
        input_value="inspect",
    )
    store.append_event(
        root.agent_run_id, "permission_required", {"tool": "write_file"}
    )

    assert store.recover_incomplete_runs() == 1
    assert store.get_task_run(task_run.task_run_id).status == "waiting_approval"
    assert store.get_agent_run(root.agent_run_id).status == "waiting_approval"
    assert store.get_agent_run(child.agent_run_id).status == "cancelled"
    assert store.get_task_by_session("session-restart").status == "waiting_approval"
    resumed = store.resume_waiting_root("session-restart")
    assert resumed is not None and resumed.agent_run_id == root.agent_run_id
    assert store.get_task_run(task_run.task_run_id).status == "running"


async def test_tracked_runtime_omits_streaming_token_deltas(tmp_path):
    from smallink.events import Event, EventType

    manager = SessionManager(workspace=tmp_path, provider=_Provider())
    engine = manager.get_engine("compact-events", workspace=str(tmp_path), agent="code")

    async def fake_run(_content, source=None):
        yield Event(EventType.ASSISTANT_DELTA, {"text": "one "})
        yield Event(EventType.REASONING_DELTA, {"text": "thinking "})
        yield Event(EventType.ASSISTANT_DELTA, {"text": "two"})
        yield Event(EventType.ASSISTANT_MESSAGE, {"text": "one two"})
        yield Event(EventType.TURN_END, {"status": "completed"})

    engine.run = fake_run
    async for _ in manager.tracked_engine_events(
        "compact-events", engine, content="hello"
    ):
        pass

    task = manager.runtime_store.get_task_by_session("compact-events")
    run = manager.runtime_store.list_task_runs(task.task_id)[0]
    agent = manager.runtime_store.list_agent_runs(run.task_run_id)[0]
    event_types = [
        event.event_type for event in manager.runtime_store.list_events(agent.agent_run_id)
    ]
    assert event_types == ["assistant_message", "turn_end"]


def test_websocket_turn_creates_queryable_runtime_tree(tmp_path):
    manager = SessionManager(workspace=tmp_path, provider=_Provider())
    client = TestClient(create_app(manager))

    with client.websocket_connect("/ws/session/runtime-session?agent=link") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "user_message", "text": "Record this task"})
        while ws.receive_json()["type"] != "turn_done":
            pass

    task_response = client.get("/v1/sessions/runtime-session/task")
    assert task_response.status_code == 200
    task = task_response.json()
    assert task["title"] == "Record this task"
    assert task["status"] == "completed"
    assert len(task["runs"]) == 1

    task_run = client.get(f"/v1/task-runs/{task['runs'][0]['task_run_id']}").json()
    assert len(task_run["agent_runs"]) == 1
    agent_run = task_run["agent_runs"][0]
    assert agent_run["status"] == "completed"
    assert agent_run["output"]["text"] == "runtime complete"

    events = client.get(
        f"/v1/agent-runs/{agent_run['agent_run_id']}/events"
    ).json()["events"]
    assert events[0]["event_type"] == "turn_start"
    assert events[-1]["event_type"] == "turn_end"


def test_runtime_api_returns_not_found(tmp_path):
    client = TestClient(
        create_app(SessionManager(workspace=tmp_path, provider=_Provider()))
    )
    assert client.get("/v1/tasks/missing").status_code == 404
    assert client.get("/v1/task-runs/missing").status_code == 404
    assert client.get("/v1/agent-runs/missing").status_code == 404
    assert client.get("/v1/agent-runs/missing/events").status_code == 404


def test_collaboration_api_only_returns_runs_with_child_agents(tmp_path):
    manager = SessionManager(workspace=tmp_path, provider=_Provider())
    _plain_run, _plain_root = manager.runtime_store.start_root_run(
        session_id="plain-session",
        title="Single agent task",
        trigger="user",
        agent_role="link",
        model="gpt-test",
        mode="interactive",
        input_value="work alone",
    )
    task_run, root = manager.runtime_store.start_root_run(
        session_id="collaboration-session",
        title="Delegated task",
        trigger="user",
        agent_role="code",
        model="gpt-test",
        mode="interactive",
        input_value="inspect the project",
    )
    manager.runtime_store.start_child_run(
        parent_agent_run_id=root.agent_run_id,
        agent_role="explorer",
        model="gpt-test",
        input_value={"task": "map the project"},
    )

    client = TestClient(create_app(manager))
    response = client.get("/v1/agent-collaborations")
    assert response.status_code == 200
    collaborations = response.json()["collaborations"]
    assert [item["task_run_id"] for item in collaborations] == [task_run.task_run_id]
