"""Bounded specialist delegation for Smallink's multi-agent runtime.

The parent agent owns the user conversation and final answer. A delegated specialist gets a
fresh context window plus a deliberately read-only toolset, then returns one self-contained
report. Child engines never receive ``delegate_to_agent``, so the first implementation cannot
silently grow an unbounded agent tree.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import aisuite as ai

from ..engine import TurnEngine
from ..events import EventType
from ..permissions import Mode, PermissionEngine
from ..tools import ToolRegistry
from .files import file_tools
from .search import search_tools


@dataclass(frozen=True)
class SpecialistProfile:
    role: str
    purpose: str
    instructions: str


SPECIALIST_PROFILES: dict[str, SpecialistProfile] = {
    "researcher": SpecialistProfile(
        role="researcher",
        purpose="Collect cited evidence from project files, indexed knowledge, and the web.",
        instructions=(
            "You are Smallink's read-only Researcher. Gather evidence for the assigned task "
            "from the available project files, indexed knowledge, and web tools. Distinguish "
            "facts from inference, preserve source paths or URLs, and call out missing evidence."
        ),
    ),
    "analyst": SpecialistProfile(
        role="analyst",
        purpose="Compare evidence, identify patterns, and produce a decision-ready synthesis.",
        instructions=(
            "You are Smallink's read-only Analyst. Turn the assigned material into a concise, "
            "decision-ready synthesis. State assumptions, compare alternatives, explain tradeoffs, "
            "and trace every important conclusion to the evidence you inspected."
        ),
    ),
    "reviewer": SpecialistProfile(
        role="reviewer",
        purpose="Review a proposal or artifact for correctness, gaps, risks, and missing tests.",
        instructions=(
            "You are Smallink's read-only Reviewer. Inspect the assigned proposal, implementation, "
            "or artifact critically. Lead with concrete defects and risks, then missing evidence or "
            "tests, and finish with a clear pass/revise recommendation. Do not edit anything."
        ),
    ),
}

_CHILD_MAX_ITERATIONS = 10
_COMMON_INSTRUCTIONS = """

