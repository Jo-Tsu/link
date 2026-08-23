from __future__ import annotations

from smallink.agent import build_engine
from smallink.agents import chat_agent
from smallink.capabilities import CapabilityContainer
from smallink.permissions import Mode, PermissionEngine
from smallink.providers.base import AssistantTurn, ModelCapabilities, ProviderClient
from smallink.tools import ToolRegistry


class StubProvider(ProviderClient):
    def complete(self, **kwargs):
        return AssistantTurn(text="done")

    def capabilities(self, model: str):
        return ModelCapabilities()


def test_build_engine_consumes_container_tools_and_permissions(tmp_path) -> None:
    provider = StubProvider()
    tools = ToolRegistry()
    permissions = PermissionEngine(workspace_root=tmp_path, mode=Mode.DISCUSS)
    container = CapabilityContainer(
        provider=provider,
        tools=tools,
        permissions=permissions,
    )

    engine = build_engine(agent=chat_agent(), capabilities=container)

    assert engine.provider is provider
    assert engine.registry is tools
    assert engine.permissions is permissions


def test_explicit_legacy_arguments_override_container(tmp_path) -> None:
    container_provider = StubProvider()
    explicit_provider = StubProvider()
    container = CapabilityContainer(provider=container_provider)

    engine = build_engine(
        agent=chat_agent(),
        capabilities=container,
        provider=explicit_provider,
    )

    assert engine.provider is explicit_provider
