"""Capability seam protocols — typed interfaces for pluggable subsystems.

Each protocol defines the minimal surface that TurnEngine / build_engine requires.
Implementations live in their own modules (memory/, providers/, tools/, permissions.py).
Existing classes already satisfy these protocols structurally — no changes needed.

The CapabilityContainer is a typed bag passed to build_engine, NOT a service locator.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Model completion interface consumed by the engine."""

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **settings: Any,
    ) -> Any: ...

    def capabilities(self, model: str) -> Any: ...

    def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **settings: Any,
    ) -> Any: ...


@runtime_checkable
class ToolProvider(Protocol):
    """Tool schema + execution registry consumed by the engine."""

    def names(self) -> list[str]: ...

    def get(self, name: str) -> Any: ...

    def schemas(self) -> list[dict[str, Any]]: ...

    def execute(self, name: str, arguments: Optional[dict[str, Any]] = None) -> Any: ...


@runtime_checkable
class MemoryProvider(Protocol):
    """Read/write interface for the memory subsystem."""

    def add(
        self,
        content: str,
        *,
        scope: Any,
        key: Optional[str] = None,
        workspace: Optional[str] = None,
        session_id: Optional[str] = None,
        status: str = "active",
        source_record_id: Optional[str] = None,
    ) -> Any: ...

    def get(self, item_id: int) -> Any: ...

    def list(
        self,
        *,
        scope: Any = None,
        workspace: Optional[str] = None,
        session_id: Optional[str] = None,
        status: str = "active",
    ) -> list: ...


@runtime_checkable
class PermissionProvider(Protocol):
    """Tool-call permission evaluation interface."""

    def evaluate(
        self, tool_name: str, arguments: dict[str, Any], metadata: Any = None
    ) -> Any: ...

    @property
    def mode(self) -> Any: ...

    def allow_tool_for_session(self, tool_name: str) -> None: ...

    def allow_command_for_session(self, command: str) -> None: ...


class CapabilityContainer:
    """Resolved capability implementations for one session's engine.

    The manager builds this per-session and passes it to build_engine.
    Existing code can ignore it and keep using keyword args; new code pulls
    from the container.
    """

    __slots__ = ("provider", "tools", "permissions", "memory")

    def __init__(
        self,
        *,
        provider: LLMProvider,
        tools: ToolProvider,
        permissions: PermissionProvider,
        memory: Optional[MemoryProvider] = None,
    ) -> None:
        self.provider = provider
        self.tools = tools
        self.permissions = permissions
        self.memory = memory
