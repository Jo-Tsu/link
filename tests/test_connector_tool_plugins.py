from __future__ import annotations

from smallink.connectors.tool_plugins import (
    BUILTIN_TOOL_FACTORIES,
    build_connector_tool_plugins,
)
from smallink.secrets import SecretStore


def test_builtin_tool_plugins_have_stable_unique_ids() -> None:
    ids = [connector_id for connector_id, _factory in BUILTIN_TOOL_FACTORIES]
    assert ids == [
        "browser_automation",
        "email",
        "minem",
        "github",
        "browser",
        "gmail",
        "google_calendar",
        "outlook",
        "jira",
        "confluence",
        "zendesk",
        "linear",
        "gitlab",
        "discord",
        "stripe",
        "asana",
        "hubspot",
        "dropbox",
        "box",
        "quickbooks",
        "whatsapp",
        "notion",
        "attio",
        "posthog",
        "mixpanel",
        "amplitude",
        "apollo",
        "hunter",
        "clickup",
        "close",
        "figma",
        "google_drive",
        "docusign",
        "canva",
    ]
    assert len(ids) == len(set(ids))


def test_plugin_composition_filters_connectors_and_tools() -> None:
    tools = build_connector_tool_plugins(
        SecretStore(),
        enabled_connectors={"github"},
        enabled_tools={"github_get_issue"},
    )

    assert [tool.__name__ for tool in tools] == ["github_get_issue"]


def test_all_connector_tools_share_one_unique_composition_path(tmp_path) -> None:
    tools = build_connector_tool_plugins(SecretStore(tmp_path / "secrets.json"))
    names = [tool.__name__ for tool in tools]

    assert len(names) == 139
    assert len(names) == len(set(names))
