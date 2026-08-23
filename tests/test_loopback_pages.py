"""Loopback helper extraction guard: routers import from loopback_pages, not app."""

from __future__ import annotations

import inspect


def test_loopback_routers_do_not_import_app_module_for_helpers():
    from smallink.server.routers.cloud import cloud_router
    from smallink.server.routers.mcp import mcp_router

    assert "..app" not in inspect.getsource(cloud_router)
    assert "..app" not in inspect.getsource(mcp_router)
