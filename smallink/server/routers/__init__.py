"""FastAPI route modules for the Smallink control plane."""

from .apps import apps_router
from .automations import automations_router
from .cloud import cloud_router
from .connectors import connectors_router
from .knowledge import knowledge_router
from .mcp import mcp_router
from .memory import memory_router
from .personas import personas_router
from .projects import projects_router
from .prompts import prompts_router
from .sessions import sessions_router
from .settings import settings_router
from .skills import skills_router
from .workspaces import workspaces_router

__all__ = [
    "apps_router",
    "automations_router",
    "cloud_router",
    "connectors_router",
    "knowledge_router",
    "mcp_router",
    "memory_router",
    "personas_router",
    "projects_router",
    "prompts_router",
    "sessions_router",
    "settings_router",
    "skills_router",
    "workspaces_router",
]
