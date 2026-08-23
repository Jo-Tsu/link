"""BWF Pipeline — stateless, SQLite-backed video production pipeline."""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from .models import Project, Series, VideoTask
from .store import BWFStore

import logging

logger = logging.getLogger(__name__)


class BWFPipeline:
    """Stateless pipeline — every method reads/writes via self.store."""

    def __init__(self, data_dir: str, *, media_concurrency: int = 2, video_concurrency: int = 2):
        self.data_dir = data_dir
        self.store = BWFStore(os.path.join(data_dir, "bwf.db"))

        os.makedirs(os.path.join(data_dir, "uploads"), exist_ok=True)
        os.makedirs(os.path.join(data_dir, "video"), exist_ok=True)
        os.makedirs(os.path.join(data_dir, "assets"), exist_ok=True)
        os.makedirs(os.path.join(data_dir, "audio"), exist_ok=True)

        self._media_semaphore = threading.BoundedSemaphore(media_concurrency)
        self._video_semaphore = threading.BoundedSemaphore(video_concurrency)

        orphans = self.store.recover_orphan_tasks()
        if orphans:
            logger.warning("Recovered %d orphan video tasks on startup.", orphans)

    # ── Project CRUD ──

    def create_project(
        self, title: str, text: str = "", *, series_id: Optional[str] = None, workflow_mode: str = "r2v"
    ) -> Project:
        now = time.time()
        project = Project(
            id=uuid.uuid4().hex,
            title=title,
            original_text=text,
            series_id=series_id,
            workflow_mode=workflow_mode,
            created_at=now,
            updated_at=now,
        )
        self.store.save_project(project.id, project.model_dump())
        if series_id:
            self._append_episode(series_id, project.id)
        return project

    def get_project(self, project_id: str) -> Optional[Project]:
        data = self.store.load_project(project_id)
        return Project(**data) if data else None

    def update_project(self, project_id: str, **updates: Any) -> Optional[Project]:
        data = self.store.load_project(project_id)
        if data is None:
            return None
        data.update(updates)
        data["updated_at"] = time.time()
        self.store.save_project(project_id, data)
        return Project(**data)

    def delete_project(self, project_id: str) -> bool:
        project = self.get_project(project_id)
        if project is None:
            return False
        if project.series_id:
            self._remove_episode(project.series_id, project_id)
        self.store.delete_project(project_id)
        return True

    def list_projects(self, series_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.store.list_projects(series_id=series_id)

    # ── Series CRUD ──

    def create_series(
        self, title: str, *, description: str = "", workflow_mode: str = "r2v",
        content_mode: str = "scripted", default_generation_mode: str = "r2v",
    ) -> Series:
        now = time.time()
        series = Series(
            id=uuid.uuid4().hex, title=title, description=description,
            workflow_mode=workflow_mode, content_mode=content_mode,
            default_generation_mode=default_generation_mode,
            created_at=now, updated_at=now,
        )
        self.store.save_series(series.id, series.model_dump())
        return series

    def get_series(self, series_id: str) -> Optional[Series]:
        data = self.store.load_series(series_id)
        return Series(**data) if data else None

    def delete_series(self, series_id: str) -> bool:
        if self.store.load_series(series_id) is None:
            return False
        self.store.delete_series(series_id)
        return True

    def list_series(self) -> List[Dict[str, Any]]:
        all_s = self.store.load_all_series()
        return [{"id": sid, "title": s.get("title", ""), "episode_count": len(s.get("episode_ids", []))} for sid, s in all_s.items()]

    def _append_episode(self, series_id: str, project_id: str) -> None:
        data = self.store.load_series(series_id)
        if data is None:
            return
        ids = data.get("episode_ids", [])
        if project_id not in ids:
            ids.append(project_id)
            data["episode_ids"] = ids
            data["updated_at"] = time.time()
            self.store.save_series(series_id, data)

    def _remove_episode(self, series_id: str, project_id: str) -> None:
        data = self.store.load_series(series_id)
        if data is None:
            return
        ids = data.get("episode_ids", [])
        if project_id in ids:
            ids.remove(project_id)
            data["episode_ids"] = ids
            data["updated_at"] = time.time()
            self.store.save_series(series_id, data)

    # ── Video Tasks ──

    def create_video_task(self, project_id: str, **kwargs: Any) -> VideoTask:
        task = VideoTask(id=uuid.uuid4().hex, project_id=project_id, **kwargs)
        self.store.save_video_task(task.id, project_id, task.model_dump())
        return task

    def get_video_tasks(self, project_id: str) -> List[VideoTask]:
        return [VideoTask(**r) for r in self.store.get_video_tasks(project_id)]

    def update_video_task(self, task_id: str, **updates: Any) -> None:
        status = updates.pop("status", "pending")
        self.store.update_video_task_status(task_id, status, **updates)

    # ── Concurrency ──

    def acquire_media_slot(self) -> bool:
        return self._media_semaphore.acquire(blocking=False)

    def release_media_slot(self) -> None:
        self._media_semaphore.release()

    def acquire_video_slot(self) -> bool:
        return self._video_semaphore.acquire(blocking=False)

    def release_video_slot(self) -> None:
        self._video_semaphore.release()

    def close(self) -> None:
        self.store.close()
