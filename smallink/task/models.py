"""Domain records for durable task, task-run, agent-run and event history."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    session_id: str
    title: str
    status: str
    project_id: Optional[str]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskRunRecord:
    task_run_id: str
    task_id: str
    trigger: str
    status: str
    model: Optional[str]
    mode: Optional[str]
    started_at: str
    finished_at: Optional[str]
    error: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentRunRecord:
    agent_run_id: str
    task_run_id: str
    parent_agent_run_id: Optional[str]
    root_agent_run_id: str
    agent_role: str
    status: str
    model: Optional[str]
    input: Any
    output: Any
    started_at: str
    finished_at: Optional[str]
    error: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RunEventRecord:
    event_id: str
    agent_run_id: str
    sequence: int
    event_type: str
    data: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
