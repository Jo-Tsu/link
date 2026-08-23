"""Small, explicit prompt contribution assembly.

The registry owns only ordering, provenance, and rendering. Callers remain responsible
for deciding which contributions apply to a session or turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class PromptContribution:
    """One named block in a rendered prompt."""

    id: str
    text: str
    order: int
    source: str
    scope: str
    layer: int = 0


class PromptRegistry:
    """Collect prompt blocks and render them in stable declared order."""

    def __init__(
        self, contributions: Iterable[PromptContribution] = ()
    ) -> None:
        self._contributions: dict[str, PromptContribution] = {}
        for contribution in contributions:
            self.register(contribution)

    def register(self, contribution: PromptContribution) -> None:
        if contribution.id in self._contributions:
            raise ValueError(f"duplicate prompt id: {contribution.id}")
        self._contributions[contribution.id] = contribution

    def contributions(
        self, *, scope: Optional[str] = None
    ) -> tuple[PromptContribution, ...]:
        selected = (
            contribution
            for contribution in self._contributions.values()
            if scope is None or contribution.scope == scope
        )
        # Python's sort is stable, so equal-order contributions retain registration order.
        return tuple(sorted(selected, key=lambda contribution: contribution.order))

    def render(self, *, scope: Optional[str] = None) -> str:
        return "\n\n".join(
            contribution.text for contribution in self.contributions(scope=scope)
        )


# Per-turn read-only mode guidance. These remain aliases imported by ``smallink.agent``
# for callers that historically inspected the private constants there.
_DISCUSS_MODE_CONTEXT = """\
Discuss mode is active: write and shell tools are disabled. Explore and answer freely; if
the user asks for a change, describe it in chat instead of attempting it (they can switch
to plan or approval mode to have you make it)."""

_PLAN_MODE_CONTEXT = """\
Plan mode is active: write and shell tools are blocked. Explore read-only and design an
approach. When you've committed to one, present it with `propose_plan` (what you'll change,
in which files, how you'll verify) — don't describe edits as if you were making them. If
the plan is approved, this same session switches to execution and you implement it; if
rejected, revise the plan using the feedback."""

_MEMORY_CONTEXT_GUIDANCE = """\
Memory context:
- The known memories below are read-only context. Do not claim to create, update, or delete \
formal memories from this session.
- New durable facts must be proposed through Smallink data governance, traced to source records, \
and confirmed by the user before they enter the formal memory store.
- If a memory names a file, flag, or URL, verify it still exists before relying on it."""

_NARRATION_GUIDANCE = """\
Narration: before each batch of tool calls, write ONE short plain sentence saying what \
you're doing and why (e.g. "Checking what merged since yesterday's digest."). It is shown \
to the user as live progress. Don't narrate trivial single-call follow-ups, don't repeat \
the previous line, and never let narration replace your final answer."""

_DELEGATION_GUIDANCE = """\
Multi-agent delegation:
- You own the user's task and final answer. A specialist returns evidence or critique to you; it \
does not replace your judgment.
- Use `delegate_to_agent` when a meaningful subtask benefits from an isolated context: \
`researcher` gathers cited evidence, `analyst` compares and synthesizes it, and `reviewer` checks \
an artifact or proposal for defects and gaps. Keep trivial work in the main context.
- Give the specialist a self-contained assignment and expected output. Independent delegations \
may be requested together. Specialists are read-only and cannot delegate again."""


def session_prompt_registry(
    *,
    agent_id: str,
    agent_prompt: str,
    delegation: bool = False,
    environment: Optional[str] = None,
    agents_md: str = "",
    memory: bool = False,
    skill_catalog: str = "",
) -> PromptRegistry:
    """Build the static session prompt in the legacy ``build_engine`` order."""
    contributions = [
        PromptContribution(
            f"agent_{agent_id}",
            agent_prompt,
            10,
            f"agent:{agent_id}",
            "session",
            1,
        ),
        PromptContribution(
            "narration",
            _NARRATION_GUIDANCE,
            20,
            "smallink/prompts.py :: _NARRATION_GUIDANCE",
            "session",
            2,
        ),
    ]
    if delegation:
        contributions.append(
            PromptContribution(
                "delegation",
                _DELEGATION_GUIDANCE,
                30,
                "smallink/prompts.py :: _DELEGATION_GUIDANCE",
                "session",
                2,
            )
        )
    if environment is not None:
        contributions.append(
            PromptContribution(
                "environment",
                environment,
                40,
                "smallink/environment.py :: environment_context()",
                "session",
                3,
            )
        )
    if agents_md:
        contributions.append(
            PromptContribution(
                "agents_md",
                agents_md,
                50,
                "workspace AGENTS.md",
                "session",
                4,
            )
        )
    if memory:
        contributions.append(
            PromptContribution(
                "memory_guidance",
                _MEMORY_CONTEXT_GUIDANCE,
                60,
                "smallink/prompts.py :: _MEMORY_CONTEXT_GUIDANCE",
                "session",
                5,
            )
        )
    if skill_catalog:
        contributions.append(
            PromptContribution(
                "skill_catalog",
                skill_catalog,
                70,
                "smallink/skills :: skill_catalog_text()",
                "session",
                6,
            )
        )
    return PromptRegistry(contributions)


def turn_prompt_registry(
    *, mode: Optional[str] = None, roots: str = "", memories: str = ""
) -> PromptRegistry:
    """Build per-turn context in the legacy mode, roots, memories order."""
    contributions: list[PromptContribution] = []
    if mode == "plan":
        contributions.append(
            PromptContribution(
                "plan_mode",
                _PLAN_MODE_CONTEXT,
                10,
                "smallink/prompts.py :: _PLAN_MODE_CONTEXT",
                "turn",
                7,
            )
        )
    elif mode == "discuss":
        contributions.append(
            PromptContribution(
                "discuss_mode",
                _DISCUSS_MODE_CONTEXT,
                10,
                "smallink/prompts.py :: _DISCUSS_MODE_CONTEXT",
                "turn",
                7,
            )
        )
    if roots:
        contributions.append(
            PromptContribution(
                "roots",
                roots,
                20,
                "smallink/roots.py :: render_context()",
                "turn",
                7,
            )
        )
    if memories:
        contributions.append(
            PromptContribution(
                "memories",
                memories,
                30,
                "smallink/memory :: format_memories()",
                "turn",
                7,
            )
        )
    return PromptRegistry(contributions)


def merge_prompt_contributions(
    *registries: PromptRegistry,
) -> tuple[PromptContribution, ...]:
    """Merge unique contributions from multiple registries in stable prompt order."""
    merged: list[PromptContribution] = []
    seen: set[str] = set()
    for registry in registries:
        for contribution in registry.contributions():
            if contribution.id in seen:
                continue
            seen.add(contribution.id)
            merged.append(contribution)
    return tuple(
        sorted(
            merged,
            key=lambda contribution: (contribution.layer, contribution.order),
        )
    )
