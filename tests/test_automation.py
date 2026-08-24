"""Tests for automation — models, store, next-run math, scheduler loop, tools, REST.

No network and no LLM: the scheduler's runner is injected with a fake; the agent-facing tools
operate on a real SQLite store; execution policy (catch-up, overlap) is exercised directly.
"""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timezone

import pytest

from smallink.automation import (
    Schedule,
    ScheduledTask,
    Scheduler,
    TaskRun,
    TaskStore,
    compute_next_run,
)
from smallink.automation.tools import scheduling_tools


def _task(**kw) -> ScheduledTask:
    kw.setdefault("title", "Daily brief")
    kw.setdefault("instructions", "search the web and brief me")
    kw.setdefault("schedule", Schedule(kind="cron", cron="10 19 * * *"))
    kw.setdefault("workspace", "/tmp/cw-auto")
    return ScheduledTask(**kw)


# -- model / schedule ----------------------------------------------------------
def test_schedule_human():
    assert Schedule("cron", cron="10 19 * * *").human() == "Every day at ~7:10 PM"
    assert "Monday" in Schedule("cron", cron="0 9 * * 0").human()
    assert Schedule("cron", cron="0 9 5 * *").human() == "Monthly on day 5 at ~9:00 AM"
    assert Schedule("once", fire_at="2026-07-01T09:00:00").human().startswith("Once at")


def test_task_gets_own_thread_id():
    t = _task()
    assert t.task_session_id == f"__task__{t.id}"
    assert t.public()["schedule"] == "Every day at ~7:10 PM"


def test_compute_next_run_cron_explicit_utc():
    t = _task(schedule=Schedule(kind="cron", cron="10 19 * * *", timezone="UTC"))
    after = datetime(2026, 6, 5, 18, 0, tzinfo=timezone.utc).timestamp()
    nxt = compute_next_run(t, after=after)
    assert datetime.fromtimestamp(nxt, tz=timezone.utc) == datetime(
        2026, 6, 5, 19, 10, tzinfo=timezone.utc
    )


def test_compute_next_run_defaults_to_local_time():
    """Default 'local' tz: '7:10pm' fires at 19:10 on the *machine's* clock, not UTC."""
    t = _task()  # Schedule default timezone == "local"
    assert t.schedule.timezone == "local"
    nxt = compute_next_run(t)
    local = datetime.fromtimestamp(nxt).astimezone()
    assert (local.hour, local.minute) == (19, 10)


def test_compute_next_run_once_in_past_is_none():
    past = "2020-01-01T00:00:00+00:00"
    t = _task(schedule=Schedule(kind="once", fire_at=past))
    assert compute_next_run(t) is None


