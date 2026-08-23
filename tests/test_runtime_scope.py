from __future__ import annotations

import pytest

from smallink.lifecycle import AgentPhase
from smallink.runtime import RuntimeRegistry, RuntimeScope


class StubEngine:
    def __init__(self) -> None:
        self.interrupts = 0
        self.executor = None

    def request_interrupt(self) -> None:
        self.interrupts += 1


def test_scope_unwinds_effects_in_reverse_order_once() -> None:
    engine = StubEngine()
    scope = RuntimeScope("session-1", engine)  # type: ignore[arg-type]
    order: list[str] = []
    scope.add_effect(lambda: order.append("first"))
    scope.add_effect(lambda: order.append("second"))
    scope.lifecycle.apply_event("turn_start")

    scope.close()
    scope.close()

    assert order == ["second", "first"]
    assert engine.interrupts == 1
    assert scope.lifecycle.phase is AgentPhase.IDLE


def test_closed_scope_rejects_new_effects() -> None:
    scope = RuntimeScope("session-1", StubEngine())  # type: ignore[arg-type]
    scope.close()

    with pytest.raises(RuntimeError, match="is closed"):
        scope.add_effect(lambda: None)


def test_registry_is_the_single_runtime_inventory() -> None:
    registry = RuntimeRegistry()
    engine = StubEngine()

    scope = registry.publish("session-1", engine)  # type: ignore[arg-type]
    assert registry.engine("session-1") is engine
    assert scope.claim() is True
    assert scope.lifecycle.phase is AgentPhase.IDLE
    assert scope.claim() is False

    removed = registry.pop("session-1")
    assert removed is scope
    removed.close()
    assert registry.engine("session-1") is None


def test_discard_removes_and_closes_runtime() -> None:
    registry = RuntimeRegistry()
    engine = StubEngine()
    registry.publish("session-1", engine)  # type: ignore[arg-type]

    removed = registry.discard("session-1")

    assert removed is not None and removed.closed
    assert engine.interrupts == 1
    assert registry.scope("session-1") is None


def test_prepare_does_not_publish_partial_runtime() -> None:
    registry = RuntimeRegistry()
    scope = registry.prepare("session-1")

    assert registry.scope("session-1") is None
    engine = StubEngine()
    registry.publish("session-1", engine, scope=scope)  # type: ignore[arg-type]
    assert registry.engine("session-1") is engine


def test_publish_rejects_competing_runtime_for_same_session() -> None:
    registry = RuntimeRegistry()
    registry.publish("session-1", StubEngine())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="already published"):
        registry.publish("session-1", StubEngine())  # type: ignore[arg-type]


def test_failed_unpublished_scope_can_unwind_without_entering_registry() -> None:
    registry = RuntimeRegistry()
    scope = registry.prepare("session-1")
    released: list[bool] = []
    scope.add_effect(lambda: released.append(True))

    scope.close()

    assert released == [True]
    assert registry.scope("session-1") is None
