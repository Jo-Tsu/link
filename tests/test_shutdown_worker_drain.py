from __future__ import annotations

import asyncio
import threading
import time

from smallink.engine import ApprovalOutcome, TurnEngine
from smallink.permissions import PermissionEngine
from smallink.providers import AssistantTurn, ModelCapabilities, ProviderClient, StreamChunk, ToolCall
from smallink.runtime.scope import RuntimeScope
from smallink.server.manager import SessionManager
from smallink.tools import ToolRegistry


class BlockingStreamProvider(ProviderClient):
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()

    def complete(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def capabilities(self, model):
        return ModelCapabilities()

    def stream(self, *, model, messages, tools=None, **settings):
        self.started.set()
        try:
            self.release.wait(timeout=5)
            yield StreamChunk(text_delta="late ")
        finally:
            self.finished.set()


class BlockingToolProvider(ProviderClient):
    def __init__(self):
        self.calls = 0

    def complete(self, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def stream(self, **kwargs):
        self.calls += 1
        yield StreamChunk(
            turn=AssistantTurn(
                tool_calls=[ToolCall(id="call_1", name="blocking_tool", arguments={})],
                finish_reason="tool_calls",
            )
        )

    def capabilities(self, model):
        return ModelCapabilities()


async def test_shutdown_waits_for_blocked_provider_thread_before_closing_stores(
    tmp_path, monkeypatch
):
    provider = BlockingStreamProvider()
    manager = SessionManager(workspace=tmp_path, provider=provider)
    engine = manager.get_engine("blocked-provider", agent="chat")
    assert engine is not None

    runtime_closed = threading.Event()
    original_runtime_close = manager.runtime_store.close

    def close_runtime_store():
        assert provider.finished.is_set(), "runtime store closed before provider worker ended"
        original_runtime_close()
        runtime_closed.set()

    monkeypatch.setattr(manager.runtime_store, "close", close_runtime_store)

    async def run_turn():
        return [event async for event in engine.run("hello")]

    turn_task = asyncio.create_task(run_turn())
    assert await asyncio.to_thread(provider.started.wait, 2)
    shutdown = asyncio.create_task(manager.aclose())
    assert not runtime_closed.is_set()
    assert not shutdown.done()

    provider.release.set()
    await asyncio.wait_for(shutdown, timeout=2)
    await asyncio.wait_for(turn_task, timeout=2)
    assert provider.finished.is_set()
    assert runtime_closed.is_set()


async def test_shutdown_waits_for_blocked_sync_tool_thread_before_closing_stores(
    tmp_path, monkeypatch
):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocking_tool():
        started.set()
        try:
            release.wait(timeout=5)
            return {"ok": True}
        finally:
            finished.set()

    provider = BlockingToolProvider()
    manager = SessionManager(workspace=tmp_path, provider=provider)
    registry = ToolRegistry()
    registry.register(blocking_tool)

    async def approve_once(_req):
        return ApprovalOutcome.ONCE

    engine = TurnEngine(
        provider=provider,
        registry=registry,
        permissions=PermissionEngine(workspace_root=tmp_path),
        model="gpt-5.5",
        approver=approve_once,
    )
    manager._runtimes.publish("blocked-tool", engine, scope=RuntimeScope("blocked-tool"))

    runtime_closed = threading.Event()
    original_runtime_close = manager.runtime_store.close

    def close_runtime_store():
        assert finished.is_set(), "runtime store closed before tool worker ended"
        original_runtime_close()
        runtime_closed.set()

    monkeypatch.setattr(manager.runtime_store, "close", close_runtime_store)

    async def run_turn():
        return [event async for event in engine.run("hello")]

    turn_task = asyncio.create_task(run_turn())
    assert await asyncio.to_thread(started.wait, 2)
    shutdown = asyncio.create_task(manager.aclose())
    assert not runtime_closed.is_set()
    assert not shutdown.done()

    release.set()
    await asyncio.wait_for(shutdown, timeout=2)
    events = await asyncio.wait_for(turn_task, timeout=2)
    assert any(event.type.value == "tool_finished" for event in events)
    assert finished.is_set()
    assert runtime_closed.is_set()


async def test_shutdown_timeout_returns_without_closing_runtime_data_stores(
    tmp_path, monkeypatch, caplog
):
    provider = BlockingStreamProvider()
    manager = SessionManager(workspace=tmp_path, provider=provider)
    engine = manager.get_engine("blocked-timeout", agent="chat")
    assert engine is not None

    runtime_closed = threading.Event()
    session_closed = threading.Event()
    audit_closed = threading.Event()

    monkeypatch.setattr(
        manager.runtime_store,
        "close",
        lambda: runtime_closed.set(),
    )
    monkeypatch.setattr(
        manager.session_store,
        "close",
        lambda: session_closed.set(),
    )
    monkeypatch.setattr(
        manager.audit_store,
        "close",
        lambda: audit_closed.set(),
    )
    monkeypatch.setattr(
        "smallink.server.manager.BINDING_WORKER_DRAIN_TIMEOUT_SECONDS",
        0.05,
    )

    async def run_turn():
        return [event async for event in engine.run("hello")]

    turn_task = asyncio.create_task(run_turn())
    assert await asyncio.to_thread(provider.started.wait, 2)
    started_at = time.monotonic()
    await manager.aclose()
    assert time.monotonic() - started_at < 0.5

    assert not runtime_closed.is_set()
    assert not session_closed.is_set()
    assert not audit_closed.is_set()
    assert (
        "leaving runtime/data stores open because blocking workers did not drain"
        in caplog.text
    )

    provider.release.set()
    await asyncio.wait_for(turn_task, timeout=2)


def test_shutdown_gate_rejects_new_turn_claims(tmp_path):
    manager = SessionManager(workspace=tmp_path, provider=BlockingStreamProvider())
    engine = manager.get_engine("late-turn", agent="chat")
    assert engine is not None

    manager.begin_shutdown()

    assert manager.try_mark_running("late-turn", engine=engine) is False
    assert manager.is_running("late-turn") is False
