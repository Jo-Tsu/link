"""Engine assembly from an Agent (Code / Chat / …).

Wires the agent's base tools + permissions + AGENTS.md (workspace agents) + memory +
the skill catalog (progressive disclosure) + load_skill into a TurnEngine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .agents import Agent, AgentContext, code_agent
from .automation import scheduling_tools
from .selfwake import selfwake_tools
from .subscriptions import subscription_tools
from .config import load_config
from .connectors import (
    connector_list,
    load_settings,
    make_integration_tools,
    make_send_file_tool,
    make_send_message_tool,
)
from .engine import Approver, TurnEngine
from .environment import environment_context
from .memory import (
    MemoryStore,
    Scope,
    format_memories,
    query_text,
    select_memories,
)
from .permissions import Mode, PermissionEngine
from .project import load_agents_md
from .roots import RootDir, normalize_roots, render_context
from .providers import ProviderClient, ProviderRouter
from .overrides import RiskOverrideStore
from .secrets import SecretStore, state_dir
from .skills import (
    SkillLoader,
    SkillSource,
    SkillStore,
    default_skill_sources,
    skill_catalog_text,
    skill_tools,
)
from .tools import ToolRegistry
from .tools.ask import ask_user_tool
from .tools.directories import request_directory_tool
from .tools.delegation import delegation_tools
from .tools.plan import propose_plan_tool
from .tools.subagent import explorer_tools
from .web import make_web_fetch_tool, make_web_search_tool
from .workspace_trust import WorkspaceTrustStore
from .tools.shell import LocalExecutor
from .tools.todo import TodoList
from .capabilities import CapabilityContainer

# Appended each turn while discuss mode is active: enforcement-only read-only, with no
# pressure toward a plan proposal (that's what distinguishes it from plan mode).
_DISCUSS_MODE_CONTEXT = """\
Discuss mode is active: write and shell tools are disabled. Explore and answer freely; if
the user asks for a change, describe it in chat instead of attempting it (they can switch
to plan or approval mode to have you make it)."""

# Appended to the latest user message every turn while plan mode is active. The mode can
# flip mid-session (plan approval), so this can't live in the static instructions.
_PLAN_MODE_CONTEXT = """\
Plan mode is active: write and shell tools are blocked. Explore read-only and design an
approach. When you've committed to one, present it with `propose_plan` (what you'll change,
in which files, how you'll verify) — don't describe edits as if you were making them. If
the plan is approved, this same session switches to execution and you implement it; if
rejected, revise the plan using the feedback."""

# Formal Smallink memory can only be created by the governance pipeline. Existing records may be
# supplied as read-only context while the candidate-review-storage flow is introduced.
_MEMORY_CONTEXT_GUIDANCE = """\
Memory context:
- The known memories below are read-only context. Do not claim to create, update, or delete \
formal memories from this session.
- New durable facts must be proposed through Smallink data governance, traced to source records, \
and confirmed by the user before they enter the formal memory store.
- If a memory names a file, flag, or URL, verify it still exists before relying on it."""

# UX-015 (§33): the GUI interleaves these status lines with humanized tool rows inside a
# collapsed "turn" — they're what the user reads while the agent works. Universal (appended
# for every persona); models that ignore it degrade gracefully to a turn with no narration.
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


def _enabled_connector_tools(secrets: SecretStore) -> tuple[set[str], set[str]]:
    connectors = {c["name"]: c for c in connector_list(secrets)}
    enabled_connectors = {
        name
        for name, c in connectors.items()
        if c.get("connected") and c.get("enabled")
    }
    enabled_tools = {
        tool["name"]
        for c in connectors.values()
        if c.get("name") in enabled_connectors
        for tool in c.get("tools", [])
        if tool.get("enabled")
    }
    return enabled_connectors, enabled_tools


def _skill_dirs(
    workspace: Optional[Path], state_root: Optional[str | Path] = None
) -> list[SkillSource]:
    return default_skill_sources(workspace, state_root=state_root or state_dir())


def build_engine(
    *,
    agent: Agent,
    workspace: Optional[str | Path] = None,
    model: str = "gpt-5.6-sol",
    mode: Mode = Mode.INTERACTIVE,
    approver: Optional[Approver] = None,
    provider: Optional[ProviderClient] = None,
    allowed_commands: Optional[list[str]] = None,
    max_iterations: Optional[int] = None,
    model_settings: Optional[dict[str, Any]] = None,
    memory_store: Optional[MemoryStore] = None,
    governance_store: Optional[Any] = None,
    messages: Optional[list[dict[str, Any]]] = None,
    extra_tools: Optional[list[Any]] = None,
    secrets: Optional[SecretStore] = None,
    task_store: Optional[Any] = None,
    wake_store: Optional[Any] = None,
    session_id: Optional[str] = None,
    audit_sink: Optional[Any] = None,
    roots: Optional[list] = None,
    directory_requester: Optional[Any] = None,
    plan_approver: Optional[Any] = None,
    question_asker: Optional[Any] = None,
    subscription_store: Optional[Any] = None,
    channel_buffer: Optional[Any] = None,
    routing_targets: Optional[list[str]] = None,
    connector_filter: Optional[set[str]] = None,
    subagent_observer: Optional[Any] = None,
    subagent_read_tools: Optional[list[Any]] = None,
    skill_state_root: Optional[str | Path] = None,
    capabilities: Optional[CapabilityContainer] = None,
) -> TurnEngine:
    # CapabilityContainer overrides — forward-compatible entry point for callers that
    # assemble capabilities before calling build_engine. Falls back to explicit kwargs.
    if capabilities is not None:
        provider = provider or capabilities.provider  # type: ignore[assignment]
        memory_store = memory_store or capabilities.memory  # type: ignore[assignment]

    ws = Path(workspace).expanduser().resolve() if workspace else None
    if agent.needs_workspace and ws is None:
        raise ValueError(f"agent '{agent.name}' requires a workspace")

    # The session's directories. Explicit `roots` (orphan Smallink: scratch + added folders) wins;
    # otherwise the single workspace is the sole writable root. One shared, mutable list flows to
    # the file tools, the permission engine, and the context injector so add/remove is seen by all.
    if roots:
        root_list: list[RootDir] = normalize_roots(roots)
    elif ws is not None:
        root_list = [RootDir(path=ws, writable=True)]
    else:
        root_list = []

    workspace_trusted = bool(ws and WorkspaceTrustStore().is_trusted(ws))
    config = load_config(ws, workspace_trusted=workspace_trusted)
    executor = (
        LocalExecutor(cwd=ws) if (agent.needs_workspace and ws is not None) else None
    )
    todo = TodoList()
    context = AgentContext(
        workspace=ws, executor=executor, todo=todo, roots=root_list or None
    )

    registry = ToolRegistry()
    registry.register_all(agent.build_tools(context))
    # MCP / connector tools (supplied by the manager) carry their own metadata + schema.
    if extra_tools:
        registry.register_all(extra_tools)
    # Messaging-enabled Smallink roles expose send_message as an explicit capability.
    secrets = secrets or SecretStore()
    if agent.messaging and any(s.enabled for s in load_settings(secrets).values()):
        registry.register(make_send_message_tool(secrets))
        # send_file (§34): hand deliverables into the chat — same targets, but its OWN
        # approval surface (a thread's standing send_message grant never covers uploads).
        registry.register(
            make_send_file_tool(secrets, workspace=ws, roots=root_list or None)
        )
        # Channel subscriptions (inbound): listen to a channel, catch up, (un)subscribe. The agent
        # obtains a channel via ask_user or from a channel message it's reacting to.
        if subscription_store is not None and channel_buffer is not None and session_id:
            registry.register_all(
                subscription_tools(
                    subscription_store,
                    session_id,
                    channel_buffer,
                    routing_targets=routing_targets,
                )
            )
    # Knowledge surfaces with a multi-root workspace can ask the user mid-task for another folder.
    if agent.family == "knowledge" and root_list:
        registry.register(request_directory_tool())
    if agent.connectors:
        enabled_connectors, enabled_tools = _enabled_connector_tools(secrets)
        # Per-session connection hierarchy (UI-REFRESH §4.3): when the caller supplies the session's
        # effective connector set, intersect it so only effective-enabled connectors expose tools.
        # Default None preserves CLI / direct callers (no per-session restriction).
        if connector_filter is not None:
            enabled_connectors = enabled_connectors & connector_filter
        registry.register_all(
            make_integration_tools(
                secrets,
                enabled_connectors=enabled_connectors,
                enabled_tools=enabled_tools,
                roots=root_list or None,
            )
        )
    # Web search + fetch: research tools for every agent (keyless DuckDuckGo default). Reuse the
    # same callables in specialist children so provider/config resolution stays consistent.
    web_search_tool = make_web_search_tool(secrets)
    web_fetch_tool = make_web_fetch_tool()
    registry.register(web_search_tool)
    registry.register(web_fetch_tool)
    # ask_user: the universal human-in-the-loop Q&A primitive (every agent; engine-intercepted).
    if question_asker is not None:
        registry.register(ask_user_tool())
    # Route by the model's `provider:` prefix (OpenAI default, Ollama, …). The manager normally
    # passes its shared router; this fallback covers the TUI / direct build_engine() callers.
    # Resolved here (not at engine construction) because the explorer subagent captures it.
    provider = provider or ProviderRouter(secrets, default_provider="openai")
    # Code-family personas can fan broad research out to read-only explorer subagents, keeping
    # their own context for the actual change.
    if agent.family == "code" and ws is not None:
        registry.register_all(
            explorer_tools(
                workspace=ws,
                provider=provider,
                model=model,
                model_settings=model_settings,
                run_observer=subagent_observer,
            )
        )
    # Workspace-backed agents may delegate bounded read-only research, analysis, and review.
    # Children receive only file/search, web, and explicitly supplied retrieval tools; connector,
    # shell, write, scheduling, and recursive delegation capabilities never cross this boundary.
    delegation_enabled = agent.family in {"code", "knowledge"} and ws is not None
    if delegation_enabled:
        registry.register_all(
            delegation_tools(
                workspace=ws,
                provider=provider,
                model=model,
                read_tools=[
                    web_search_tool,
                    web_fetch_tool,
                    *(subagent_read_tools or []),
                ],
                model_settings=model_settings,
                run_observer=subagent_observer,
            )
        )
    # Scheduling: knowledge surfaces with a workspace can set up scheduled tasks (origin = this
    # session). Code stays out (it fans out to explorers instead).
    if task_store is not None and ws is not None and agent.family == "knowledge":
        origin = {
            "surface": agent.name,
            "session_id": session_id or "",
            "workspace": str(ws),
            "agent": agent.name,
        }
        registry.register_all(
            scheduling_tools(task_store, origin=origin, default_workspace=str(ws))
        )
    # Self-wake: knowledge surfaces can suspend + schedule their own resumption (timer /
    # on-completion / on-event). The scheduler tick resumes due wakes.
    if wake_store is not None and session_id and agent.family == "knowledge":
        registry.register_all(selfwake_tools(wake_store, session_id))

    instructions = f"{agent.system_prompt}\n\n{_NARRATION_GUIDANCE}"
    if delegation_enabled:
        instructions = f"{instructions}\n\n{_DELEGATION_GUIDANCE}"
    if ws is not None:
        instructions = f"{instructions}\n\n{environment_context(ws)}"
        conventions = load_agents_md(ws)
        if conventions:
            instructions = f"{instructions}\n\n{conventions}"

    if memory_store is not None:
        instructions = f"{instructions}\n\n{_MEMORY_CONTEXT_GUIDANCE}"

    resolved_skill_root = Path(skill_state_root or state_dir()).expanduser()
    skill_loader = SkillLoader(_skill_dirs(ws, resolved_skill_root))
    skill_store = SkillStore(resolved_skill_root, workspace=ws)
    registry.register_all(skill_tools(skill_loader, skill_store))
    catalog = skill_catalog_text(skill_loader)
    if catalog:
        instructions = f"{instructions}\n\n{catalog}"

    # User-local risk overrides (mainly to relax MCP's conservative default). Empty store →
    # no-op; never written by persona loading (the no-self-grant rule).
    risk_overrides = RiskOverrideStore(state_dir() / "risk_overrides.json").resolver()
    permissions = PermissionEngine(
        workspace_root=ws or (root_list[0].path if root_list else Path.cwd()),
        mode=mode,
        # `[]` is an explicit deny-by-default override, not a request to fall back to config.
        allowed_commands=(
            allowed_commands if allowed_commands is not None else config.allowed_commands
        ),
        auto_allow_tools=set(config.auto_allow),
        roots=root_list or None,
        risk_overrides=risk_overrides,
    )
    # The plan-mode exit door. Always registered (surfaces can flip a live session into
    # plan mode via set_mode, and the registry is fixed at build); the engine rejects the
    # call whenever the session isn't actually in plan mode.
    registry.register(propose_plan_tool())

    # Per-turn ephemeral context, appended to the latest user message since mid-thread system
    # messages aren't reliable across providers. Two producers: the plan-mode reminder (mode can
    # flip mid-session, so it's checked each turn, not baked into the instructions) and the live
    # directory list (project-space roles can gain folders mid-session).
    roots_context = (
        (lambda: render_context(root_list))
        if root_list and agent.family == "knowledge"
        else None
    )

    _cited_memories: list[dict[str, Any]] = []

    def context_provider(
        current_messages: Optional[list[dict[str, Any]]] = None,
    ) -> str:
        _cited_memories.clear()
        parts = []
        if permissions.mode is Mode.PLAN:
            parts.append(_PLAN_MODE_CONTEXT)
        elif permissions.mode is Mode.DISCUSS:
            parts.append(_DISCUSS_MODE_CONTEXT)
        if roots_context is not None:
            ctx = roots_context()
            if ctx:
                parts.append(ctx)
        if memory_store is not None:
            remembered = memory_store.list(scope=Scope.GLOBAL)
            if ws is not None:
                remembered += memory_store.list(
                    scope=Scope.WORKSPACE,
                    workspace=str(ws),
                )
            if session_id:
                remembered += memory_store.list(
                    scope=Scope.SESSION,
                    session_id=session_id,
                )
            selected = select_memories(
                remembered,
                query_text(current_messages or messages or []),
            )
            block = format_memories(selected)
            if block:
                parts.append(block)
                for memory in selected:
                    _cited_memories.append({
                        "memory_id": memory.id,
                        "content": memory.content[:120],
                        "key": memory.key,
                        "scope": memory.scope.value if hasattr(memory.scope, "value") else str(memory.scope),
                    })
                if governance_store is not None:
                    for memory in selected:
                        governance_store.record_usage(
                            memory.id,
                            session_id=session_id,
                            workspace=str(ws) if ws else None,
                        )
        return "\n\n".join(parts)

    engine = TurnEngine(
        provider=provider,
        registry=registry,
        permissions=permissions,
        model=model,
        instructions=instructions,
        approver=approver,
        # Stop kills the in-flight foreground shell command, not just the loop.
        interrupt_hooks=[executor.interrupt_now] if executor is not None else None,
        max_iterations=(
            max_iterations if max_iterations is not None else config.max_iterations
        ),
        model_settings=model_settings,
        messages=messages,
        audit_sink=audit_sink,
        context_provider=context_provider,
        directory_requester=directory_requester,
        plan_approver=plan_approver,
        question_asker=question_asker,
    )
    engine.executor = executor  # type: ignore[attr-defined]
    engine.todo = todo  # type: ignore[attr-defined]
    engine.agent_name = agent.name  # type: ignore[attr-defined]
    engine.roots = root_list  # type: ignore[attr-defined]  # shared list; Slice C mutates in place
    engine.cited_memories = _cited_memories  # type: ignore[attr-defined]
    engine.audit_context = {
        "session_id": session_id or "",
        "agent": agent.name,
        "workspace": str(ws) if ws else "",
    }
    engine.skill_loader = skill_loader  # type: ignore[attr-defined]
    return engine


def build_code_engine(**kwargs: Any) -> TurnEngine:
    """Back-compat shim: build the Code agent's engine."""
    return build_engine(agent=code_agent(), **kwargs)
