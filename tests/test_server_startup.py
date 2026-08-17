"""The local API must stay responsive while OS credential stores are slow."""

from __future__ import annotations

import asyncio
import time

import smallink.server.manager as manager_module
from smallink.server import SessionManager


async def test_gateway_secret_loading_does_not_block_event_loop(tmp_path, monkeypatch):
    manager = SessionManager(data_dir=tmp_path / "data")

    def slow_settings(_secrets):
        time.sleep(0.2)
        return {}

    monkeypatch.setattr(manager_module, "load_settings", slow_settings)
    gateway = asyncio.create_task(manager._build_and_start_gateway())

    # This timer can fire only when credential loading is outside the event loop.
    await asyncio.wait_for(asyncio.sleep(0.02), timeout=0.08)
    assert await gateway == []
    await manager.stop_gateway()
