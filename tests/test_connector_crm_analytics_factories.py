from __future__ import annotations

import hashlib
import inspect
import json
from typing import Any, Callable

import pytest

from smallink.connectors.tool_utils import request
from smallink.connectors.tools_domain.crm_analytics import (
    make_amplitude_tools,
    make_apollo_tools,
    make_attio_tools,
    make_close_tools,
    make_crm_analytics_tools,
    make_hubspot_tools,
    make_hunter_tools,
    make_mixpanel_tools,
    make_notion_tools,
    make_posthog_tools,
)
from smallink.secrets import SecretStore


FACTORY_TO_NAMES = (
    (
        make_hubspot_tools,
        [
            "hubspot_search",
            "hubspot_get_object",
            "hubspot_create_contact",
            "hubspot_update_object",
            "hubspot_log_note",
            "hubspot_create_task",
        ],
    ),
    (
        make_notion_tools,
        [
            "notion_search",
            "notion_read_page",
            "notion_query_database",
            "notion_create_page",
        ],
    ),
    (
        make_attio_tools,
        [
            "attio_list_objects",
            "attio_query_records",
            "attio_get_record",
            "attio_create_note",
        ],
    ),
    (make_posthog_tools, ["posthog_query", "posthog_list_insights"]),
    (make_mixpanel_tools, ["mixpanel_segmentation", "mixpanel_top_events"]),
    (
        make_amplitude_tools,
        ["amplitude_active_users", "amplitude_event_totals"],
    ),
    (
        make_apollo_tools,
        ["apollo_enrich_person", "apollo_enrich_company", "apollo_search_people"],
    ),
    (
        make_hunter_tools,
        ["hunter_domain_search", "hunter_find_email", "hunter_verify_email"],
    ),
    (
        make_close_tools,
        [
            "close_search_leads",
            "close_get_lead",
            "close_list_opportunities",
            "close_create_lead",
            "close_update_opportunity",
            "close_log_note",
        ],
    ),
)

EXPECTED_NAMES = [name for _factory, names in FACTORY_TO_NAMES for name in names]

