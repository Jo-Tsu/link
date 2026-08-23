"""Durable recording and lifecycle projection for one session turn.

This service deliberately owns only the cross-cutting work around an engine
event stream. Engine creation, session concurrency, persistence checkpoints,
and transport broadcasting remain SessionManager responsibilities.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any, Optional

from ..conversations import ConversationStore, title_from
from ..events import Event, EventType
from ..lifecycle import AgentPhase, LifecycleTracker
from ..sensory import SQLiteSensoryStore
from ..task import SQLiteTaskRuntimeStore

if TYPE_CHECKING:
    from ..engine import TurnEngine

logger = logging.getLogger("smallink.runtime.session")

_SENSORY_SECRET_PATTERN = re.compile(
    r"(?i)(password|passwd|secret|api[_ -]?key|access[_ -]?token|refresh[_ -]?token)"
    r"\s*[:=]\s*[^\s,;]+"
)


def sensory_safe(value: Any) -> Any:
    """Remove embedded binary payloads while retaining useful provenance."""
    if isinstance(value, str) and value.lstrip().lower().startswith("data:"):
        return {
            "omitted": True,
            "characters": len(value),
            "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
        }
    if isinstance(value, list):
        return [sensory_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: sensory_safe(item) for key, item in value.items()}
    return value


def sensory_sensitivity(value: Any) -> str:
    """Classify first-party captures before they enter the source pool."""
    try:
        text = (
            json.dumps(value, ensure_ascii=False)
            if not isinstance(value, str)
            else value
        )
    except (TypeError, ValueError):
        text = str(value)
    return "secret" if _SENSORY_SECRET_PATTERN.search(text) else "private"


class SessionRuntimeService:
    """Project a TurnEngine event stream into durable and sensory records."""

    def __init__(
        self,
        *,
        runtime_store: SQLiteTaskRuntimeStore,
        sensory_store: SQLiteSensoryStore,
        session_store: ConversationStore,
        lifecycle_for: Callable[[str], LifecycleTracker],
    ) -> None:
        self.runtime_store = runtime_store
        self.sensory_store = sensory_store
        self.session_store = session_store
        self._lifecycle_for = lifecycle_for

    def get_phase(self, session_id: str) -> AgentPhase:
        return self._lifecycle_for(session_id).phase

    async def tracked_engine_events(
        self,
        session_id: str,
        engine: TurnEngine,
        *,
        content: Any = None,
        source: Optional[dict[str, Any]] = None,
        trigger: str = "user",
        retry: bool = False,
        resume: bool = False,
        client_message_id: Optional[str] = None,
    ) -> AsyncIterator[Event]:
        """Run one engine turn and record its task, events, sensory data, and phase."""
        record = self.session_store.load(session_id)
        title = (record.title if record else None) or title_from(engine.messages)
        if title == "New session" and content is not None:
            title = title_from([{"role": "user", "content": content}])
        mode = getattr(getattr(engine, "permissions", None), "mode", None)
        input_value: Any = content
        if retry:
            input_value = {"action": "retry"}
        elif resume:
            input_value = {"action": "resume"}

        agent_run = (
            await asyncio.to_thread(self.runtime_store.resume_waiting_root, session_id)
            if resume
            else None
        )
        workspace = (
            str(getattr(getattr(engine, "executor", None), "cwd", "")) or None
        )
        if agent_run is None:
            project_id = record.project_id if record else None
            if not project_id and workspace:
                project = self.session_store.get_project_by_workspace(workspace)
                project_id = project.project_id if project else None
            _task_run, agent_run = await asyncio.to_thread(
                self.runtime_store.start_root_run,
                session_id=session_id,
                title=title,
                trigger=trigger,
                agent_role=getattr(engine, "agent_name", "code"),
                model=getattr(engine, "model", None),
                mode=getattr(mode, "value", str(mode) if mode is not None else None),
                input_value=input_value,
                project_id=project_id,
            )

        source_name = str((source or {}).get("connector") or "smallink")
        try:
            await asyncio.to_thread(
                self.sensory_store.add,
                source_type=source_name,
                connector_id=(source or {}).get("connector"),
                account_id=(source or {}).get("account_id")
                or (source or {}).get("team_id"),
                external_id=f"{agent_run.agent_run_id}:input",
                content_type="connector_input" if source else "user_input",
                raw_content=sensory_safe(input_value),
                sensitivity=sensory_sensitivity(input_value),
                project_path=workspace,
                conversation_id=session_id,
                metadata={
                    "agent_run_id": agent_run.agent_run_id,
                    "trigger": trigger,
                    "agent_role": getattr(engine, "agent_name", "code"),
                    "model": getattr(engine, "model", None),
                    "source": sensory_safe(source or {}),
                },
                source_locator=f"/v1/sessions/{session_id}/messages",
            )
        except Exception:
            logger.exception("could not capture sensory input for %s", session_id)

        terminal_status: Optional[str] = None
        terminal_error: Optional[str] = None
        output: dict[str, Any] = {}
        event_count = 0
        tracker = self._lifecycle_for(session_id)
        try:
            if resume:
                events = engine.resume()
            elif retry:
                events = engine.retry()
            elif client_message_id:
                events = engine.run(
                    content, source=source, client_message_id=client_message_id
                )
            else:
                events = engine.run(content, source=source)

            async for event in events:
                event_count += 1
                event_type = event.type.value
                phase_changed = tracker.apply_event(event_type)

                if event_type == "assistant_message":
                    cited = getattr(engine, "cited_memories", None)
                    if cited:
                        yield Event(EventType.MEMORY_CITED, {"memories": list(cited)})

                # Deltas are transport details; only complete semantic events are durable.
                if event_type not in {"assistant_delta", "reasoning_delta"}:
                    await asyncio.to_thread(
                        self.runtime_store.append_event,
                        agent_run.agent_run_id,
                        event_type,
                        event.data,
                    )

                sensory_type = {
                    "assistant_message": "assistant_output",
                    "tool_proposed": "tool_call",
                    "tool_finished": "tool_result",
                    "error": "runtime_error",
                    "interrupted": "runtime_error",
                }.get(event_type)
                if sensory_type:
                    try:
                        await asyncio.to_thread(
                            self.sensory_store.add,
                            source_type="smallink",
                            external_id=(
                                f"{agent_run.agent_run_id}:{event_count}:{event_type}"
                            ),
                            content_type=sensory_type,
                            raw_content=sensory_safe(event.data),
                            sensitivity=sensory_sensitivity(event.data),
                            project_path=workspace,
                            conversation_id=session_id,
                            metadata={
                                "agent_run_id": agent_run.agent_run_id,
                                "event_type": event_type,
                                "trigger": trigger,
                                "agent_role": getattr(engine, "agent_name", "code"),
                                "model": getattr(engine, "model", None),
                            },
                            source_locator=(
                                f"/v1/agent-runs/{agent_run.agent_run_id}/events"
                            ),
                        )
                    except Exception:
                        logger.exception(
                            "could not capture sensory event %s for %s",
                            event_type,
                            session_id,
                        )

                if event_type == "assistant_message" and event.data.get("text"):
                    output["text"] = event.data["text"]
                elif event_type == "turn_end":
                    engine_status = event.data.get("status", "completed")
                    terminal_status = (
                        "completed" if engine_status == "completed" else "failed"
                    )
                    output["engine_status"] = engine_status
                elif event_type == "error":
                    terminal_status = "failed"
                    terminal_error = str(event.data.get("error", "engine error"))
                elif event_type == "interrupted":
                    terminal_status = "cancelled"
                    terminal_error = str(
                        event.data.get("reason", "execution interrupted")
                    )

                yield event
                if phase_changed:
                    yield Event(
                        EventType.PHASE_CHANGED,
                        {
                            "phase": tracker.phase.value,
                            "trigger": event_type,
                            "session_id": session_id,
                        },
                    )

            if terminal_status is None:
                if event_count == 0 and (retry or resume):
                    terminal_status = "completed"
                    output["engine_status"] = "no_op"
                else:
                    terminal_status = "failed"
                    terminal_error = "engine event stream ended without a terminal event"
        except asyncio.CancelledError:
            terminal_status = "cancelled"
            terminal_error = "execution cancelled"
            raise
        except Exception as exc:
            terminal_status = "failed"
            terminal_error = str(exc)
            raise
        finally:
            await asyncio.to_thread(
                self.runtime_store.finish_agent_run,
                agent_run.agent_run_id,
                status=terminal_status or "failed",
                output=output or None,
                error=terminal_error,
            )
