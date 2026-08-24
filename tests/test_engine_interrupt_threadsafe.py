from __future__ import annotations

import asyncio
import threading
import time

from smallink.engine import TurnEngine
from smallink.events import EventType
from smallink.permissions import PermissionEngine
from smallink.providers import ModelCapabilities, ProviderClient, StreamChunk
from smallink.tools import ToolRegistry


class BlockingProvider(ProviderClient):
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def complete(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def capabilities(self, model):
        return ModelCapabilities()

    def stream(self, *, model, messages, tools=None, **settings):
        self.started.set()
        while not self.release.wait(timeout=0.01):
            time.sleep(0.01)
            yield StreamChunk(text_delta="tick ")


class CountingProvider(ProviderClient):
    def __init__(self):
        self.calls = 0

    def complete(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def capabilities(self, model):
        return ModelCapabilities()

    def stream(self, *, model, messages, tools=None, **settings):
        self.calls += 1
        yield StreamChunk(text_delta="should-not-run ")


def test_request_interrupt_is_threadsafe_under_asyncio_debug(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONASYNCIODEBUG", "1")
    provider = BlockingProvider()
    hooks_fired: list[str] = []
    engine = TurnEngine(
        provider=provider,
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
        interrupt_hooks=[lambda: hooks_fired.append("fired")],
    )

    async def scenario():
        events = []
        interrupter_error: list[BaseException] = []

        def interrupt_from_worker():
            try:
                assert provider.started.wait(timeout=5)
                time.sleep(0.02)
                engine.request_interrupt()
            except BaseException as exc:  # thread target: surface any failure explicitly
                interrupter_error.append(exc)
            finally:
                provider.release.set()

        worker = threading.Thread(target=interrupt_from_worker)
        worker.start()
        try:
            async for event in engine.run("hello"):
                events.append(event)
        finally:
            worker.join(timeout=5)
        assert interrupter_error == []
        return events

    events = asyncio.run(scenario(), debug=True)
    assert events[-1].type == EventType.INTERRUPTED
    assert hooks_fired == ["fired"]
    tool_messages = [m for m in engine.messages if m.get("role") == "tool"]
    assert tool_messages == []


def test_request_interrupt_after_claim_before_run_starts_is_not_lost_under_asyncio_debug(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PYTHONASYNCIODEBUG", "1")
    provider = CountingProvider()
    hooks_fired: list[str] = []
    engine = TurnEngine(
        provider=provider,
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
        interrupt_hooks=[lambda: hooks_fired.append("fired")],
    )

    async def scenario():
        engine.prepare_turn()
        errors: list[BaseException] = []

        def interrupt_from_worker():
            try:
                engine.request_interrupt()
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=interrupt_from_worker)
        worker.start()
        worker.join(timeout=5)
        await asyncio.sleep(0)
        assert errors == []
        return [event async for event in engine.run("hello")]

    events = asyncio.run(scenario(), debug=True)
    assert events[0].type == EventType.TURN_START
    assert events[-1].type == EventType.INTERRUPTED
    assert provider.calls == 0
    assert hooks_fired == ["fired"]
    assert engine.messages[-1]["role"] == "notice"
    assert engine.messages[-1]["kind"] == "interrupted"


def test_cancelling_interruptible_reaps_its_child_tasks(tmp_path):
    engine = TurnEngine(
        provider=CountingProvider(),
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
    )

    async def scenario():
        blocker = asyncio.Event()
        wrapper = asyncio.create_task(
            engine._interruptible(blocker.wait(), interrupted=None)
        )
        await asyncio.sleep(0)
        wrapper.cancel()
        try:
            await wrapper
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0)
        leftovers = [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task() and not task.done()
        ]
        assert leftovers == []

    asyncio.run(scenario(), debug=True)


def test_wait_for_workers_keeps_shutdown_dependencies_alive(tmp_path):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    class BlockingToolProvider(CountingProvider):
        pass

    def blocking_tool():
        started.set()
        release.wait(timeout=5)
        finished.set()
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(blocking_tool)
    engine = TurnEngine(
        provider=BlockingToolProvider(),
        registry=registry,
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
    )

    async def scenario():
        worker = asyncio.create_task(
            asyncio.to_thread(engine._execute_sync, type("Call", (), {"name": "blocking_tool", "arguments": {}})())
        )
        engine._worker_futures.add(worker)
        worker.add_done_callback(engine._worker_futures.discard)
        await asyncio.to_thread(started.wait, 2)
        drain = asyncio.create_task(engine.wait_for_workers())
        await asyncio.sleep(0)
        assert not drain.done()
        release.set()
        await asyncio.wait_for(drain, timeout=2)
        assert finished.is_set()

    asyncio.run(scenario(), debug=True)


def test_request_interrupt_falls_back_when_owner_loop_is_closed(tmp_path):
    provider = CountingProvider()
    hooks_fired: list[str] = []
    engine = TurnEngine(
        provider=provider,
        registry=ToolRegistry(),
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
        interrupt_hooks=[lambda: hooks_fired.append("fired")],
    )

    loop = asyncio.new_event_loop()
    try:
        engine._owner_loop = loop
    finally:
        loop.close()

    engine.request_interrupt()

    assert engine._cancel.is_set()
    assert hooks_fired == ["fired"]
