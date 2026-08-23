"""Prompt contribution ordering and compatibility contracts."""

from __future__ import annotations

import pytest

from smallink.agents.chat import CHAT_INSTRUCTIONS, chat_agent
from smallink.prompts import (
    PromptContribution,
    PromptRegistry,
    _DELEGATION_GUIDANCE,
    _DISCUSS_MODE_CONTEXT,
    _MEMORY_CONTEXT_GUIDANCE,
    _NARRATION_GUIDANCE,
    _PLAN_MODE_CONTEXT,
    merge_prompt_contributions,
    session_prompt_registry,
    turn_prompt_registry,
)


class _StubProvider:
    def complete(self, **kwargs):  # pragma: no cover - build only
        raise NotImplementedError

    def capabilities(self, model):
        from smallink.providers import ModelCapabilities

        return ModelCapabilities()


def test_registry_orders_stably_and_exposes_source_and_scope():
    registry = PromptRegistry(
        [
            PromptContribution("last", "C", 20, "c.py", "session"),
            PromptContribution("first", "A", 10, "a.py", "session"),
            PromptContribution("same_order", "B", 10, "b.py", "turn"),
        ]
    )

    contributions = registry.contributions()
    assert [item.id for item in contributions] == ["first", "same_order", "last"]
    assert [(item.source, item.scope) for item in contributions] == [
        ("a.py", "session"),
        ("b.py", "turn"),
        ("c.py", "session"),
    ]
    assert registry.render() == "A\n\nB\n\nC"
    assert registry.render(scope="session") == "A\n\nC"


def test_registry_rejects_duplicate_ids():
    contribution = PromptContribution("same", "A", 10, "a.py", "session")
    with pytest.raises(ValueError, match=r"duplicate prompt id: same"):
        PromptRegistry(
            [
                contribution,
                PromptContribution("same", "B", 20, "b.py", "turn"),
            ]
        )


def test_session_and_turn_assembly_match_legacy_strings_exactly():
    session = session_prompt_registry(
        agent_id="example",
        agent_prompt="PERSONA",
        delegation=True,
        environment="ENVIRONMENT",
        agents_md="CONVENTIONS",
        memory=True,
        skill_catalog="SKILLS",
    )
    assert session.render() == "\n\n".join(
        [
            "PERSONA",
            _NARRATION_GUIDANCE,
            _DELEGATION_GUIDANCE,
            "ENVIRONMENT",
            "CONVENTIONS",
            _MEMORY_CONTEXT_GUIDANCE,
            "SKILLS",
        ]
    )
    assert [item.id for item in session.contributions()] == [
        "agent_example",
        "narration",
        "delegation",
        "environment",
        "agents_md",
        "memory_guidance",
        "skill_catalog",
    ]
    assert [(item.layer, item.scope, item.source) for item in session.contributions()] == [
        (1, "session", "agent:example"),
        (2, "session", "smallink/prompts.py :: _NARRATION_GUIDANCE"),
        (2, "session", "smallink/prompts.py :: _DELEGATION_GUIDANCE"),
        (3, "session", "smallink/environment.py :: environment_context()"),
        (4, "session", "workspace AGENTS.md"),
        (5, "session", "smallink/prompts.py :: _MEMORY_CONTEXT_GUIDANCE"),
        (6, "session", "smallink/skills :: skill_catalog_text()"),
    ]

    assert turn_prompt_registry(
        mode="plan", roots="ROOTS", memories="MEMORIES"
    ).render() == "\n\n".join([_PLAN_MODE_CONTEXT, "ROOTS", "MEMORIES"])
    assert turn_prompt_registry(mode="discuss").render() == _DISCUSS_MODE_CONTEXT


def test_merge_prompt_contributions_preserves_real_layer_order_and_dedupes():
    merged = merge_prompt_contributions(
        session_prompt_registry(
            agent_id="link",
            agent_prompt="LINK",
            delegation=True,
            environment="ENV",
            memory=True,
        ),
        session_prompt_registry(
            agent_id="code",
            agent_prompt="CODE",
            delegation=True,
            environment="ENV",
            memory=True,
        ),
        turn_prompt_registry(mode="plan"),
        turn_prompt_registry(mode="discuss"),
    )

    assert [item.id for item in merged] == [
        "agent_link",
        "agent_code",
        "narration",
        "delegation",
        "environment",
        "memory_guidance",
        "plan_mode",
        "discuss_mode",
    ]
    assert [item.layer for item in merged] == [1, 1, 2, 2, 3, 5, 7, 7]


def test_build_engine_preserves_exact_system_prompt(monkeypatch, tmp_path):
    import smallink.agent as agent_module

    monkeypatch.setattr(agent_module, "_skill_dirs", lambda *args, **kwargs: [])
    engine = agent_module.build_engine(
        agent=chat_agent(),
        provider=_StubProvider(),
        skill_state_root=tmp_path / "state",
    )

    assert engine.messages[0] == {
        "role": "system",
        "content": f"{CHAT_INSTRUCTIONS}\n\n{_NARRATION_GUIDANCE}",
    }


def test_prompts_endpoint_keeps_existing_response_shape_and_order():
    from smallink.server.routers.prompts import prompts_router

    router = prompts_router(None)
    endpoint = next(route.endpoint for route in router.routes if route.path == "/v1/prompts")
    result = endpoint()

    assert list(result) == ["layers", "assembly_order", "assembly_source", "notes"]
    assert [layer["id"] for layer in result["layers"]] == [
        "agent_link",
        "agent_code",
        "agent_chat",
        "agent_ops",
        "narration",
        "delegation",
        "environment",
        "agents_md",
        "memory_guidance",
        "skill_catalog",
        "plan_mode",
        "discuss_mode",
        "roots",
        "memories",
    ]
    assert [layer["layer"] for layer in result["layers"]] == [
        1, 1, 1, 1, 2, 2, 3, 4, 5, 6, 7, 7, 7, 7
    ]
    assert all(
        list(layer)
        == [
            "id",
            "layer",
            "name",
            "description",
            "source",
            "scope",
            "editable",
            "safety",
            "safety_note",
            "text",
        ]
        for layer in result["layers"]
    )
    assert result["layers"][4]["text"] == _NARRATION_GUIDANCE
    assert result["layers"][5]["text"] == _DELEGATION_GUIDANCE
    assert result["layers"][8]["text"] == _MEMORY_CONTEXT_GUIDANCE
    assert result["layers"][10]["text"] == _PLAN_MODE_CONTEXT
    assert result["layers"][11]["text"] == _DISCUSS_MODE_CONTEXT
    assert result["layers"][5]["scope"] == "session"
    assert result["layers"][10]["scope"] == "turn"
    assert {"agents_md", "skill_catalog", "roots", "memories"}.issubset(
        {layer["id"] for layer in result["layers"]}
    )
    assert result["assembly_source"] == (
        "smallink.prompts.session_prompt_registry + smallink.prompts.turn_prompt_registry"
    )
    assert list(result["notes"]) == [
        "layer_4_agents_md",
        "layer_6_skill_catalog",
        "layer_7_memory_injection",
    ]
