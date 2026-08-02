"""Runtime observer used by child agents without coupling them to SessionManager."""

from __future__ import annotations

from typing import Any, Optional

from .store import SQLiteTaskRuntimeStore


class AgentRunObserver:
    """Attach child-agent execution to the active root run for one session."""

    def __init__(self, store: SQLiteTaskRuntimeStore, session_id: str) -> None:
        self.store = store
        self.session_id = session_id

    def start(
        self, *, agent_role: str, model: Optional[str], input_value: Any
    ) -> Optional[str]:
        parent = self.store.active_root_for_session(self.session_id)
        if parent is None:
            return None
        child = self.store.start_child_run(
            parent_agent_run_id=parent.agent_run_id,
            agent_role=agent_role,
            model=model,
            input_value=input_value,
        )
        return child.agent_run_id

    def event(
        self, agent_run_id: Optional[str], event_type: str, data: dict[str, Any]
    ) -> None:
        if agent_run_id is not None:
            self.store.append_event(agent_run_id, event_type, data)

    def finish(
        self,
        agent_run_id: Optional[str],
        *,
        status: str,
        output: Any = None,
        error: Optional[str] = None,
    ) -> None:
        if agent_run_id is not None:
            self.store.finish_agent_run(
                agent_run_id, status=status, output=output, error=error
            )
