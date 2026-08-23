from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse


def memory_router(manager: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/sensory-records")
    def sensory_records(
        limit: int = 100,
        offset: int = 0,
        source_type: str | None = None,
        governance_status: str | None = None,
        conversation_id: str | None = None,
        project_path: str | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        return manager.sensory_records(
            limit=limit,
            offset=offset,
            source_type=source_type,
            governance_status=governance_status,
            conversation_id=conversation_id,
            project_path=project_path,
            query=query,
        )

    @router.get("/v1/sensory-records/stats")
    def sensory_record_stats() -> dict[str, Any]:
        return manager.sensory_store.stats()

    @router.get("/v1/sensory-records/{record_id}")
    def sensory_record(record_id: str) -> Any:
        record = manager.sensory_record(record_id)
        return record if record is not None else JSONResponse(
            status_code=404,
            content={"error": "sensory record not found"},
        )

    @router.get("/v1/sensory-records/{record_id}/provenance")
    def sensory_provenance(record_id: str) -> Any:
        provenance = manager.sensory_provenance(record_id)
        return provenance if provenance is not None else JSONResponse(
            status_code=404,
            content={"error": "sensory record not found"},
        )

    @router.post("/v1/sensory-records")
    def ingest_sensory_record(body: dict) -> Any:
        try:
            return manager.ingest_sensory_record(body or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/v1/sensory-records")
    def delete_sensory_records(body: dict | None = None) -> Any:
        body = body or {}
        try:
            return manager.delete_sensory_records(
                record_ids=body.get("record_ids"),
                source_type=body.get("source_type"),
                before=body.get("before"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/v1/memory/pipeline/run")
    async def run_memory_pipeline(body: dict | None = None) -> dict[str, Any]:
        body = body or {}
        return await asyncio.to_thread(
            manager.run_memory_pipeline,
            body.get("record_ids"),
            int(body.get("limit", 50)),
            bool(body.get("retry_failed", False)),
            bool(body.get("allow_sensitive_cloud", False)),
        )

    @router.get("/v1/memory/governance/schedule")
    def governance_schedule() -> dict[str, Any]:
        return manager.governance_schedule()

    @router.patch("/v1/memory/governance/schedule")
    def update_governance_schedule(body: dict) -> Any:
        try:
            return manager.set_governance_schedule(body or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/v1/memory")
    def memory(status: str | None = "active") -> dict[str, Any]:
        wanted = None if status in (None, "", "all") else status
        return {"memory": manager.list_memory(status=wanted)}

    @router.get("/v1/memory/candidates")
    def memory_candidates(
        status: str | None = "pending",
        min_confidence: float | None = None,
        max_confidence: float | None = None,
    ) -> dict[str, Any]:
        wanted = None if status in (None, "", "all") else status
        return {"candidates": manager.memory_candidates(
            status=wanted,
            min_confidence=min_confidence,
            max_confidence=max_confidence,
        )}

    @router.post("/v1/memory/candidates/auto-accept")
    async def auto_accept_candidates(body: dict | None = None) -> dict[str, Any]:
        body = body or {}
        threshold = float(body.get("threshold", 0.9))
        return await asyncio.to_thread(
            manager.auto_accept_high_confidence, threshold
        )

    @router.get("/v1/memory/candidates/confidence-summary")
    def confidence_summary() -> dict[str, Any]:
        return manager.memory_confidence_summary()

    @router.get("/v1/memory/governance/tasks")
    def governance_tasks(
        status: str | None = None, limit: int = 100
    ) -> dict[str, Any]:
        wanted = None if status in (None, "", "all") else status
        return {"tasks": manager.governance_tasks(status=wanted, limit=limit)}

    @router.get("/v1/memory/governance/tasks/{task_id}")
    def governance_task(task_id: str) -> Any:
        task = manager.governance_task(task_id)
        return task if task is not None else JSONResponse(
            status_code=404,
            content={"error": "governance task not found"},
        )

    @router.post("/v1/memory/candidates/batch/decision")
    def decide_memory_candidates(body: dict) -> Any:
        try:
            return manager.decide_memory_candidates(body or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.patch("/v1/memory/candidates/batch/type")
    def retype_memory_candidates(body: dict) -> Any:
        try:
            return manager.retype_memory_candidates(body or {})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/v1/memory/candidates/{candidate_id}")
    def memory_candidate(candidate_id: str) -> Any:
        candidate = manager.memory_candidate(candidate_id)
        return candidate if candidate is not None else JSONResponse(
            status_code=404,
            content={"error": "memory candidate not found"},
        )

    @router.post("/v1/memory/candidates/{candidate_id}/decision")
    def decide_memory_candidate(candidate_id: str, body: dict) -> Any:
        try:
            return manager.decide_memory_candidate(candidate_id, body or {})
        except KeyError:
            return JSONResponse(
                status_code=404,
                content={"error": "memory candidate or merge target not found"},
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/v1/memory")
    def add_memory(body: dict) -> Any:
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "error": "governance_required",
                "message": "Formal memories can only be created from a confirmed governance candidate.",
            },
        )

    @router.post("/v1/memory/{memory_id}/archive")
    def archive_memory(memory_id: int) -> Any:
        try:
            return manager.set_memory_status(memory_id, "archived")
        except KeyError:
            return JSONResponse(
                status_code=404, content={"error": "memory not found"}
            )

    @router.post("/v1/memory/{memory_id}/restore")
    def restore_memory(memory_id: int) -> Any:
        try:
            return manager.set_memory_status(memory_id, "active")
        except KeyError:
            return JSONResponse(
                status_code=404, content={"error": "memory not found"}
            )

    @router.get("/v1/memory/usage-history")
    def memory_usage_history(limit: int = 50, memory_id: int | None = None) -> Any:
        return manager.memory_usage_history(limit=limit, memory_id=memory_id)

    return router
