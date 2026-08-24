from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from smallink.server.manager import (
    BROADCAST_CALLBACK_TIMEOUT_SECONDS,
    SessionManager,
)


async def test_broadcast_event_isolates_slow_callback_and_removes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = SessionManager(data_dir=tmp_path / "data")
    monkeypatch.setattr("smallink.server.manager.BROADCAST_CALLBACK_TIMEOUT_SECONDS", 0.05)

    fast_seen = asyncio.Event()
    slow_started = asyncio.Event()
    slow_release = asyncio.Event()
    fast_messages: list[dict] = []

    async def fast_cb(message: dict) -> None:
        fast_messages.append(message)
        fast_seen.set()

    async def slow_cb(message: dict) -> None:
        slow_started.set()
        await slow_release.wait()

    manager.register_event_client(slow_cb)
    manager.register_event_client(fast_cb)

    task = asyncio.create_task(manager.broadcast_event({"type": "tick"}))
    await slow_started.wait()
    await asyncio.wait_for(fast_seen.wait(), timeout=0.2)

    assert fast_messages == [{"type": "tick"}]
    assert slow_cb in manager._event_clients

    await asyncio.wait_for(
        task,
        timeout=BROADCAST_CALLBACK_TIMEOUT_SECONDS + 0.3,
    )
    assert slow_cb not in manager._event_clients
    assert fast_cb in manager._event_clients

    await manager.aclose()


async def test_broadcast_session_isolates_slow_callback_and_removes_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = SessionManager(data_dir=tmp_path / "data")
    monkeypatch.setattr("smallink.server.manager.BROADCAST_CALLBACK_TIMEOUT_SECONDS", 0.05)

    session_id = "session-1"
    fast_seen = asyncio.Event()
    slow_started = asyncio.Event()
    slow_release = asyncio.Event()
    fast_messages: list[dict] = []

    async def fast_cb(message: dict) -> None:
        fast_messages.append(message)
        fast_seen.set()

    async def slow_cb(message: dict) -> None:
        slow_started.set()
        await slow_release.wait()

    manager.register_session_client(session_id, slow_cb)
    manager.register_session_client(session_id, fast_cb)

    task = asyncio.create_task(
        manager.broadcast_session(session_id, {"type": "turn_event"})
    )
    await slow_started.wait()
    await asyncio.wait_for(fast_seen.wait(), timeout=0.2)

    assert fast_messages == [{"type": "turn_event"}]
    assert slow_cb in manager._session_clients[session_id]

    await asyncio.wait_for(
        task,
        timeout=BROADCAST_CALLBACK_TIMEOUT_SECONDS + 0.3,
    )
    session_clients = manager._session_clients.get(session_id, set())
    assert slow_cb not in session_clients
    assert fast_cb in session_clients

    await manager.aclose()
