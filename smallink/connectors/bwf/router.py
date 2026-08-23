"""BWF Studio API router — self-contained, mountable on any FastAPI app."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .pipeline import BWFPipeline

import logging

logger = logging.getLogger(__name__)

bwf_router = APIRouter(tags=["bwf"])

_pipeline: Optional[BWFPipeline] = None


def _get_bwf_data_dir() -> str:
    state_dir = os.environ.get("LINK_STATE_DIR") or str(Path.home() / ".config" / "link")
    bwf_dir = os.path.join(state_dir, "apps", "bwf")
    os.makedirs(bwf_dir, exist_ok=True)
    return bwf_dir


def init_bwf(data_dir: Optional[str] = None) -> BWFPipeline:
    """Initialize BWF pipeline. Called once at app startup."""
    global _pipeline
    if data_dir is None:
        data_dir = _get_bwf_data_dir()
    _pipeline = BWFPipeline(data_dir=data_dir)
    logger.info("BWF Studio initialized at %s", data_dir)
    return _pipeline


def get_pipeline() -> BWFPipeline:
    if _pipeline is None:
        raise RuntimeError("BWF not initialized. Call init_bwf() first.")
    return _pipeline


def mount_bwf_on_app(app: FastAPI, data_dir: Optional[str] = None) -> None:
    """Mount BWF router + media files onto an existing FastAPI app."""
    if data_dir is None:
        data_dir = _get_bwf_data_dir()
    init_bwf(data_dir)
    app.include_router(bwf_router, prefix="/v1/apps/bwf")
    os.makedirs(data_dir, exist_ok=True)
    app.mount("/files/bwf", StaticFiles(directory=data_dir), name="bwf_files")
    logger.info("BWF Studio mounted at /v1/apps/bwf")


# ── Request schemas ──

class CreateProjectRequest(BaseModel):
    title: str
    text: str = ""
    series_id: Optional[str] = None
    workflow_mode: str = "r2v"


class UpdateProjectRequest(BaseModel):
    title: Optional[str] = None
    original_text: Optional[str] = None
    starred: Optional[bool] = None


class CreateSeriesRequest(BaseModel):
    title: str
    description: str = ""
    workflow_mode: str = "r2v"
    content_mode: str = "scripted"
    default_generation_mode: str = "r2v"


class CreateVideoTaskRequest(BaseModel):
    frame_id: Optional[str] = None
    image_url: str = ""
    prompt: str = ""
    model: str = "wan2.7-i2v"
    generation_mode: str = "i2v"
    duration: int = 5
    provider_params: Dict[str, Any] = Field(default_factory=dict)


# ── Routes ──

@bwf_router.get("/health")
def bwf_health():
    return {"status": "ok", "app": "bwf"}


@bwf_router.get("/projects")
def list_projects(series_id: Optional[str] = None):
    return get_pipeline().list_projects(series_id=series_id)


@bwf_router.post("/projects")
def create_project(req: CreateProjectRequest):
    project = get_pipeline().create_project(
        title=req.title, text=req.text,
        series_id=req.series_id, workflow_mode=req.workflow_mode,
    )
    return project.model_dump()


@bwf_router.get("/projects/{project_id}")
def get_project(project_id: str):
    project = get_pipeline().get_project(project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    return project.model_dump()


@bwf_router.patch("/projects/{project_id}")
def update_project(project_id: str, req: UpdateProjectRequest):
    updates = req.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(400, "No fields to update")
    project = get_pipeline().update_project(project_id, **updates)
    if project is None:
        raise HTTPException(404, "Project not found")
    return project.model_dump()


@bwf_router.delete("/projects/{project_id}")
def delete_project(project_id: str):
    if not get_pipeline().delete_project(project_id):
        raise HTTPException(404, "Project not found")
    return {"deleted": True}


@bwf_router.get("/series")
def list_series():
    return get_pipeline().list_series()


@bwf_router.post("/series")
def create_series(req: CreateSeriesRequest):
    series = get_pipeline().create_series(
        title=req.title, description=req.description,
        workflow_mode=req.workflow_mode, content_mode=req.content_mode,
        default_generation_mode=req.default_generation_mode,
    )
    return series.model_dump()


@bwf_router.get("/series/{series_id}")
def get_series(series_id: str):
    series = get_pipeline().get_series(series_id)
    if series is None:
        raise HTTPException(404, "Series not found")
    return series.model_dump()


@bwf_router.delete("/series/{series_id}")
def delete_series(series_id: str):
    if not get_pipeline().delete_series(series_id):
        raise HTTPException(404, "Series not found")
    return {"deleted": True}


@bwf_router.get("/series/{series_id}/episodes")
def list_episodes(series_id: str):
    series = get_pipeline().get_series(series_id)
    if series is None:
        raise HTTPException(404, "Series not found")
    return get_pipeline().list_projects(series_id=series_id)


@bwf_router.get("/projects/{project_id}/video-tasks")
def list_video_tasks(project_id: str):
    tasks = get_pipeline().get_video_tasks(project_id)
    return [t.model_dump() for t in tasks]


@bwf_router.post("/projects/{project_id}/video-tasks")
def create_video_task(project_id: str, req: CreateVideoTaskRequest):
    project = get_pipeline().get_project(project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    task = get_pipeline().create_video_task(
        project_id=project_id,
        frame_id=req.frame_id, image_url=req.image_url,
        prompt=req.prompt, model=req.model,
        generation_mode=req.generation_mode, duration=req.duration,
        provider_params=req.provider_params,
    )
    return task.model_dump()


@bwf_router.post("/maintenance/cleanup")
def run_cleanup(max_age_days: int = 7):
    count = get_pipeline().store.cleanup_old_tasks(max_age_seconds=max_age_days * 86400)
    return {"cleaned": count}
