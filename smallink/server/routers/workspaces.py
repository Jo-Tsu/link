"""Workspaces router — recent, open, trust, pick."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter


def workspaces_router(manager: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/workspaces/recent")
    def recent_workspaces() -> dict[str, Any]:
        return {"workspaces": manager.recent_workspaces()}

    @router.post("/v1/workspaces/open")
    def open_workspace(body: dict) -> dict[str, Any]:
        return manager.open_workspace(
            body.get("path", ""), create=bool(body.get("create"))
        )

    @router.get("/v1/workspaces/trusted")
    def trusted_workspaces() -> dict[str, Any]:
        return {"workspaces": manager.trusted_workspaces()}

    @router.post("/v1/workspaces/trust")
    def set_workspace_trust(body: dict) -> dict[str, Any]:
        return manager.set_workspace_trust(
            str((body or {}).get("path", "")),
            trusted=bool((body or {}).get("trusted", False)),
        )

    @router.post("/v1/workspaces/pick")
    async def pick_workspace() -> dict[str, Any]:
        return await asyncio.to_thread(manager.pick_native_folder)

    return router
