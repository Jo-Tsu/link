from __future__ import annotations

import inspect

from smallink.connectors.tool_defs import connector_for_tool
from smallink.connectors.tools_domain.registry import MIGRATED_TOOL_FACTORIES
from smallink.secrets import SecretStore


EXPECTED_CONNECTORS = (
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
)


def test_migrated_factory_registry_is_explicit_unique_and_uniform() -> None:
    connector_ids = tuple(connector_id for connector_id, _ in MIGRATED_TOOL_FACTORIES)
    assert connector_ids == EXPECTED_CONNECTORS
    assert len(connector_ids) == len(set(connector_ids))

    for _connector_id, factory in MIGRATED_TOOL_FACTORIES:
        parameters = inspect.signature(factory).parameters
        assert tuple(parameters) == ("secrets", "roots", "request_fn")
        assert parameters["roots"].kind is inspect.Parameter.KEYWORD_ONLY
        assert parameters["roots"].default is None
        assert parameters["request_fn"].kind is inspect.Parameter.KEYWORD_ONLY


def test_migrated_factories_own_unique_tools_with_matching_connector_ids(
    tmp_path,
) -> None:
    secrets = SecretStore(tmp_path / "secrets.json")
    names: list[str] = []

    for connector_id, factory in MIGRATED_TOOL_FACTORIES:
        tools = factory(secrets)
        assert tools, connector_id
        assert all(connector_for_tool(tool.__name__) == connector_id for tool in tools)
        names.extend(tool.__name__ for tool in tools)

    assert len(names) == 110
    assert len(names) == len(set(names))
