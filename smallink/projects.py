"""Project record — a named workspace scope that groups sessions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ProjectRecord:
    project_id: str
    name: str
    workspace_path: str
    icon: str = "\U0001f4c1"
    description: str = ""
    status: str = "active"
    default_agent: Optional[str] = None
    default_model: Optional[str] = None
    pinned: bool = False
    sort_order: int = 0
    project_type: str = "folder"
    owner_app_id: Optional[str] = None
    system_key: Optional[str] = None
    disabled_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
