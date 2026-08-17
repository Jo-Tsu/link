"""Risk classes for tools — the intrinsic side-effect category that drives permission
gating (and, later in Phase 2, unattended Inbox routing).

This replaces the hardcoded ``WRITE_TOOLS`` / ``SHELL_TOOL`` name sets the permission engine
used to carry inline: risk is now a declared property a single ``classify`` reads.

A tool's *effective* risk = an optional user-local override (Phase 2) ?? the base
classification here. Built-in vetted tools are classified by name; anything else must carry
explicit low-risk metadata or is treated as consequential and requires approval.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Optional


class RiskClass(str, Enum):
    READ = "read"  # no side effects — always allowed
    WRITE_LOCAL = "write_local"  # mutates the workspace — path-scoped + mode-gated
    EXEC = "exec"  # runs commands — mode-gated
    EXTERNAL = "external"  # side effects off the machine — the unattended Inbox hook


# Built-in tools whose risk is fixed by name (the old WRITE_TOOLS / SHELL_TOOL, as data).
WRITE_TOOLS = {"write_file", "replace_in_file", "apply_patch", "apply_unified_diff"}
SHELL_TOOL = "run_shell"
READ_TOOLS = {"read_file", "grep", "git_log", "todo_write"}

_BASE: dict[str, RiskClass] = {
    **{name: RiskClass.READ for name in READ_TOOLS},
    **{name: RiskClass.WRITE_LOCAL for name in WRITE_TOOLS},
    SHELL_TOOL: RiskClass.EXEC,
}

# A user-local override resolver: tool name -> RiskClass (or None to defer to the base).
# Wired in Phase 2 (mainly to relax MCP's conservative default); always None until then.
RiskOverrides = Callable[[str], Optional["RiskClass"]]


def classify(
    tool_name: str, metadata: Any = None, overrides: Optional[RiskOverrides] = None
) -> RiskClass:
    """Effective risk of a tool call. ``overrides`` (user-local) wins, then the by-name base
    table, then explicit aisuite metadata. Unregistered or ambiguous tools fail closed as
    external-risk calls, so they cannot silently gain read-level privileges."""
    if overrides is not None:
        ov = overrides(tool_name)
        if ov is not None:
            return ov
    base = _BASE.get(tool_name)
    if base is not None:
        return base
    if bool(getattr(metadata, "requires_approval", False)):
        return RiskClass.EXTERNAL
    if str(getattr(metadata, "risk_level", "")).lower() == "low":
        return RiskClass.READ
    return RiskClass.EXTERNAL


def is_consequential(risk: RiskClass) -> bool:
    """Anything but a pure read needs the permission engine's attention."""
    return risk is not RiskClass.READ
