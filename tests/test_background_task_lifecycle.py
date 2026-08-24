from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi import APIRouter

from smallink.server.manager import SessionManager
from smallink.server.routers.connectors import connectors_router
from smallink.server.routers.mcp import mcp_router


def _post_endpoint(router: APIRouter, path: str):
    return next(
        route.endpoint
        for route in router.routes
        if getattr(route, "path", None) == path and "POST" in route.methods
    )


@pytest.mark.parametrize(
    ("router_factory", "path", "method_name", "name"),
    [
        (mcp_router, "/v1/mcp/{name}/connect", "connect_mcp", "granola"),
        (
            connectors_router,
            "/v1/connectors/{name}/mcp-connect",
            "mcp_connect_connector",
            "monday",
        ),
    ],
)
async def test_connect_routes_are_cancelled_and_awaited_on_shutdown(
    tmp_path, monkeypatch, router_factory, path, method_name, name
) -> None:
    manager = SessionManager(data_dir=tmp_path / "data")
    started = asyncio.Event()
    finished = asyncio.Event()

    async def wait_for_connect(_name: str) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()

    monkeypatch.setattr(manager, method_name, wait_for_connect)
    endpoint = _post_endpoint(router_factory(manager), path)

    assert await endpoint(name) == {"ok": True, "started": True}
    await started.wait()
    task = next(iter(manager._background_tasks))

    await asyncio.wait_for(manager.aclose(), timeout=2)

    assert task.cancelled()
    assert finished.is_set()
    assert manager._background_tasks == set()


async def test_aclose_cancels_and_awaits_inflight_autotitle(
    tmp_path, monkeypatch
) -> None:
    manager = SessionManager(data_dir=tmp_path / "data")
    engine = manager.get_engine("session-1", agent="chat")
    engine.messages.append({"role": "user", "content": "plan the launch"})
    manager.save("session-1", engine)
    started = asyncio.Event()
    finished = asyncio.Event()

    async def wait_for_title(_session_id, _engine, _openers) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()

    monkeypatch.setattr(manager, "_generate_autotitle", wait_for_title)
    manager._maybe_autotitle("session-1")
    await started.wait()
    task = next(iter(manager._autotitle_tasks))

    await asyncio.wait_for(manager.aclose(), timeout=2)

    assert task.cancelled()
    assert finished.is_set()
    assert manager._autotitle_tasks == set()
    assert manager._autotitle_inflight == set()

    manager._maybe_autotitle("session-1")
    assert manager._autotitle_tasks == set()


async def test_background_task_exception_is_retrieved_and_logged(
    tmp_path, caplog
) -> None:
    manager = SessionManager(data_dir=tmp_path / "data")
    finished = asyncio.Event()

    async def fail() -> None:
        try:
            raise RuntimeError("connect exploded")
        finally:
            finished.set()

    caplog.set_level(logging.ERROR, logger="smallink.manager")
    task = manager.spawn_background_task(fail())
    await finished.wait()
    while task in manager._background_tasks:
        await asyncio.sleep(0)

    assert task.done()
    assert "background task failed" in caplog.text
    assert "connect exploded" in caplog.text

    await manager.aclose()
