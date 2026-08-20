from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse


def knowledge_router(manager: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/knowledge")
    def list_knowledge(
        project_id: str | None = None, status: str | None = "active"
    ) -> Any:
        wanted = None if status in (None, "", "all") else status
        try:
            return {
                "items": manager.knowledge_items(
                    project_id=project_id, status=wanted
                )
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @router.get("/v1/knowledge/search")
    def search_knowledge(
        q: str, project_id: str | None = None, limit: int = 20
    ) -> Any:
        try:
            return manager.search_knowledge(q, project_id=project_id, limit=limit)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @router.post("/v1/knowledge/index-source")
    def index_source(body: dict) -> Any:
        payload = body or {}
        record_id = str(payload.get("record_id") or "").strip()
        if not record_id:
            raise HTTPException(status_code=400, detail="record_id is required")
        try:
            return manager.index_knowledge_source(
                record_id,
                project_id=payload.get("project_id"),
                title=str(payload.get("title") or ""),
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail="source record or project not found"
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/v1/knowledge/projects/{project_id}/index")
    def index_project(project_id: str) -> Any:
        try:
            return manager.index_project_knowledge(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="project not found") from exc

    @router.get("/v1/knowledge/{item_id}")
    def get_knowledge(item_id: str) -> Any:
        item = manager.knowledge_item(item_id)
        return item if item is not None else JSONResponse(
            status_code=404, content={"error": "knowledge item not found"}
        )

    @router.patch("/v1/knowledge/{item_id}/archive")
    def archive_knowledge(item_id: str, body: dict) -> Any:
        try:
            return manager.archive_knowledge_item(
                item_id, bool((body or {}).get("archived", True))
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="knowledge item not found") from exc

    return router
