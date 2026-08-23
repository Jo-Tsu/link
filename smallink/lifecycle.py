"""Agent lifecycle state machine — observable, deterministic phase transitions.

Each session has exactly one AgentPhase at any time. Transitions emit a
PHASE_CHANGED event so any consumer (WS, TUI, tests) can derive the phase
from the event stream without inferring it from content events.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Optional


class AgentPhase(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    THINKING = "thinking"
    TOOL_PENDING = "tool_pending"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    COMPLETING = "completing"
    ERRORED = "errored"
    INTERRUPTED = "interrupted"


_TRANSITIONS: dict[AgentPhase, set[AgentPhase]] = {
    AgentPhase.IDLE: {AgentPhase.STARTING},
    AgentPhase.STARTING: {AgentPhase.THINKING, AgentPhase.ERRORED, AgentPhase.INTERRUPTED},
    AgentPhase.THINKING: {
        AgentPhase.TOOL_PENDING,
        AgentPhase.EXECUTING,
        AgentPhase.COMPLETING,
        AgentPhase.ERRORED,
        AgentPhase.INTERRUPTED,
    },
    AgentPhase.TOOL_PENDING: {
        AgentPhase.AWAITING_APPROVAL,
        AgentPhase.EXECUTING,
        AgentPhase.THINKING,
        AgentPhase.ERRORED,
        AgentPhase.INTERRUPTED,
    },
    AgentPhase.AWAITING_APPROVAL: {
        AgentPhase.EXECUTING,
        AgentPhase.TOOL_PENDING,
        AgentPhase.THINKING,
        AgentPhase.ERRORED,
        AgentPhase.INTERRUPTED,
    },
    AgentPhase.EXECUTING: {
        AgentPhase.THINKING,
        AgentPhase.COMPLETING,
        AgentPhase.ERRORED,
        AgentPhase.INTERRUPTED,
    },
    AgentPhase.COMPLETING: {AgentPhase.IDLE},
    AgentPhase.ERRORED: {AgentPhase.IDLE},
    AgentPhase.INTERRUPTED: {AgentPhase.IDLE},
}

PhaseListener = Callable[["AgentPhase", "AgentPhase", dict[str, Any]], None]


class InvalidTransition(Exception):
    def __init__(self, from_phase: AgentPhase, to_phase: AgentPhase) -> None:
        super().__init__(f"Invalid transition: {from_phase.value} -> {to_phase.value}")
        self.from_phase = from_phase
        self.to_phase = to_phase


class LifecycleTracker:
    """Per-session state machine. Validates transitions and notifies listeners."""

    def __init__(
        self,
        session_id: str,
        *,
        on_transition: Optional[PhaseListener] = None,
    ) -> None:
        self.session_id = session_id
        self._phase = AgentPhase.IDLE
        self._listeners: list[PhaseListener] = []
        if on_transition:
            self._listeners.append(on_transition)

    @property
    def phase(self) -> AgentPhase:
        return self._phase

    @property
    def is_busy(self) -> bool:
        return self._phase not in (
            AgentPhase.IDLE,
            AgentPhase.ERRORED,
            AgentPhase.INTERRUPTED,
        )

    def transition(self, target: AgentPhase, context: Optional[dict[str, Any]] = None) -> None:
        if target == self._phase:
            return
        allowed = _TRANSITIONS.get(self._phase, set())
        if target not in allowed:
            raise InvalidTransition(self._phase, target)
        prev = self._phase
        self._phase = target
        ctx = context or {}
        for listener in self._listeners:
            listener(prev, target, ctx)

    def reset(self) -> None:
        self._phase = AgentPhase.IDLE

    def add_listener(self, fn: PhaseListener) -> None:
        self._listeners.append(fn)

    def remove_listener(self, fn: PhaseListener) -> None:
        self._listeners = [l for l in self._listeners if l is not fn]

    def apply_event(self, event_type: str) -> bool:
        """Project one engine event into lifecycle state.

        The engine may emit a completed assistant message without token deltas, so
        semantic message/tool/end events include the intermediate states needed for
        a legal transition. Unknown and state-neutral events return ``False``.
        """
        target = {
            "assistant_delta": AgentPhase.THINKING,
            "reasoning_delta": AgentPhase.THINKING,
            "assistant_message": AgentPhase.THINKING,
            "tool_proposed": AgentPhase.TOOL_PENDING,
            "permission_required": AgentPhase.AWAITING_APPROVAL,
            "directory_requested": AgentPhase.AWAITING_APPROVAL,
            "question_requested": AgentPhase.AWAITING_APPROVAL,
            "plan_proposed": AgentPhase.AWAITING_APPROVAL,
            "tool_started": AgentPhase.EXECUTING,
            "tool_finished": AgentPhase.THINKING,
            "turn_end": AgentPhase.COMPLETING,
            "error": AgentPhase.ERRORED,
            "interrupted": AgentPhase.INTERRUPTED,
        }.get(event_type)
        if event_type == "turn_start":
            if self.phase == AgentPhase.STARTING:
                return False
            if self.phase != AgentPhase.IDLE:
                raise InvalidTransition(self.phase, AgentPhase.STARTING)
            self.transition(AgentPhase.STARTING, {"event_type": event_type})
            return True
        if target is None or target == self.phase:
            return False
        if self.phase == AgentPhase.IDLE:
            if target not in {
                AgentPhase.THINKING,
                AgentPhase.TOOL_PENDING,
                AgentPhase.COMPLETING,
                AgentPhase.ERRORED,
                AgentPhase.INTERRUPTED,
            }:
                raise InvalidTransition(self.phase, target)
            self.transition(AgentPhase.STARTING, {"event_type": event_type})
        if self.phase == AgentPhase.STARTING and target in {
            AgentPhase.TOOL_PENDING,
            AgentPhase.COMPLETING,
        }:
            self.transition(AgentPhase.THINKING, {"event_type": event_type})
        self.transition(target, {"event_type": event_type})
        return True

    def finish(self, context: Optional[dict[str, Any]] = None) -> None:
        """Return to idle at the owner-controlled end of a run.

        ``mark_running`` is a concurrency claim and may wrap callers that consume
        the engine stream directly. In that case there are no projected semantic
        events, but releasing the claim is still an explicit lifecycle boundary.
        """
        if self.phase == AgentPhase.IDLE:
            return
        previous = self._phase
        self._phase = AgentPhase.IDLE
        ctx = context or {}
        for listener in self._listeners:
            listener(previous, AgentPhase.IDLE, ctx)
