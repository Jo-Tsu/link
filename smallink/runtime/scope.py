"""Owned resources for one live agent session.

DeepSeek Harness ties every registration and resource to a Fiber. Smallink does
not need a general plugin framework, but it does need the same ownership rule:
everything created for one live session is released together and exactly once.
"""

from __future__ import annotations

from contextlib import ExitStack
from typing import TYPE_CHECKING, Any, Callable, Iterator

from ..lifecycle import LifecycleTracker

if TYPE_CHECKING:
    from ..engine import TurnEngine


class RuntimeScope:
    """One unpublished/published session runtime with deterministic teardown."""

    def __init__(
        self,
        session_id: str,
        engine: TurnEngine | None = None,
        *,
        lifecycle: LifecycleTracker | None = None,
    ) -> None:
        self.session_id = session_id
        self.engine = engine
        self.lifecycle = lifecycle or LifecycleTracker(session_id)
        self._effects = ExitStack()
        self._closed = False
        self._claimed = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def claimed(self) -> bool:
        return self._claimed

    def bind(self, engine: TurnEngine) -> None:
        """Attach the fully assembled engine before publishing the runtime."""
        if self._closed:
            raise RuntimeError(f"runtime scope {self.session_id!r} is closed")
        if self.engine is not None and self.engine is not engine:
            raise RuntimeError(f"runtime scope {self.session_id!r} already has an engine")
        self.engine = engine

    def claim(self) -> bool:
        """Atomically claim the session's single execution slot."""
        if self._closed or self._claimed:
            return False
        self._claimed = True
        return True

    def release(self) -> None:
        """Release execution and finish its live lifecycle projection."""
        self._claimed = False
        self.lifecycle.finish({"reason": "run_released"})

    def add_effect(self, disposer: Callable[[], Any]) -> Callable[[], Any]:
        """Own a reversible registration/resource and return its disposer."""
        if self._closed:
            raise RuntimeError(f"runtime scope {self.session_id!r} is closed")
        self._effects.callback(disposer)
        return disposer

    def close(self) -> None:
        """Interrupt the engine and unwind owned effects once, in reverse order."""
        if self._closed:
            return
        self._closed = True
        if self.engine is not None:
            self.engine.request_interrupt()
        self._effects.close()
        self.lifecycle.finish({"reason": "scope_closed"})
        self._claimed = False


class RuntimeRegistry:
    """Authoritative inventory of live per-session runtimes."""

    def __init__(self) -> None:
        self._scopes: dict[str, RuntimeScope] = {}

    def ensure(self, session_id: str) -> RuntimeScope:
        scope = self._scopes.get(session_id)
        if scope is None:
            scope = RuntimeScope(session_id)
            self._scopes[session_id] = scope
        return scope

    def prepare(self, session_id: str) -> RuntimeScope:
        """Create an unpublished scope for atomic runtime assembly."""
        existing = self._scopes.get(session_id)
        if existing is not None:
            raise RuntimeError(f"runtime {session_id!r} is already published")
        return RuntimeScope(session_id)

    def publish(
        self,
        session_id: str,
        engine: TurnEngine,
        *,
        scope: RuntimeScope | None = None,
    ) -> RuntimeScope:
        """Atomically expose a completely assembled session runtime."""
        existing = self._scopes.get(session_id)
        if existing is not None and existing.engine is engine:
            return existing
        if existing is not None and existing.engine is not None:
            raise RuntimeError(f"runtime {session_id!r} is already published")
        scope = scope or existing or RuntimeScope(session_id)
        if scope.session_id != session_id:
            raise ValueError("runtime scope/session id mismatch")
        if existing is not None and existing is not scope:
            raise RuntimeError(f"runtime {session_id!r} is already published")
        scope.bind(engine)
        self._scopes[session_id] = scope
        return scope

    def scope(self, session_id: str) -> RuntimeScope | None:
        return self._scopes.get(session_id)

    def engine(self, session_id: str) -> TurnEngine | None:
        scope = self.scope(session_id)
        return scope.engine if scope is not None else None

    def engines(self) -> Iterator[TurnEngine]:
        for scope in self._scopes.values():
            if scope.engine is not None:
                yield scope.engine

    def engine_items(self) -> Iterator[tuple[str, TurnEngine]]:
        for session_id, scope in self._scopes.items():
            if scope.engine is not None:
                yield session_id, scope.engine

    def pop(self, session_id: str) -> RuntimeScope | None:
        return self._scopes.pop(session_id, None)

    def discard(self, session_id: str) -> RuntimeScope | None:
        """Remove and close one runtime, returning the removed scope."""
        scope = self.pop(session_id)
        if scope is not None:
            scope.close()
        return scope

    def close_all(self) -> None:
        for scope in list(self._scopes.values()):
            scope.close()
        self._scopes.clear()
