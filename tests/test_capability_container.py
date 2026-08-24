from __future__ import annotations

from smallink.agent import build_engine
from smallink.agents import chat_agent, link_agent
from smallink.agents.base import Agent
from smallink.capabilities import CapabilityContainer
from smallink.permissions import Mode, PermissionEngine
from smallink.providers.base import AssistantTurn, ModelCapabilities, ProviderClient
from smallink.secrets import SecretStore
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


def _tool_schema(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"{name} description",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _connector_tool(name: str):
    def _tool():
        return {"ok": True, "tool": name}

    _tool.__name__ = name
    _tool.__doc__ = f"{name} doc"
    _tool.__link_schema__ = _tool_schema(name)
    return _tool


def test_build_engine_filters_connector_tools_into_registry(tmp_path, monkeypatch) -> None:
    seen: dict[str, object] = {}
    github_search = _connector_tool("github_search")
    browser_read_url = _connector_tool("browser_read_url")
    github_create_issue = _connector_tool("github_create_issue")
    tool_connector = {
        "github_search": "github",
        "browser_read_url": "browser",
        "github_create_issue": "github",
    }

    def fake_enabled_connector_tools(_secrets):
        return {"github", "browser"}, {"github_search", "browser_read_url"}

    def fake_make_integration_tools(
        _secrets,
        *,
        enabled_connectors=None,
        enabled_tools=None,
        roots=None,
    ):
        seen["enabled_connectors"] = enabled_connectors
        seen["enabled_tools"] = enabled_tools
        seen["roots"] = roots
        candidates = [github_search, browser_read_url, github_create_issue]
        return [
            tool
            for tool in candidates
            if tool_connector[tool.__name__] in (enabled_connectors or set())
            and tool.__name__ in (enabled_tools or set())
        ]

    monkeypatch.setattr(
        "smallink.agent._enabled_connector_tools", fake_enabled_connector_tools
    )
    monkeypatch.setattr(
        "smallink.agent.make_integration_tools", fake_make_integration_tools
    )

    engine = build_engine(
        agent=link_agent(),
        workspace=tmp_path,
        provider=StubProvider(),
        secrets=SecretStore(tmp_path / "secrets.json"),
        connector_filter={"github"},
    )

    assert seen["enabled_connectors"] == {"github"}
    assert seen["enabled_tools"] == {"github_search", "browser_read_url"}
    assert isinstance(seen["roots"], list)

    names = set(engine.registry.names())
    schema_names = {
        schema["function"]["name"]
        for schema in engine.registry.schemas()
        if schema.get("type") == "function"
    }
    assert "github_search" in names
    assert "github_search" in schema_names
    assert "browser_read_url" not in names
    assert "browser_read_url" not in schema_names
    assert "github_create_issue" not in names
    assert "github_create_issue" not in schema_names


def test_build_engine_skips_connector_assembly_for_chat_and_non_connector_agent(
    tmp_path, monkeypatch
) -> None:
    calls: list[str] = []

    def fake_enabled_connector_tools(_secrets):
        calls.append("_enabled_connector_tools")
        return {"github"}, {"github_search"}

    def fake_make_integration_tools(
        _secrets,
        *,
        enabled_connectors=None,
        enabled_tools=None,
        roots=None,
    ):
        calls.append("make_integration_tools")
        return [_connector_tool("github_search")]

    monkeypatch.setattr(
        "smallink.agent._enabled_connector_tools", fake_enabled_connector_tools
    )
    monkeypatch.setattr(
        "smallink.agent.make_integration_tools", fake_make_integration_tools
    )

    chat_engine = build_engine(
        agent=chat_agent(),
        provider=StubProvider(),
        secrets=SecretStore(tmp_path / "chat-secrets.json"),
    )
    no_connectors_engine = build_engine(
        agent=Agent(
            name="plain",
            title="Plain",
            system_prompt="No connectors here.",
            needs_workspace=True,
            connectors=False,
            messaging=False,
            family="knowledge",
        ),
        workspace=tmp_path,
        provider=StubProvider(),
        secrets=SecretStore(tmp_path / "plain-secrets.json"),
    )

    assert "github_search" not in set(chat_engine.registry.names())
    assert "github_search" not in set(no_connectors_engine.registry.names())
    assert all(
        schema["function"]["name"] != "github_search"
        for schema in chat_engine.registry.schemas()
    )
    assert all(
        schema["function"]["name"] != "github_search"
        for schema in no_connectors_engine.registry.schemas()
    )
    assert calls == []