# SHA-256 over canonical JSON pins every description, property, and required field
# from the legacy inline schema without duplicating 32 large schema literals here.
EXPECTED_SCHEMA_HASHES = {
    "hubspot_search": "c0153ac7b3599c5e9bc082e6a1411a536d7006f2274020e7511974e54a4e914d",
    "hubspot_get_object": "1be5b68871e61b8a537bce3d7160b74521500f3e51af0176dac5623551a067c3",
    "hubspot_create_contact": "99c80d986749b0a98eb611e7a2b4fcd26798ab43d1fb1305bc2287ea032f3167",
    "hubspot_update_object": "5ae87748a06e75974afd9a3ad02110c2d0b6175563588a53583dcff40e28f5c7",
    "hubspot_log_note": "804526d0edc1d07fdac82d7137765215a2dca54dba4f315081bdac6468ab102b",
    "hubspot_create_task": "329bcab45d575a79abf402e4229b3503dbc49b5ce5fb9048ac6833938e1d618f",
    "notion_search": "958ef8d6d7b79b5763583865327d14326b83cff5ae501a5adc102117e76cedeb",
    "notion_read_page": "99df927a53b9af87a294a8e0c1c7154b498dd884dc6a67498804ab7a8ebd60ab",
    "notion_query_database": "9db5af6e2f8ac2a7a984f9d48d11b80df4d9e98deb4ea337bcab97775ba81e4b",
    "notion_create_page": "11d0adc2347e619abe0695b9e9718a96b97d62710986b466179aad6e2cdd4200",
    "attio_list_objects": "c59774c11a1e7ccad08edace3572784b596ec05d104ec177bf99673c7bb1035a",
    "attio_query_records": "75cc22918918f373271a51e6838ba1f546e080dcd5dc08f7d4095e4929f23672",
    "attio_get_record": "fed7a10762d07b3537b1d7a388bd9ba367cae2bd30ae04d43097e7665fea967e",
    "attio_create_note": "f0ef24e552ea33c18e009c5be86ddf7ceb111683972c74185096d31941911f85",
    "posthog_query": "5a7b940a76145d4f53ef30655c3341ba2fb8fc1d97d8bc3d93ab49dec4172721",
    "posthog_list_insights": "c88ce5af4bb46cc6913e078cb865c1bb4f5eb62732cd5e7bcc13b8e748381805",
    "mixpanel_segmentation": "99e1b4eefc8d776fe65d3ed9d23963b3dc608e677aeea127a36bc4618270acfe",
    "mixpanel_top_events": "c6ce3e540c27280beb293e6217572f42b1f50f1a29a7e29166bad0c9942c58df",
    "amplitude_active_users": "d30d4a0efbc841f351b7387c9473980942540774650b5a88aa0be92c158b51bc",
    "amplitude_event_totals": "73806bcb9b76ea7adc59963e9030947d70c2b6b405dd677af0ed873cfed5b64f",
    "apollo_enrich_person": "db981f9799e89ca10bc78a0890b1199b934638b739edac9f7a950734ed9a18bc",
    "apollo_enrich_company": "6eb97d25715f30c57d12498ec4bd71c27a3df3ea5ae018467070f2701e5bb8fa",
    "apollo_search_people": "0e9e3774e1051fa0a0aac9c256f8751972773bfa9794e587cf5dea36eb55f8d1",
    "hunter_domain_search": "45ac2bc56c88b0a905cb9d0a1476fdfcc295d21e81abc9784544289bc6945a60",
    "hunter_find_email": "ad337aa2a629d0a566124c3ae06daff56015d69787a4e75e548a20b2b3b8b903",
    "hunter_verify_email": "7974600abaf2bdf87d0ee774919df9799ce11283cd1b7f85f24a0f752f1b528e",
    "close_search_leads": "b3157ca08ea241138053c280eaa8c724a2a8b4962e99d0c2a235074e21afe9e7",
    "close_get_lead": "0fd8c951fedb13bcdde3d387102ce98a628fb80157113a05ecd188235fad1759",
    "close_list_opportunities": "b62396c24aa893b9fad654b112c4c235dae11d7db144d83ca5e41b8c1db75860",
    "close_create_lead": "eec1b68dae879c43aabc71ee8829b23472bd3343fa22dbd442a58832b94d9076",
    "close_update_opportunity": "aea32b7cf60ce7a4cf8ad0fd0cf18e8186fe1564471d08b1961e820dccadb981",
    "close_log_note": "5b00d6beb79078e5e537698bdcc45ad53aab4c2169834669611ae1254b6e2847",
}

WRITE_TOOLS = {
    "hubspot_create_contact",
    "hubspot_update_object",
    "hubspot_log_note",
    "hubspot_create_task",
    "notion_create_page",
    "attio_create_note",
    "close_create_lead",
    "close_update_opportunity",
    "close_log_note",
}


def _connector(name: str) -> str:
    return name.split("_", 1)[0]


def _by_name(tools: list[Callable[..., Any]]) -> dict[str, Callable[..., Any]]:
    return {tool.__name__: tool for tool in tools}