# -- store ---------------------------------------------------------------------
def test_store_crud_and_due(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    t = _task(
        schedule=Schedule(kind="cron", cron="* * * * *")
    )  # every minute → due soon
    store.save(t)
    assert store.get(t.id).title == "Daily brief"
    assert [x.id for x in store.list()] == [t.id]
    # next_run computed + due() finds it once we're past next_run
    due = store.due(now=t.next_run + 1)
    assert [x.id for x in due] == [t.id]
    # disabled tasks are not due
    t.enabled = False
    store.save(t)
    assert store.due(now=t.next_run + 1 if t.next_run else 9e9) == []
    assert store.delete(t.id) is True and store.get(t.id) is None


def test_store_runs_history(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    t = _task()
    store.save(t)
    store.add_run(TaskRun(task_id=t.id, status="ok", result_text="hi"))
    store.add_run(TaskRun(task_id=t.id, status="error", error="boom"))
    runs = store.runs(t.id)
    assert len(runs) == 2 and runs[0].status in ("ok", "error")


def test_store_transaction_rolls_back_nested_writes(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    task = _task()

    with pytest.raises(RuntimeError):
        with store.transaction():
            store.save(task)
            store.add_run(TaskRun(task_id=task.id, status="ok"))
            raise RuntimeError("boom")

    assert store.get(task.id) is None
    assert store.runs(task.id) == []


# -- scheduler loop ------------------------------------------------------------
async def test_scheduler_runs_due_task_and_advances(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    t = _task(schedule=Schedule(kind="cron", cron="* * * * *"))
    store.save(t)
    # force it due now
    t.next_run = 1.0
    store.save(t)
    t.next_run = 1.0  # save() recomputes; push it into the past again
    store._conn.execute("UPDATE scheduled_tasks SET next_run=1.0 WHERE id=?", (t.id,))
    store._conn.commit()

    ran: list[str] = []

    async def runner(task, trigger):
        ran.append(task.id)
        return TaskRun(task_id=task.id, status="ok", trigger=trigger)

    sched = Scheduler(store, runner, tick_seconds=0.05)
    sched.start()
    await asyncio.sleep(0.2)
    await sched.stop()
    assert ran == [t.id]
    advanced = store.get(t.id)
    assert advanced.run_count == 1 and advanced.last_status == "ok"
    assert (
        advanced.next_run is not None and advanced.next_run > 1.0
    )  # moved to the future


async def test_scheduler_skips_overlapping_run(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    t = _task()
    store.save(t)
    gate = asyncio.Event()
    started = 0

    async def slow_runner(task, trigger):
        nonlocal started
        started += 1
        await gate.wait()
        return TaskRun(task_id=task.id, status="ok")

    sched = Scheduler(store, slow_runner)
    first = asyncio.create_task(sched.run_task(t, trigger="manual"))
    await asyncio.sleep(0.02)
    second = await sched.run_task(t, trigger="manual")  # overlaps → skipped
    assert second is None and started == 1
    gate.set()
    await first


async def test_scheduler_reloads_fresh_task_and_uses_updated_fields(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    task = _task(schedule=Schedule(kind="cron", cron="* * * * *"), instructions="stale")
    store.save(task)
    store._conn.execute("UPDATE scheduled_tasks SET next_run=1.0 WHERE id=?", (task.id,))
    store._conn.commit()
    store.save(
        ScheduledTask.from_dict(
            {
                **store.get(task.id).to_dict(),
                "instructions": "fresh",
                "always_allowed_tools": ["send_message slack:C1"],
            }
        )
    )
    store._conn.execute("UPDATE scheduled_tasks SET next_run=1.0 WHERE id=?", (task.id,))
    store._conn.commit()
    seen: list[tuple[str, list[str]]] = []

    async def runner(fresh, trigger):
        seen.append((fresh.instructions, list(fresh.always_allowed_tools)))
        return TaskRun(task_id=fresh.id, status="ok", trigger=trigger, finished_at=time.time())

    sched = Scheduler(store, runner)
    run = await sched.run_task(task, trigger="schedule")

    assert run is not None and run.status == "ok"
    assert seen == [("fresh", ["send_message slack:C1"])]


async def test_scheduler_skips_deleted_disabled_and_not_due_fresh_task(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    deleted = _task(id="task-deleted", schedule=Schedule(kind="cron", cron="* * * * *"))
    disabled = _task(id="task-disabled", schedule=Schedule(kind="cron", cron="* * * * *"))
    not_due = _task(id="task-not-due", schedule=Schedule(kind="cron", cron="* * * * *"))
    store.save(disabled)
    store.save(not_due)
    store._conn.execute(
        "UPDATE scheduled_tasks SET next_run=1.0 WHERE id IN (?, ?)", (disabled.id, not_due.id)
    )
    store._conn.commit()
    disabled_fresh = store.get(disabled.id)
    disabled_fresh.enabled = False
    store.save(disabled_fresh)
    store._conn.execute(
        "UPDATE scheduled_tasks SET next_run=? WHERE id=?",
        (time.time() + 3600, not_due.id),
    )
    store._conn.commit()
    ran: list[str] = []

    async def runner(task, trigger):
        ran.append(task.id)
        return TaskRun(task_id=task.id, status="ok", trigger=trigger, finished_at=time.time())

    sched = Scheduler(store, runner)

    assert await sched.run_task(deleted, trigger="schedule") is None
    assert await sched.run_task(disabled, trigger="schedule") is None
    assert await sched.run_task(not_due, trigger="schedule") is None
    assert ran == []


async def test_scheduler_exception_records_run_once(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    task = _task(schedule=Schedule(kind="cron", cron="* * * * *"))
    store.save(task)
    store._conn.execute("UPDATE scheduled_tasks SET next_run=1.0 WHERE id=?", (task.id,))
    store._conn.commit()

    async def runner(task, trigger):
        raise RuntimeError("boom")

    sched = Scheduler(store, runner)
    run = await sched.run_task(task, trigger="schedule")

    assert run is not None and run.status == "error"
    runs = store.runs(task.id)
    assert len(runs) == 1
    assert runs[0].run_id == run.run_id
    assert store.get(task.id).run_count == 1
    assert store.get(task.id).last_status == "error"


# -- agent-facing tools --------------------------------------------------------
def test_create_and_list_tools(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    origin = {
        "surface": "link",
        "session_id": "s1",
        "workspace": "/tmp/ws",
        "agent": "link",
    }
    tools = {
        t.__name__: t
        for t in scheduling_tools(store, origin=origin, default_workspace="/tmp/ws")
    }

    out = tools["create_scheduled_task"](
        title="Brief", instructions="brief me", cron="10 19 * * *"
    )
    assert out["ok"] and out["schedule"] == "Every day at ~7:10 PM"
    # create surfaces a confirm card → gated
    assert (
        tools["create_scheduled_task"].__aisuite_tool_metadata__.requires_approval
        is True
    )

    listed = tools["list_scheduled_tasks"]()["tasks"]
    assert (
        len(listed) == 1
        and listed[0]["origin_session_id" if False else "title"] == "Brief"
    )
    saved = store.list()[0]
    assert saved.origin_session_id == "s1" and saved.workspace == "/tmp/ws"

    bad = tools["create_scheduled_task"](title="x", instructions="y", cron="not-a-cron")
    assert "invalid cron" in bad["error"]
    none = tools["create_scheduled_task"](title="x", instructions="y")
    assert "error" in none  # neither cron nor fire_at


def test_update_and_delete_tools(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    tools = {
        t.__name__: t
        for t in scheduling_tools(
            store, origin={"workspace": "/tmp/ws"}, default_workspace="/tmp/ws"
        )
    }
    tid = tools["create_scheduled_task"](
        title="X", instructions="do", cron="0 9 * * *"
    )["id"]
    assert (
        tools["update_scheduled_task"](id=tid, enabled=False)["task"]["enabled"]
        is False
    )
    assert store.get(tid).next_run is None  # disabled → no next run
    assert tools["delete_scheduled_task"](id=tid)["ok"] is True
    assert tools["update_scheduled_task"](id=tid)["error"]


# -- run persists as a continuable session -------------------------------------
async def test_scheduled_run_persists_continuable_session(tmp_path, monkeypatch):
    from smallink.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from smallink.server.manager import SessionManager, _last_assistant_text

    class ScriptedProvider(ProviderClient):
        def __init__(self, turns):
            self._turns = list(turns)

        def complete(self, *, model, messages, tools=None, **settings):
            return self._turns.pop(0)

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("LINK_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    # two turns: the scheduled run, then a follow-up question
    provider = ScriptedProvider(
        [
            AssistantTurn(text="Daily brief: all quiet.", finish_reason="stop"),
            AssistantTurn(text="Sure — here is more detail.", finish_reason="stop"),
        ]
    )
    manager = SessionManager(data_dir=tmp_path / "data", provider=provider)
    task = _task(workspace=str(ws), agent="link")
    manager.task_store.save(task)

    run = await manager._run_scheduled_task(task, trigger="manual")
    assert run.status == "ok" and run.session_id == f"__run__{run.run_id}"
    assert run.result_text == "Daily brief: all quiet."

    # the run is now a real, reopenable session with the transcript
    record = manager.session_store.load(run.session_id)
    assert (
        record is not None
        and record.workspace
        and any("Scheduled run" in (m.get("content") or "") for m in record.messages)
    )
    # …and it is continuable: a follow-up turn reuses the same thread
    engine = manager.get_engine(run.session_id, workspace=str(ws), agent="link")
    async for _ in engine.run("tell me more"):
        pass
    assert _last_assistant_text(engine.messages) == "Sure — here is more detail."


def test_task_engine_has_no_scheduling_tools(tmp_path, monkeypatch):
    """A scheduled run executes its instructions — it must not be able to (re)schedule. With
    instructions like 'every day at 5:32pm, prepare…', an agent holding create_scheduled_task
    creates another automation instead of doing the task."""
    from smallink.providers import (
        AssistantTurn as _AT,
        ModelCapabilities,
        ProviderClient,
    )
    from smallink.server import SessionManager

    class _Provider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return _AT(text="ok", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("LINK_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=_Provider())
    task = _task(workspace=str(ws), agent="link")
    manager.task_store.save(task)

    engine = manager._build_task_engine(task, session_id="__run__test")
    names = set(engine.registry.names())
    assert "create_scheduled_task" not in names
    assert "update_scheduled_task" not in names
    assert "write_file" in names  # the deliverable tools are still there


async def test_manual_run_prepare_and_finalize(tmp_path, monkeypatch):
    from smallink.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from smallink.server.manager import SessionManager

    class ScriptedProvider(ProviderClient):
        def __init__(self, turns):
            self._turns = list(turns)

        def complete(self, *, model, messages, tools=None, **settings):
            return self._turns.pop(0)

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("LINK_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(
        data_dir=tmp_path / "data",
        provider=ScriptedProvider(
            [AssistantTurn(text="Done — briefing ready.", finish_reason="stop")]
        ),
    )
    task = _task(workspace=str(ws), agent="link")
    manager.task_store.save(task)

    # prepare: a "running" run + a session to open live (NOT executed yet)
    prep = manager.prepare_manual_run(task.id)
    assert prep["ok"] and prep["session_id"] == f"__run__{prep['run_id']}"
    # The prompt wraps the instructions in execute-now framing (so the live agent runs the task
    # instead of re-scheduling it) and carries them verbatim.
    assert prep["agent"] == "link"
    assert task.instructions in prep["prompt"]
    assert "do not create or modify any scheduled tasks" in prep["prompt"]
    assert manager.task_store.runs(task.id)[0].status == "running"

    # the GUI drives the run live over the session, then finalize records the outcome
    engine = manager.get_engine(prep["session_id"], workspace=str(ws), agent="link")
    async for _ in engine.run(prep["prompt"]):
        pass
    manager.save(prep["session_id"], engine)

    out = manager.finalize_manual_run(task.id, prep["run_id"])
    assert out["ok"] and out["run"]["status"] == "ok"
    assert out["run"]["result_text"] == "Done — briefing ready."
    assert manager.task_store.get(task.id).run_count == 1


async def test_manual_run_uses_runtime_failure_as_authoritative_outcome(tmp_path):
    from smallink.providers import ModelCapabilities, ProviderClient
    from smallink.server.manager import SessionManager

    class FailingProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            raise RuntimeError("provider unavailable")

        def capabilities(self, model):
            return ModelCapabilities()

    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=FailingProvider())
    task = _task(workspace=str(ws), agent="link")
    manager.task_store.save(task)
    prep = manager.prepare_manual_run(task.id)
    engine = manager.get_engine(prep["session_id"], workspace=str(ws), agent="link")

    async for _ in manager.tracked_engine_events(
        prep["session_id"], engine, content=prep["prompt"]
    ):
        pass
    manager.save(prep["session_id"], engine)
    out = manager.finalize_manual_run(task.id, prep["run_id"])

    assert out["ok"] and out["run"]["status"] == "error"
    assert "provider unavailable" in out["run"]["error"]
    assert manager.task_store.get(task.id).last_status == "error"


def test_delete_automation_cannot_be_undone_by_concurrent_finalize(
    tmp_path, monkeypatch
):
    from smallink.server.manager import SessionManager
    from smallink.sessions import SessionRecord

    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data")
    task = _task(workspace=str(ws), agent="link")
    manager.task_store.save(task)
    prepared = manager.prepare_manual_run(task.id)
    manager.session_store.save(
        SessionRecord(
            session_id=prepared["session_id"],
            workspace=str(ws),
            model=manager.model,
            mode="interactive",
            messages=[{"role": "assistant", "content": "done"}],
            agent="link",
        )
    )

    finalize_entered = threading.Event()
    release_finalize = threading.Event()
    original_load = manager.session_store.load

    def blocking_load(session_id):
        if session_id == prepared["session_id"]:
            finalize_entered.set()
            release_finalize.wait(timeout=5)
        return original_load(session_id)

    monkeypatch.setattr(manager.session_store, "load", blocking_load)
    finalized: dict[str, object] = {}
    finalize_thread = threading.Thread(
        target=lambda: finalized.update(
            manager.finalize_manual_run(task.id, prepared["run_id"])
        )
    )
    finalize_thread.start()
    assert finalize_entered.wait(timeout=5)

    deleted: dict[str, object] = {}
    delete_thread = threading.Thread(
        target=lambda: deleted.update(manager.delete_automation(task.id))
    )
    delete_thread.start()
    assert delete_thread.is_alive()

    release_finalize.set()
    finalize_thread.join(timeout=5)
    delete_thread.join(timeout=5)

    assert finalized["ok"] is True
    assert deleted["ok"] is True
    assert manager.task_store.get(task.id) is None
    assert manager.task_store.find_run(prepared["run_id"]) is None


def test_delete_automation_cannot_be_undone_by_concurrent_update(
    tmp_path, monkeypatch
):
    from smallink.server.manager import SessionManager

    manager = SessionManager(data_dir=tmp_path / "data")
    task = _task(workspace=str(tmp_path), agent="link")
    manager.task_store.save(task)
    update_entered = threading.Event()
    release_update = threading.Event()
    original_save = manager.task_store.save

    def blocking_save(updated):
        if updated.id == task.id and updated.title == "Updated":
            update_entered.set()
            release_update.wait(timeout=5)
        return original_save(updated)

    monkeypatch.setattr(manager.task_store, "save", blocking_save)
    updated: dict[str, object] = {}
    update_thread = threading.Thread(
        target=lambda: updated.update(
            manager.update_automation(task.id, {"title": "Updated"})
        )
    )
    update_thread.start()
    assert update_entered.wait(timeout=5)

    deleted: dict[str, object] = {}
    delete_thread = threading.Thread(
        target=lambda: deleted.update(manager.delete_automation(task.id))
    )
    delete_thread.start()
    assert delete_thread.is_alive()

    release_update.set()
    update_thread.join(timeout=5)
    delete_thread.join(timeout=5)

    assert updated["ok"] is True
    assert deleted["ok"] is True
    assert manager.task_store.get(task.id) is None


def test_automation_store_recovers_runs_left_active_by_restart(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    task = _task()
    store.save(task)
    run = store.add_run(TaskRun(task_id=task.id, trigger="manual"))

    assert store.recover_incomplete_runs() == 1
    recovered = store.find_run(run.run_id)
    assert recovered.status == "interrupted"
    assert "restarted" in recovered.error
    assert store.get(task.id).last_status == "interrupted"


def test_automation_store_preserves_completed_runtime_for_late_finalize(tmp_path):
    store = TaskStore(tmp_path / "auto.db")
    task = _task()
    store.save(task)
    run = store.add_run(TaskRun(task_id=task.id, trigger="manual"))

    assert store.recover_incomplete_runs(
        runtime_status=lambda session_id: (
            "completed" if session_id == run.session_id else None
        )
    ) == 0
    preserved = store.find_run(run.run_id)
    assert preserved is not None
    assert preserved.status == "running"
    assert store.get(task.id).run_count == 0


def test_manager_finalizes_completed_manual_run_after_restart(tmp_path):
    from smallink.server.manager import SessionManager
    from smallink.sessions import SessionRecord

    data_dir = tmp_path / "data"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    manager = SessionManager(data_dir=data_dir)
    task = _task(workspace=str(workspace), agent="link")
    manager.task_store.save(task)
    prepared = manager.prepare_manual_run(task.id)
    runtime_run, root = manager.runtime_store.start_root_run(
        session_id=prepared["session_id"],
        title=task.title,
        trigger="user",
        agent_role="link",
        model=manager.model,
        mode="interactive",
        input_value=prepared["prompt"],
    )
    manager.runtime_store.finish_agent_run(
        root.agent_run_id,
        status="completed",
        output={"text": "Recovered result"},
    )
    assert manager.runtime_store.get_task_run(runtime_run.task_run_id).status == "completed"
    manager.session_store.save(
        SessionRecord(
            session_id=prepared["session_id"],
            workspace=str(workspace),
            model=manager.model,
            mode="interactive",
            messages=[{"role": "assistant", "content": "Recovered result"}],
            agent="link",
        )
    )
    manager.task_store.close()
    manager.runtime_store.close()
    manager.session_store.close()

    recovered = SessionManager(data_dir=data_dir)
    run = recovered.get_automation(task.id)["runs"][0]
    assert run["status"] == "ok"
    assert run["result_text"] == "Recovered result"
    assert recovered.task_store.get(task.id).run_count == 1


def test_restart_uses_runtime_final_output_not_checkpoint_assistant_text(tmp_path):
    from smallink.server.manager import SessionManager
    from smallink.sessions import SessionRecord

    data_dir = tmp_path / "data"
    workspace = tmp_path / "ws"
    workspace.mkdir()
    manager = SessionManager(data_dir=data_dir)
    task = _task(workspace=str(workspace), agent="link")
    manager.task_store.save(task)
    prepared = manager.prepare_manual_run(task.id)
    runtime_run, root = manager.runtime_store.start_root_run(
        session_id=prepared["session_id"],
        title=task.title,
        trigger="user",
        agent_role="link",
        model=manager.model,
        mode="interactive",
        input_value=prepared["prompt"],
    )
    manager.runtime_store.finish_agent_run(
        root.agent_run_id, status="completed", output={"text": "Final result"}
    )
    assert manager.runtime_store.get_task_run(runtime_run.task_run_id).status == "completed"
    manager.session_store.save(
        SessionRecord(
            session_id=prepared["session_id"],
            workspace=str(workspace),
            model=manager.model,
            mode="interactive",
            messages=[
                {
                    "role": "assistant",
                    "content": "Working on it",
                    "tool_calls": [{"id": "call-1"}],
                }
            ],
            agent="link",
        )
    )
    manager.task_store.close()
    manager.runtime_store.close()
    manager.session_store.close()

    recovered = SessionManager(data_dir=data_dir)
    run = recovered.get_automation(task.id)["runs"][0]
    assert run["status"] == "ok"
    assert run["result_text"] == "Final result"


# -- REST ----------------------------------------------------------------------
def test_automations_rest(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from smallink.server.app import create_app
    from smallink.server.manager import SessionManager

    monkeypatch.setenv("LINK_STATE_DIR", str(tmp_path / "state"))
    manager = SessionManager(data_dir=tmp_path / "data")
    # seed a task directly via the store
    t = _task(workspace=str(tmp_path / "ws"))
    manager.task_store.save(t)
    client = TestClient(create_app(manager))

    tasks = client.get("/v1/automations").json()["tasks"]
    assert (
        tasks[0]["title"] == "Daily brief"
        and tasks[0]["schedule"] == "Every day at ~7:10 PM"
    )
    assert (
        client.patch(f"/v1/automations/{t.id}", json={"enabled": False}).json()["task"][
            "enabled"
        ]
        is False
    )
    assert client.get(f"/v1/automations/{t.id}").json()["task"]["id"] == t.id
    assert client.delete(f"/v1/automations/{t.id}").json()["ok"] is True


# -- unseen-run tracking (UX-023 sidebar badges) --------------------------------
def test_unseen_runs_counted_and_cleared_by_mark_seen(tmp_path, monkeypatch):
    """list_automations surfaces unseen counts (runs after the seen mark), with
    unseen_failed keyed to the NEWEST unseen run; mark_automation_seen clears them
    and later runs count fresh."""
    monkeypatch.setenv("LINK_STATE_DIR", str(tmp_path / "state"))
    from smallink.server.manager import SessionManager

    manager = SessionManager(data_dir=tmp_path / "data")
    t = manager.task_store.save(_task())
    manager.task_store.add_run(TaskRun(task_id=t.id, status="ok"))
    manager.task_store.add_run(TaskRun(task_id=t.id, status="error"))

    row = manager.list_automations()["tasks"][0]
    assert row["unseen_runs"] == 2
    assert row["unseen_failed"] is True  # newest unseen run errored

    assert manager.mark_automation_seen(t.id)["ok"]
    row = manager.list_automations()["tasks"][0]
    assert row["unseen_runs"] == 0 and row["unseen_failed"] is False

    time.sleep(0.01)  # a run strictly after the seen mark
    manager.task_store.add_run(TaskRun(task_id=t.id, status="ok"))
    row = manager.list_automations()["tasks"][0]
    assert row["unseen_runs"] == 1 and row["unseen_failed"] is False

    assert not manager.mark_automation_seen("task-nope")["ok"]


@pytest.mark.asyncio
async def test_scheduled_run_broadcasts_run_started_event(tmp_path, monkeypatch):
    """UX-026: the moment a scheduled run starts, every /ws/events socket hears
    automation_run_started (the top-right toast). Dead sockets drop silently."""
    from smallink.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from smallink.server.manager import SessionManager

    class ScriptedProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="done", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    monkeypatch.setenv("LINK_STATE_DIR", str(tmp_path / "state"))
    ws = tmp_path / "ws"
    ws.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())
    task = _task(workspace=str(ws), agent="link")
    manager.task_store.save(task)
    manager.task_store._conn.execute(
        "UPDATE scheduled_tasks SET next_run=1.0 WHERE id=?", (task.id,)
    )
    manager.task_store._conn.commit()

    heard: list = []

    async def listener(message):
        heard.append(message)

    async def dead(message):
        raise RuntimeError("socket gone")

    manager.register_event_client(listener)
    manager.register_event_client(dead)
    run = await manager._run_scheduled_task(task, trigger="schedule")

    (event,) = [m for m in heard if m["type"] == "automation_run_started"]
    assert event["data"]["task_id"] == task.id
    assert event["data"]["task_title"] == task.title
    assert event["data"]["session_id"] == run.session_id
    assert event["data"]["trigger"] == "schedule"
    assert dead not in manager._event_clients  # dropped, not fatal


@pytest.mark.asyncio
async def test_scheduled_run_publishes_engine_before_started_event(tmp_path, monkeypatch):
    from smallink.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from smallink.server.manager import SessionManager

    class ScriptedProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="done", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    workspace = tmp_path / "ws"
    workspace.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())
    task = _task(workspace=str(workspace), agent="link")
    manager.task_store.save(task)
    manager.task_store._conn.execute(
        "UPDATE scheduled_tasks SET next_run=1.0 WHERE id=?", (task.id,)
    )
    manager.task_store._conn.commit()
    seen_engine = []

    async def inspect_started(message):
        if message["type"] != "automation_run_started":
            return
        session_id = message["data"]["session_id"]
        seen_engine.append(manager.get_engine(session_id, workspace=str(workspace), agent="link"))

    manager.register_event_client(inspect_started)
    run = await manager._run_scheduled_task(task, trigger="schedule")

    assert run.status == "ok"
    assert seen_engine == [manager._runtimes.engine(run.session_id)]


@pytest.mark.asyncio
async def test_scheduled_engine_build_failure_updates_original_run(tmp_path, monkeypatch):
    from smallink.server.manager import SessionManager

    manager = SessionManager(data_dir=tmp_path / "data")
    task = _task(workspace=str(tmp_path), agent="link")
    manager.task_store.save(task)
    manager.task_store._conn.execute(
        "UPDATE scheduled_tasks SET next_run=1.0 WHERE id=?", (task.id,)
    )
    manager.task_store._conn.commit()

    def fail_build(*args, **kwargs):
        raise RuntimeError("engine build failed")

    monkeypatch.setattr(manager, "_build_task_engine", fail_build)
    run = await manager._run_scheduled_task(task, trigger="schedule")
    stored = manager.task_store.runs(task.id)

    assert run.status == "error"
    assert run.error == "engine build failed"
    assert len(stored) == 1
    assert stored[0].run_id == run.run_id
    assert stored[0].status == "error"


@pytest.mark.asyncio
async def test_scheduled_run_claim_failure_skips_without_counting(tmp_path, monkeypatch):
    from smallink.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from smallink.server.manager import SessionManager

    class ScriptedProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="done", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    workspace = tmp_path / "ws"
    workspace.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())
    task = _task(workspace=str(workspace), agent="link")
    manager.task_store.save(task)
    manager.task_store._conn.execute(
        "UPDATE scheduled_tasks SET next_run=1.0 WHERE id=?", (task.id,)
    )
    manager.task_store._conn.commit()
    original_try_mark = manager.try_mark_running

    def fail_scheduled_claim(session_id, *, engine=None):
        if session_id.startswith("__run__"):
            return False
        return original_try_mark(session_id, engine=engine)

    monkeypatch.setattr(manager, "try_mark_running", fail_scheduled_claim)
    run = await manager._run_scheduled_task(task, trigger="schedule")
    stored = manager.task_store.runs(task.id)
    refreshed = manager.task_store.get(task.id)

    assert run.status == "skipped"
    assert "already active" in (run.error or "")
    assert len(stored) == 1 and stored[0].status == "skipped"
    assert refreshed.run_count == 0
    assert refreshed.last_status is None


@pytest.mark.asyncio
async def test_scheduled_run_saves_before_releasing_execution_slot(tmp_path, monkeypatch):
    from smallink.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from smallink.server.manager import SessionManager

    class ScriptedProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="done", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    workspace = tmp_path / "ws"
    workspace.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())
    task = _task(workspace=str(workspace), agent="link")
    manager.task_store.save(task)
    manager.task_store._conn.execute(
        "UPDATE scheduled_tasks SET next_run=1.0 WHERE id=?", (task.id,)
    )
    manager.task_store._conn.commit()
    order: list[str] = []
    original_save = manager.save
    original_mark_idle = manager.mark_idle

    def tracking_save(session_id, engine):
        order.append("save")
        return original_save(session_id, engine)

    def tracking_mark_idle(session_id):
        order.append("mark_idle")
        return original_mark_idle(session_id)

    monkeypatch.setattr(manager, "save", tracking_save)
    monkeypatch.setattr(manager, "mark_idle", tracking_mark_idle)
    run = await manager._run_scheduled_task(task, trigger="schedule")

    assert run.status == "ok"
    assert order[:2] == ["save", "mark_idle"]


@pytest.mark.asyncio
async def test_scheduled_run_save_failure_is_not_recorded_as_success(tmp_path, monkeypatch):
    from smallink.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from smallink.server.manager import SessionManager

    class ScriptedProvider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="done", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities()

    workspace = tmp_path / "ws"
    workspace.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data", provider=ScriptedProvider())
    task = _task(workspace=str(workspace), agent="link")
    manager.task_store.save(task)
    manager.task_store._conn.execute(
        "UPDATE scheduled_tasks SET next_run=1.0 WHERE id=?", (task.id,)
    )
    manager.task_store._conn.commit()

    def fail_save(*_args, **_kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(manager, "save", fail_save)
    run = await manager._run_scheduled_task(task, trigger="schedule")

    assert run.status == "error"
    assert "could not be saved" in (run.error or "")
    assert manager.task_store.get(task.id).last_status == "error"
    assert manager.is_running(run.session_id) is False


@pytest.mark.asyncio
async def test_cancelled_scheduled_run_is_counted_once_as_interrupted(tmp_path, monkeypatch):
    from smallink.server.manager import SessionManager

    workspace = tmp_path / "ws"
    workspace.mkdir()
    manager = SessionManager(data_dir=tmp_path / "data")
    task = _task(workspace=str(workspace), agent="link")
    manager.task_store.save(task)
    manager.task_store._conn.execute(
        "UPDATE scheduled_tasks SET next_run=1.0 WHERE id=?", (task.id,)
    )
    manager.task_store._conn.commit()
    started = asyncio.Event()

    async def blocked_events(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()
        if False:  # pragma: no cover - keeps this an async generator
            yield None

    monkeypatch.setattr(manager, "tracked_engine_events", blocked_events)
    execution = asyncio.create_task(
        manager._run_scheduled_task(task, trigger="schedule")
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution

    run = manager.task_store.runs(task.id)[0]
    refreshed = manager.task_store.get(task.id)
    assert run.status == "interrupted"
    assert refreshed.run_count == 1
    assert refreshed.last_status == "interrupted"
    assert manager.task_store.recover_incomplete_runs() == 0
    assert manager.task_store.get(task.id).run_count == 1


def test_complete_run_is_idempotent_and_atomic(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "auto.db")
    task = _task()
    store.save(task)
    run = TaskRun(
        task_id=task.id, status="ok", finished_at=time.time(), result_text="done"
    )

    store.complete_run(run)
    store.complete_run(run)
    assert store.get(task.id).run_count == 1

    second = TaskRun(
        task_id=task.id, status="ok", finished_at=time.time(), result_text="second"
    )
    original_save = store.save

    def fail_task_save(updated):
        if updated.run_count == 2:
            raise RuntimeError("disk full")
        return original_save(updated)

    monkeypatch.setattr(store, "save", fail_task_save)
    with pytest.raises(RuntimeError, match="disk full"):
        store.complete_run(second)

    assert store.find_run(second.run_id) is None
    assert store.get(task.id).run_count == 1
