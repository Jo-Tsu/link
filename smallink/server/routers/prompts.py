"""GET /v1/prompts — exposes the complete system-prompt architecture for inspection.

Each layer includes its raw text, a human-readable description, the source location,
and a safety annotation marking whether user edits affect core execution logic.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ...agents.link import LINK_INSTRUCTIONS
from ...agents.code import CODE_INSTRUCTIONS
from ...agents.chat import CHAT_INSTRUCTIONS
from ...agent import (
    _NARRATION_GUIDANCE,
    _MEMORY_CONTEXT_GUIDANCE,
    _PLAN_MODE_CONTEXT,
    _DISCUSS_MODE_CONTEXT,
)
from ...environment import environment_context


def prompts_router(manager: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/prompts")
    def get_prompts() -> dict[str, Any]:
        # Generate a sample environment context for display
        sample_env = environment_context("/example/workspace")

        # Read ops persona if available
        ops_prompt = ""
        try:
            from pathlib import Path
            ops_path = Path(__file__).resolve().parents[2] / "personas" / "builtin" / "ops.md"
            if ops_path.is_file():
                raw = ops_path.read_text()
                # Extract body after frontmatter
                parts = raw.split("---", 2)
                if len(parts) >= 3:
                    ops_prompt = parts[2].strip()
                else:
                    ops_prompt = raw
        except Exception:
            ops_prompt = "(could not read ops.md)"

        layers = [
            {
                "id": "agent_link",
                "layer": 1,
                "name": "Link Agent (Knowledge Work)",
                "description": "Default agent persona for general knowledge work sessions. Defines the agent's role, how it uses tools, and deliverable expectations.",
                "source": "smallink/agents/link.py :: LINK_INSTRUCTIONS",
                "editable": True,
                "safety": "safe",
                "safety_note": "Modifying this prompt changes how the agent talks and approaches tasks, but does not affect the tool execution pipeline, session lifecycle, or memory governance. Safe to customize tone, style, constraints.",
                "text": LINK_INSTRUCTIONS,
            },
            {
                "id": "agent_code",
                "layer": 1,
                "name": "Code Agent (Coding Surface)",
                "description": "Coding-focused persona for software engineering work. Defines coding style rules, verification expectations, and edit tool preferences.",
                "source": "smallink/agents/code.py :: CODE_INSTRUCTIONS",
                "editable": True,
                "safety": "safe",
                "safety_note": "Modifying this prompt changes coding behavior (how the agent explores, edits, verifies). It does NOT affect the tool registry, permission engine, or file-write mechanics. Safe to adjust coding conventions.",
                "text": CODE_INSTRUCTIONS,
            },
            {
                "id": "agent_chat",
                "layer": 1,
                "name": "Chat Agent (No Tools)",
                "description": "Lightweight conversational agent with no file or shell access. Used for general Q&A.",
                "source": "smallink/agents/chat.py :: CHAT_INSTRUCTIONS",
                "editable": True,
                "safety": "safe",
                "safety_note": "This agent has no tools. Modifying the prompt only changes conversation behavior. Fully safe to customize.",
                "text": CHAT_INSTRUCTIONS,
            },
            {
                "id": "agent_ops",
                "layer": 1,
                "name": "Ops Agent (Runbooks & Incidents)",
                "description": "Operations persona for investigating incidents and producing operational deliverables. Loaded from personas/builtin/ops.md.",
                "source": "smallink/personas/builtin/ops.md (body after frontmatter)",
                "editable": True,
                "safety": "safe",
                "safety_note": "Same as other agent prompts — changes affect behavior style only. The ops toolset is declared in the frontmatter (not in the prompt body), so editing the prose cannot escalate permissions.",
                "text": ops_prompt,
            },
            {
                "id": "narration",
                "layer": 2,
                "name": "Narration Guidance",
                "description": "Appended to every agent. Tells the model to emit short progress lines before tool batches so the GUI can show live status.",
                "source": "smallink/agent.py :: _NARRATION_GUIDANCE",
                "editable": True,
                "safety": "safe",
                "safety_note": "Controls UX narration style only. Removing it means the GUI progress panel shows nothing during tool work — cosmetic, not functional.",
                "text": _NARRATION_GUIDANCE,
            },
            {
                "id": "environment",
                "layer": 3,
                "name": "Environment Context (Dynamic)",
                "description": "Auto-generated snapshot of the session's workspace path, platform, date, and git state. Regenerated at session start.",
                "source": "smallink/environment.py :: environment_context()",
                "editable": False,
                "safety": "system",
                "safety_note": "This is dynamically generated from actual system state. It cannot be edited as a prompt — it's computed. Changing the generation code could cause the agent to operate outside workspace boundaries (the folder-scope restriction is enforced here).",
                "text": sample_env,
            },
            {
                "id": "memory_guidance",
                "layer": 5,
                "name": "Memory Context Guidance",
                "description": "Governance rules that prevent the agent from claiming to create/modify formal memories directly. Ensures the human-review pipeline.",
                "source": "smallink/agent.py :: _MEMORY_CONTEXT_GUIDANCE",
                "editable": "caution",
                "safety": "caution",
                "safety_note": "This enforces the memory governance contract (memories require user confirmation). Weakening it could let the agent claim it stored memories without going through the pipeline. Edits here should preserve the 'read-only + must-be-confirmed' invariant.",
                "text": _MEMORY_CONTEXT_GUIDANCE,
            },
            {
                "id": "plan_mode",
                "layer": 7,
                "name": "Plan Mode Context (Per-Turn)",
                "description": "Injected into the latest user message when the session is in plan mode. Blocks write/shell tools at the prompt level.",
                "source": "smallink/agent.py :: _PLAN_MODE_CONTEXT",
                "editable": "caution",
                "safety": "caution",
                "safety_note": "Plan mode is also enforced by PermissionEngine (hard block). This prompt is a soft reinforcement. Removing it won't break execution safety, but the agent may try tool calls that get rejected, wasting tokens.",
                "text": _PLAN_MODE_CONTEXT,
            },
            {
                "id": "discuss_mode",
                "layer": 7,
                "name": "Discuss Mode Context (Per-Turn)",
                "description": "Injected when discuss mode is active. Similar to plan mode but without the plan-proposal expectation.",
                "source": "smallink/agent.py :: _DISCUSS_MODE_CONTEXT",
                "editable": "caution",
                "safety": "caution",
                "safety_note": "Same as plan mode — backed by hard permission checks. The prompt is a soft guide. Safe to rephrase, but removing entirely may increase rejected tool-call attempts.",
                "text": _DISCUSS_MODE_CONTEXT,
            },
        ]

        assembly_order = [
            "Layer 1: Agent System Prompt (one of: link / code / chat / ops persona)",
            "Layer 2: Narration Guidance (appended for all agents)",
            "Layer 3: Environment Context (dynamic, generated at session start)",
            "Layer 4: AGENTS.md (project conventions file, if present in workspace root)",
            "Layer 5: Memory Context Guidance (when memory store is active)",
            "Layer 6: Skill Catalog (dynamic list of registered skills)",
            "Layer 7: Per-Turn Ephemeral Context (plan/discuss mode + roots + memory injection)",
        ]

        return {
            "layers": layers,
            "assembly_order": assembly_order,
            "assembly_source": "smallink/agent.py :: build_engine() lines 253-269",
            "notes": {
                "layer_4_agents_md": "Read from workspace root at session start. User-created file — always safe to edit.",
                "layer_6_skill_catalog": "Auto-generated from registered skills. Not editable as a prompt (add/remove skills instead).",
                "layer_7_memory_injection": "Memories selected by select_memories() and formatted by format_memories(). Content comes from the memory store, not a static prompt.",
            },
        }

    return router