def _schema_hash(tool: Callable[..., Any]) -> str:
    canonical = json.dumps(
        tool.__link_schema__, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def test_factories_preserve_signatures_names_schemas_and_metadata(tmp_path) -> None:
    secrets = SecretStore(tmp_path / "secrets.json")
    factories = (*FACTORY_TO_NAMES, (make_crm_analytics_tools, EXPECTED_NAMES))

    for factory, expected_names in factories:
        signature = inspect.signature(factory)
        assert list(signature.parameters) == ["secrets", "roots", "request_fn"]
        assert signature.parameters["roots"].kind is inspect.Parameter.KEYWORD_ONLY
        assert signature.parameters["request_fn"].kind is inspect.Parameter.KEYWORD_ONLY
        assert signature.parameters["roots"].default is None
        assert signature.parameters["request_fn"].default is request
        assert [tool.__name__ for tool in factory(secrets)] == expected_names

    tools = make_crm_analytics_tools(secrets)
    assert set(EXPECTED_SCHEMA_HASHES) == set(EXPECTED_NAMES)
    for tool in tools:
        name = tool.__name__
        tool_schema = tool.__link_schema__
        metadata = tool.__aisuite_tool_metadata__
        approval = name in WRITE_TOOLS

        assert _schema_hash(tool) == EXPECTED_SCHEMA_HASHES[name]
        assert tool_schema["type"] == "function"
        assert tool_schema["function"]["name"] == name
        assert tool.__doc__ == tool_schema["function"]["description"]
        assert metadata.name == name
        assert metadata.category == "connector"
        assert metadata.capabilities == [_connector(name), "write" if approval else "read"]
        assert metadata.requires_approval is approval
        assert metadata.risk_level == ("medium" if approval else "low")


@pytest.fixture
def connected_secrets(tmp_path) -> SecretStore:
    secrets = SecretStore(tmp_path / "secrets.json")
    profiles = {
        "hubspot": {"token": "hs-token", "account": "portal 7"},
        "notion": {"access_token": "notion-token"},
        "attio": {"access_token": "attio-token"},
        "posthog": {"api_key": "posthog-key", "project_id": "77"},
        "mixpanel": {
            "username": "mix-user",
            "secret": "mix-secret",
            "project_id": "88",
        },
        "amplitude": {"api_key": "amp-key", "secret_key": "amp-secret"},
        "apollo": {"api_key": "apollo-key"},
        "hunter": {"api_key": "hunter-key"},
        "close": {"api_key": "close-key"},
    }
    for connector, connector_profile in profiles.items():
        secrets.put(f"{connector}:default", connector_profile)
    return secrets


def test_each_connector_routes_http_through_injected_request(
    connected_secrets: SecretStore,
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_request(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        calls.append({"method": method, "url": url, **kwargs})
        return {"ok": True, "data": {"request_number": len(calls)}}

    tools = _by_name(
        make_crm_analytics_tools(
            connected_secrets, roots=["unused"], request_fn=fake_request
        )
    )

    assert tools["hubspot_search"]("acme")["portal"] == "portal 7"
    assert tools["notion_search"]("roadmap")["account"] == "default"
    assert tools["attio_list_objects"]()["account"] == "default"
    assert tools["posthog_query"]("SELECT 1")["account"] == "77"
    assert tools["mixpanel_segmentation"](
        "purchase", "2026-08-01", "2026-08-23"
    )["account"] == "88"
    assert tools["amplitude_active_users"]("2026-08-01", "2026-08-23")[
        "account"
    ] == "default"
    assert tools["apollo_enrich_person"](email="ada@example.com")["account"] == "default"
    assert tools["hunter_domain_search"]("example.com")["account"] == "default"
    assert tools["close_search_leads"]("status:potential acme")["ok"] is True

    assert len(calls) == 9
    assert [call["url"] for call in calls] == [
        "https://api.hubapi.com/crm/v3/objects/contacts/search",
        "https://api.notion.com/v1/search",
        "https://api.attio.com/v2/objects",
        "https://us.posthog.com/api/projects/77/query",
        "https://mixpanel.com/api/query/segmentation",
        "https://amplitude.com/api/2/users",
        "https://api.apollo.io/api/v1/people/match",
        "https://api.hunter.io/v2/domain-search",
        "https://api.close.com/api/v1/lead/",
    ]
    assert calls[0]["headers"]["Authorization"] == "Bearer hs-token"
    assert calls[1]["headers"]["Notion-Version"] == "2022-06-28"
    assert calls[2]["headers"]["Authorization"] == "Bearer attio-token"
    assert calls[3]["json"] == {
        "query": {"kind": "HogQLQuery", "query": "SELECT 1"}
    }
    assert calls[4]["auth"] == ("mix-user", "mix-secret")
    assert calls[5]["params"]["start"] == "20260801"
    assert calls[6]["headers"]["X-Api-Key"] == "apollo-key"
    assert calls[7]["params"]["api_key"] == "hunter-key"
    assert calls[8]["auth"] == ("close-key", "")
