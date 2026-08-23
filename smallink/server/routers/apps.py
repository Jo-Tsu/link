"""Apps router — application center CRUD + capabilities."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException


def apps_router(manager: Any) -> APIRouter:
    router = APIRouter()
    service = manager.app_projects

    @router.get("/v1/apps")
    def list_apps() -> dict[str, Any]:
        return {"apps": service.list_apps()}

    @router.get("/v1/apps/{app_id}")
    def get_app(app_id: str) -> Any:
        try:
            return service.app_descriptor(app_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="application not found") from exc

    @router.post("/v1/apps/{app_id}/enable")
    def enable_app(app_id: str) -> Any:
        try:
            return service.enable_app(app_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="application not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/v1/apps/{app_id}/check")
    def check_app(app_id: str) -> Any:
        try:
            return service.check_app(app_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="application not found") from exc

    @router.post("/v1/apps/{app_id}/disable")
    def disable_app(app_id: str) -> Any:
        try:
            return service.disable_app(app_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="application not found") from exc

    @router.get("/v1/apps/{app_id}/assets")
    def app_assets(
        app_id: str,
        query: str = "",
        asset_type: str = "all",
        limit: int = 60,
        session_id: str | None = None,
    ) -> Any:
        try:
            return service.app_assets(
                app_id,
                query=query,
                asset_type=asset_type,
                limit=limit,
                session_id=session_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="application not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/v1/apps/{app_id}/pick-file")
    async def pick_app_file(app_id: str) -> Any:
        try:
            return await asyncio.to_thread(manager.pick_native_app_file, app_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="application not found") from exc

    @router.post("/v1/apps/{app_id}/capabilities/{capability}")
    def invoke_app_capability(app_id: str, capability: str, body: dict) -> Any:
        payload = body or {}
        try:
            return service.invoke_app_capability(
                app_id,
                capability,
                payload.get("arguments") if isinstance(payload.get("arguments"), dict) else payload,
                session_id=payload.get("session_id"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="application not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/v1/apps/{app_id}/activity")
    def app_activity(app_id: str, limit: int = 50) -> Any:
        try:
            return {"activity": service.app_activity(app_id, limit=limit)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="application not found") from exc

    return router
