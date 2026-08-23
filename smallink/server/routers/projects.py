"""Projects router — CRUD, sessions, overview."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse


def projects_router(manager: Any) -> APIRouter:
    router = APIRouter()
    service = manager.app_projects

    @router.get("/v1/projects")
    def list_projects(status: str | None = None) -> dict[str, Any]:
        return {"projects": service.list_projects(status=status)}

    @router.post("/v1/projects")
    def create_project(body: dict) -> dict[str, Any]:
        return service.create_project(body or {})

    @router.get("/v1/projects/{project_id}")
    def get_project(project_id: str) -> Any:
        proj = service.get_project(project_id)
        if proj is None:
            return JSONResponse(status_code=404, content={"error": "project not found"})
        return proj

    @router.patch("/v1/projects/{project_id}")
    def update_project(project_id: str, body: dict) -> dict[str, Any]:
        return service.update_project(project_id, body or {})

    @router.delete("/v1/projects/{project_id}")
    def delete_project(project_id: str) -> dict[str, Any]:
        return service.delete_project(project_id)

    @router.get("/v1/projects/{project_id}/sessions")
    def project_sessions(project_id: str) -> dict[str, Any]:
        return {"sessions": service.project_sessions(project_id)}

    @router.get("/v1/projects/{project_id}/overview")
    def project_overview(project_id: str) -> Any:
        overview = service.project_overview(project_id)
        if overview is None:
            return JSONResponse(status_code=404, content={"error": "project not found"})
        return overview

    return router
