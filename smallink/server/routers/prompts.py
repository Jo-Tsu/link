"""GET /v1/prompts — exposes prompt assembly using real PromptRegistry contributions."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ...agents.link import LINK_INSTRUCTIONS
from ...agents.code import CODE_INSTRUCTIONS
from ...agents.chat import CHAT_INSTRUCTIONS
from ...prompts import (
    PromptContribution,
    PromptRegistry,
    merge_prompt_contributions,
    session_prompt_registry,
    turn_prompt_registry,
)
from ...environment import environment_context


def _ops_prompt() -> str:
    try:
        from pathlib import Path

        ops_path = (
            Path(__file__).resolve().parents[2] / "personas" / "builtin" / "ops.md"
        )
        if ops_path.is_file():
            raw = ops_path.read_text()
            parts = raw.split("---", 2)
            if len(parts) >= 3:
                return parts[2].strip()
            return raw
    except Exception:
        pass
    return "(could not read ops.md)"


def _ops_contribution() -> PromptContribution:
    return PromptContribution(
        "agent_ops",
        _ops_prompt(),
        10,
        "smallink/personas/builtin/ops.md (body after frontmatter)",
        "session",
        1,
    )


def _compat_meta(contribution: PromptContribution) -> dict[str, Any]:
    agent_meta = {
        "agent_link": {
            "name": "Link Agent (Knowledge Work)",
            "description": "Default agent persona for general knowledge work sessions. Defines the agent's role, how it uses tools, and deliverable expectations.",
            "editable": True,
            "safety": "safe",
            "safety_note": "Modifying this prompt changes how the agent talks and approaches tasks, but does not affect the tool execution pipeline, session lifecycle, or memory governance. Safe to customize tone, style, constraints.",
        },
        "agent_code": {
            "name": "Code Agent (Coding Surface)",
            "description": "Coding-focused persona for software engineering work. Defines coding style rules, verification expectations, and edit tool preferences.",
            "editable": True,
            "safety": "safe",
            "safety_note": "Modifying this prompt changes coding behavior (how the agent explores, edits, verifies). It does NOT affect the tool registry, permission engine, or file-write mechanics. Safe to adjust coding conventions.",
        },
        "agent_chat": {
            "name": "Chat Agent (No Tools)",
            "description": "Lightweight conversational agent with no file or shell access. Used for general Q&A.",
            "editable": True,
            "safety": "safe",
            "safety_note": "This agent has no tools. Modifying the prompt only changes conversation behavior. Fully safe to customize.",
        },
        "agent_ops": {
            "name": "Ops Agent (Runbooks & Incidents)",
            "description": "Operations persona for investigating incidents and producing operational deliverables. Loaded from personas/builtin/ops.md.",
            "editable": True,
            "safety": "safe",
            "safety_note": "Same as other agent prompts — changes affect behavior style only. The ops toolset is declared in the frontmatter (not in the prompt body), so editing the prose cannot escalate permissions.",
        },
    }
    contribution_meta = {
        "narration": {
            "name": "Narration Guidance",
            "description": "Appended to every agent. Tells the model to emit short progress lines before tool batches so the GUI can show live status.",
            "editable": True,
            "safety": "safe",
            "safety_note": "Controls UX narration style only. Removing it means the GUI progress panel shows nothing during tool work — cosmetic, not functional.",
        },
        "delegation": {
            "name": "Delegation Guidance",
            "description": "Appended when the current agent/runtime actually exposes delegated specialist runs. Describes the bounded multi-agent contract and explicitly prohibits recursive delegation.",
            "editable": "caution",
            "safety": "caution",
            "safety_note": "This is prompt-level guidance for a real tool path. Weakening it will not create delegation by itself, but it can make delegated work less bounded or less predictable. Keep the explicit ownership and no-recursive-delegation constraints.",
        },
        "environment": {
            "name": "Environment Context (Dynamic Example)",
            "description": "Example output from the dynamically generated session environment block. The real value is computed from actual workspace and system state at session start.",
            "editable": False,
            "safety": "system",
            "safety_note": "This text is a sample, not a persisted prompt. The real environment block is generated from actual state. Changing generation code can affect workspace boundaries and runtime behavior.",
        },
        "agents_md": {
            "name": "AGENTS.md Conventions",
            "description": "Workspace-local conventions appended when an AGENTS.md file is present at the project root.",
            "editable": True,
            "safety": "safe",
            "safety_note": "This comes from a user-controlled workspace file. Editing the file changes local conventions only; it does not alter the server's tool or permission pipeline.",
        },
        "memory_guidance": {
            "name": "Memory Context Guidance",
            "description": "Governance rules that prevent the agent from claiming to create or modify formal memories directly. Ensures the human-review pipeline.",
            "editable": "caution",
            "safety": "caution",
            "safety_note": "This enforces the memory governance contract (memories require user confirmation). Weakening it could let the agent claim it stored memories without going through the pipeline. Edits here should preserve the read-only and must-be-confirmed invariant.",
        },
        "skill_catalog": {
            "name": "Skill Catalog (Dynamic Example)",
            "description": "Example of the dynamically generated skill catalog appended when skills are available for the current workspace and user scope.",
            "editable": False,
            "safety": "system",
            "safety_note": "This is generated from installed skills, not edited as a prompt. Change the available skills instead of editing this output shape.",
        },
        "plan_mode": {
            "name": "Plan Mode Context (Per-Turn)",
            "description": "Injected into the latest user message when the session is in plan mode. Reinforces the read-only planning contract for that turn.",
            "editable": "caution",
            "safety": "caution",
            "safety_note": "Plan mode is also enforced by PermissionEngine. This prompt is a soft reinforcement; removing it will not bypass safety, but it can increase rejected tool attempts and drift from intended behavior.",
        },
        "discuss_mode": {
            "name": "Discuss Mode Context (Per-Turn)",
            "description": "Injected when discuss mode is active. Similar to plan mode but without the plan-proposal expectation.",
            "editable": "caution",
            "safety": "caution",
            "safety_note": "Discuss mode is also enforced by PermissionEngine. This prompt is a soft guide; removing it will not bypass safety, but it can increase rejected tool attempts and blur the read-only discussion contract.",
        },
        "roots": {
            "name": "Root Context (Dynamic Example)",
            "description": "Example of the per-turn root-directory context rendered from the live workspace root set.",
            "editable": False,
            "safety": "system",
            "safety_note": "This is generated from the current runtime root set. The example is illustrative; the real block changes as roots are added or removed during a session.",
        },
        "memories": {
            "name": "Memory Injection (Dynamic Example)",
            "description": "Example of selected memories formatted into per-turn context. Real content is chosen dynamically from the memory store for the current turn.",
            "editable": False,
            "safety": "system",
            "safety_note": "This block is produced from stored memories selected at runtime. It is not a static prompt layer; changing selection or formatting code affects what the model sees.",
        },
    }
    meta = agent_meta.get(contribution.id) or contribution_meta.get(contribution.id)
    if meta is None:
        label = contribution.id.replace("_", " ").title()
        meta = {
            "name": label,
            "description": f"Prompt contribution `{contribution.id}` from the real PromptRegistry.",
            "editable": False,
            "safety": "system",
            "safety_note": "Generated from the real PromptRegistry contribution metadata.",
        }
    return {
        "id": contribution.id,
        "layer": contribution.layer,
        "name": meta["name"],
        "description": meta["description"],
        "source": contribution.source,
        "scope": contribution.scope,
        "editable": meta["editable"],
        "safety": meta["safety"],
        "safety_note": meta["safety_note"],
        "text": contribution.text,
    }


def prompts_router(manager: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/prompts")
    def get_prompts() -> dict[str, Any]:
        sample_env = environment_context("/example/workspace")
        sample_agents_md = (
            "# Workspace conventions (dynamic example)\n"
            "Project-specific instructions from the active workspace appear here."
        )
        sample_skill_catalog = (
            "Available skills (dynamic example):\n"
            "- example-skill: Loaded from the current user and workspace skill roots."
        )
        sample_roots = (
            "Available directories (dynamic example):\n"
            "- /example/workspace [read-write] — primary scratch"
        )
        sample_memories = (
            "Confirmed memories (dynamic example):\n"
            "- Only active, scope-matched memories selected for the current turn appear here."
        )
        session = merge_prompt_contributions(
            session_prompt_registry(
                agent_id="link",
                agent_prompt=LINK_INSTRUCTIONS,
                delegation=True,
                environment=sample_env,
                agents_md=sample_agents_md,
                memory=True,
                skill_catalog=sample_skill_catalog,
            ),
            session_prompt_registry(
                agent_id="code",
                agent_prompt=CODE_INSTRUCTIONS,
                delegation=True,
                environment=sample_env,
                memory=True,
            ),
            session_prompt_registry(
                agent_id="chat",
                agent_prompt=CHAT_INSTRUCTIONS,
                delegation=False,
                environment=sample_env,
                memory=True,
            ),
            PromptRegistry([_ops_contribution()]),
        )
        turn = merge_prompt_contributions(
            turn_prompt_registry(
                mode="plan", roots=sample_roots, memories=sample_memories
            ),
            turn_prompt_registry(mode="discuss"),
        )
        layers = [_compat_meta(contribution) for contribution in [*session, *turn]]

        assembly_order = [
            "Layer 1: Agent System Prompt (one of: link / code / chat / ops persona)",
            "Layer 2: Narration and delegation guidance (appended when the runtime enables them)",
            "Layer 3: Environment Context (dynamic, generated at session start)",
            "Layer 4: AGENTS.md (project conventions file, if present in workspace root)",
            "Layer 5: Memory Context Guidance (when memory store is active)",
            "Layer 6: Skill Catalog (dynamic list of registered skills)",
            "Layer 7: Per-Turn Ephemeral Context (plan/discuss mode + roots + memory injection)",
        ]

        return {
            "layers": layers,
            "assembly_order": assembly_order,
            "assembly_source": "smallink.prompts.session_prompt_registry + smallink.prompts.turn_prompt_registry",
            "notes": {
                "layer_4_agents_md": "Read from workspace root at session start. User-created file — always safe to edit.",
                "layer_6_skill_catalog": "Auto-generated from registered skills. The displayed text is an explicit example; add or remove skills rather than editing the rendered output.",
                "layer_7_memory_injection": "Memories selected by select_memories() and formatted by format_memories(). Content comes from the memory store, not a static prompt.",
            },
        }

    return router
