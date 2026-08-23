"""Connector tool domain modules — each file owns one connector's tools.

This package replaces the monolithic make_integration_tools() with composable,
per-connector factories. Each module exports a `make_<name>_tools(...)` function
that returns a list of callables ready for ToolRegistry.

The parent integration_tools.py delegates to these modules and handles the
final filtering by enabled_connectors/enabled_tools.
"""

from .github import make_github_tools
from .minem import make_minem_tools

__all__ = [
    "make_github_tools",
    "make_minem_tools",
]
