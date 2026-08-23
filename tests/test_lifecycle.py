from __future__ import annotations

import pytest

from smallink.lifecycle import AgentPhase, InvalidTransition, LifecycleTracker


def test_non_streaming_turn_has_legal_lifecycle() -> None:
    tracker = LifecycleTracker("session-1")

    for event_type in ("turn_start", "assistant_message", "turn_end"):
        tracker.apply_event(event_type)

    assert tracker.phase is AgentPhase.COMPLETING
    tracker.transition(AgentPhase.IDLE)
    assert tracker.phase is AgentPhase.IDLE


def test_non_streaming_tool_turn_has_legal_lifecycle() -> None:
    tracker = LifecycleTracker("session-1")

    phases = []
    for event_type in (
        "turn_start",
        "assistant_message",
        "tool_proposed",
        "permission_required",
        "tool_started",
        "tool_finished",
        "assistant_message",
        "turn_end",
    ):
        tracker.apply_event(event_type)
        phases.append(tracker.phase)

    assert phases == [
        AgentPhase.STARTING,
        AgentPhase.THINKING,
        AgentPhase.TOOL_PENDING,
        AgentPhase.AWAITING_APPROVAL,
        AgentPhase.EXECUTING,
        AgentPhase.THINKING,
        AgentPhase.THINKING,
        AgentPhase.COMPLETING,
    ]


def test_illegal_transition_fails_loudly() -> None:
    tracker = LifecycleTracker("session-1")

    with pytest.raises(InvalidTransition):
        tracker.apply_event("tool_started")

    assert tracker.phase is AgentPhase.IDLE


def test_durable_resume_can_finish_an_already_resolved_prompt() -> None:
    tracker = LifecycleTracker("session-1")

    for event_type in (
        "turn_start",
        "assistant_message",
        "tool_proposed",
        "tool_finished",
        "assistant_message",
        "turn_end",
    ):
        tracker.apply_event(event_type)

    assert tracker.phase is AgentPhase.COMPLETING


def test_first_semantic_event_bootstraps_missing_turn_start() -> None:
    tracker = LifecycleTracker("session-1")

    tracker.apply_event("tool_proposed")

    assert tracker.phase is AgentPhase.TOOL_PENDING