You work for a parent agent, not directly for the user. Use only the read-only tools provided.
You cannot write files, run shell commands, contact external systems, or delegate another agent.
Your final message is the report returned to the parent. Make it self-contained, readable, and
specific. Include source paths, record identifiers, or URLs whenever the tools expose them. If
the requested evidence is unavailable, say what you checked instead of guessing.
"""


def build_specialist_engine(
    *,
    workspace: str | Path,
    provider: Any,
    model: str,
    role: str,
    read_tools: Optional[list[Any]] = None,
    model_settings: Optional[dict[str, Any]] = None,
    max_iterations: int = _CHILD_MAX_ITERATIONS,
) -> TurnEngine:
    """Build one isolated specialist engine with no mutating or recursive tools."""
    profile = SPECIALIST_PROFILES.get(role)
    if profile is None:
        raise ValueError(f"unknown specialist role: {role}")

    ws = str(Path(workspace).expanduser().resolve())
    registry = ToolRegistry()
    # aisuite's files toolkit without allow_write exposes list/read helpers. Smallink's
    # line-numbered reader replaces the toolkit readers so reports can cite path:line.
    replaced = {"search_files", "read_file", "read_file_lines"}
    registry.register_all(
        [
            tool
            for tool in ai.toolkits.files(root=ws)
            if getattr(tool, "__name__", "") not in replaced
        ]
    )
    registry.register_all(file_tools(ws))
    registry.register_all(search_tools(ws))
    registry.register_all(list(read_tools or []))

    return TurnEngine(
        provider=provider,
        registry=registry,
        permissions=PermissionEngine(workspace_root=Path(ws), mode=Mode.PLAN),
        model=model,
        instructions=f"{profile.instructions}{_COMMON_INSTRUCTIONS}",
        max_iterations=max_iterations,
        model_settings=model_settings,
    )


def delegation_tools(
    *,
    workspace: str | Path,
    provider: Any,
    model: str,
    read_tools: Optional[list[Any]] = None,
    model_settings: Optional[dict[str, Any]] = None,
    run_observer: Optional[Any] = None,
) -> list[Any]:
    """Expose one generic delegation primitive backed by durable child AgentRuns."""

    def delegate_to_agent(
        role: str,
        task: str,
        expected_output: str = "",
    ) -> dict[str, Any]:
        """Delegate bounded read-only work to a specialist with a fresh context.

        Args:
            role (str): Specialist role: researcher, analyst, or reviewer.
            task (str): Precise assignment including relevant context and constraints.
            expected_output (str): Optional description of the report shape the parent needs.
        """
        normalized_role = str(role or "").strip().lower()
        profile = SPECIALIST_PROFILES.get(normalized_role)
        if profile is None:
            return {
                "error": f"unknown specialist role: {role}",
                "allowed_roles": list(SPECIALIST_PROFILES),
            }
        clean_task = str(task or "").strip()
        if not clean_task:
            return {"error": "task is required"}

        assignment = clean_task
        if expected_output.strip():
            assignment += f"\n\nExpected report: {expected_output.strip()}"
        child_run_id = (
            run_observer.start(
                agent_role=normalized_role,
                model=model,
                input_value={
                    "role": normalized_role,
                    "task": clean_task,
                    "expected_output": expected_output.strip(),
                },
            )
            if run_observer is not None
            else None
        )
        engine = build_specialist_engine(
            workspace=workspace,
            provider=provider,
            model=model,
            role=normalized_role,
            read_tools=read_tools,
            model_settings=model_settings,
        )

        async def _run() -> tuple[str, str]:
            report, status = "", "unknown"
            async for event in engine.run(assignment):
                if run_observer is not None:
                    run_observer.event(child_run_id, event.type.value, event.data)
                if event.type == EventType.ASSISTANT_MESSAGE and event.data.get("text"):
                    report = event.data["text"]
                elif event.type == EventType.TURN_END:
                    status = event.data.get("status", "unknown")
                elif event.type == EventType.ERROR:
                    return report, f"error: {event.data.get('error', '')}"
            return report, status

        try:
            report, status = asyncio.run(_run())
        except Exception as exc:
            if run_observer is not None:
                run_observer.finish(child_run_id, status="failed", error=str(exc))
            raise

        terminal_status = "completed" if status == "completed" else "failed"
        output = {
            "agent_role": normalized_role,
            "report": report,
            "engine_status": status,
        }
        if run_observer is not None:
            run_observer.finish(
                child_run_id,
                status=terminal_status,
                output=output,
                error=None if terminal_status == "completed" else status,
            )
        if not report:
            return {
                "agent_role": normalized_role,
                "agent_run_id": child_run_id,
                "error": f"specialist produced no report (status: {status})",
            }
        result: dict[str, Any] = {
            "agent_role": normalized_role,
            "agent_run_id": child_run_id,
            "purpose": profile.purpose,
            "report": report,
        }
        if status != "completed":
            result["note"] = (
                f"{normalized_role} stopped early ({status}); the report may be partial"
            )
        return result

    delegate_to_agent.__link_schema__ = {
        "type": "function",
        "function": {
            "name": "delegate_to_agent",
            "description": (
                "Delegate a bounded read-only assignment to a specialist with a fresh context. "
                "Use researcher for evidence gathering, analyst for synthesis and tradeoffs, and "
                "reviewer for defects, risks, and missing validation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "enum": list(SPECIALIST_PROFILES),
                        "description": "The specialist role to start.",
                    },
                    "task": {
                        "type": "string",
                        "description": "A precise, self-contained assignment.",
                    },
                    "expected_output": {
                        "type": "string",
                        "description": "Optional report format or acceptance criteria.",
                    },
                },
                "required": ["role", "task"],
            },
        },
    }
    return [
        ai.tool(
            delegate_to_agent,
            metadata=ai.ToolMetadata(
                category="agent",
                risk_level="low",
                capabilities=["delegate", "read"],
                requires_approval=False,
            ),
        )
    ]
