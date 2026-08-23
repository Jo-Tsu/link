"""Skills router — list, create, import, detail, pick."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from ...skills import SkillStoreError


def skills_router(manager: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/skills")
    def skills(workspace: Optional[str] = None) -> dict[str, Any]:
        return manager.list_skills(workspace)

    @router.post("/v1/skills")
    def skill_create(body: dict) -> dict[str, Any]:
        try:
            return manager.create_skill(body or {})
        except SkillStoreError as exc:
            status = 409 if exc.code == "conflict" else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @router.post("/v1/skills/import")
    def skill_import(body: dict) -> dict[str, Any]:
        try:
            return manager.import_skill(body or {})
        except SkillStoreError as exc:
            status = 409 if exc.code == "conflict" else 400
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @router.post("/v1/skills/pick-archive")
    async def skill_pick_archive() -> dict[str, Any]:
        return await asyncio.to_thread(manager.pick_native_skill_archive)

    @router.get("/v1/skills/{skill_id}")
    def skill_detail(skill_id: str, workspace: Optional[str] = None) -> dict[str, Any]:
        detail = manager.skill_detail(skill_id, workspace)
        if detail is None:
            raise HTTPException(status_code=404, detail="unknown skill")
        return detail

    return router
