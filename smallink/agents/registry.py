"""Agent registry — resolves a persona id to its runtime Agent.

Delegates to the persona registry (``link.personas``) so built-in surfaces and
markdown/third-party personas resolve through one path. Imports of the persona registry are
lazy to avoid an import cycle (personas → agents builders).
"""

from __future__ import annotations

from .base import Agent


def get_agent(name: str) -> Agent:
    name = name or "code"
    from ..personas.registry import get_registry

    return get_registry().agent(name)


def list_agents() -> list[dict]:
    # Session surfaces shown in the new-session picker (enabled + surfaced personas).
    from ..personas.registry import get_registry

    return get_registry().sidebar()
