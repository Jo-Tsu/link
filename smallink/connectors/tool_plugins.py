"""Explicit connector tool-plugin composition.

This is intentionally a small trusted built-in registry: no filesystem scan,
dynamic import, or configuration language. Each connector declares a stable id
and owns one tool factory; the historical entry point is now only an adapter.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..secrets import SecretStore
from .browser_automation import make_browser_automation_tools
from .email_tools import make_email_tools
from .tool_defs import connector_for_tool
from .tools_domain import make_github_tools, make_minem_tools
from .tools_domain.registry import MIGRATED_TOOL_FACTORIES

ToolFactory = Callable[..., list[Callable[..., Any]]]


def _browser_automation_factory(
    _secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Optional[Callable[..., dict[str, Any]]] = None,
) -> list[Callable[..., Any]]:
    del roots, request_fn
    return make_browser_automation_tools()


def _email_factory(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Optional[Callable[..., dict[str, Any]]] = None,
) -> list[Callable[..., Any]]:
    del request_fn
    return make_email_tools(secrets, roots=roots)


def _minem_factory(
    _secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Optional[Callable[..., dict[str, Any]]] = None,
) -> list[Callable[..., Any]]:
    del roots, request_fn
    return make_minem_tools()


def _github_factory(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Optional[Callable[..., dict[str, Any]]] = None,
) -> list[Callable[..., Any]]:
    if request_fn is None:
        return make_github_tools(secrets, roots=roots)
    return make_github_tools(secrets, roots=roots, request_fn=request_fn)


BUILTIN_TOOL_FACTORIES: tuple[tuple[str, ToolFactory], ...] = (
    ("browser_automation", _browser_automation_factory),
    ("email", _email_factory),
    ("minem", _minem_factory),
    ("github", _github_factory),
    *MIGRATED_TOOL_FACTORIES,
)


def build_connector_tool_plugins(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Optional[Callable[..., dict[str, Any]]] = None,
    enabled_connectors: Optional[set[str]] = None,
    enabled_tools: Optional[set[str]] = None,
) -> list[Callable[..., Any]]:
    """Build every connector tool contribution in deterministic order."""
    tools: list[Callable[..., Any]] = []
    seen_plugins: set[str] = set()
    seen_tools: set[str] = set()
    for connector_id, factory in BUILTIN_TOOL_FACTORIES:
        if connector_id in seen_plugins:
            raise ValueError(f"duplicate connector tool plugin: {connector_id}")
        seen_plugins.add(connector_id)
        kwargs = {"roots": roots}
        if request_fn is not None:
            kwargs["request_fn"] = request_fn
        for tool in factory(secrets, **kwargs):
            name = tool.__name__
            if name in seen_tools:
                raise ValueError(f"duplicate connector tool: {name}")
            seen_tools.add(name)
            tools.append(tool)

    if enabled_connectors is not None:
        tools = [
            tool
            for tool in tools
            if connector_for_tool(tool.__name__) in enabled_connectors
        ]
    if enabled_tools is not None:
        tools = [tool for tool in tools if tool.__name__ in enabled_tools]
    return tools
