"""Compatibility entry point for the explicit connector tool registry.

Connector implementations live in ``tools_domain``. This module intentionally
keeps the historical factory and injectable ``_request`` name so existing
callers and tests can migrate without changing the public tool surface.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..secrets import SecretStore
from .tool_plugins import build_connector_tool_plugins
from .tool_utils import request as _request


def make_integration_tools(
    secrets: SecretStore,
    *,
    enabled_connectors: Optional[set[str]] = None,
    enabled_tools: Optional[set[str]] = None,
    roots: Optional[list[Any]] = None,
) -> list[Callable[..., Any]]:
    """Build the complete connector tool surface in stable legacy order."""
    return build_connector_tool_plugins(
        secrets,
        roots=roots,
        request_fn=_request,
        enabled_connectors=enabled_connectors,
        enabled_tools=enabled_tools,
    )
