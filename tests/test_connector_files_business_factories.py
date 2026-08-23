from __future__ import annotations

from typing import Any

import pytest

from smallink.connectors import accounts
from smallink.connectors.tools_domain.files_business import (
    make_box_tools,
    make_drive_tools,
    make_dropbox_tools,
    make_files_business_tools,
    make_quickbooks_tools,
    make_whatsapp_tools,
)
from smallink.secrets import SecretStore


EXPECTED_TOOLS = [
    ("dropbox_search", ["query"], ["dropbox", "read"], False),
    ("dropbox_list_folder", [], ["dropbox", "read"], False),
    ("dropbox_read_file", ["path"], ["dropbox", "read"], False),
    ("box_search", ["query"], ["box", "read"], False),
    ("box_list_folder", [], ["box", "read"], False),
    ("box_read_file", ["file_id"], ["box", "read"], False),
    ("quickbooks_query", ["query"], ["quickbooks", "read"], False),
    ("quickbooks_list_customers", [], ["quickbooks", "read"], False),
    ("quickbooks_list_invoices", [], ["quickbooks", "read"], False),
    ("quickbooks_get_report", ["report"], ["quickbooks", "read"], False),
    ("whatsapp_send_message", ["to", "text"], ["whatsapp", "write"], True),
    ("whatsapp_send_template", ["to", "template_name"], ["whatsapp", "write"], True),
    ("drive_search_files", ["query"], ["google_drive", "read"], False),
    ("drive_list_folder", [], ["google_drive", "read"], False),
    ("drive_read_file", ["file_id"], ["google_drive", "read"], False),
]


@pytest.fixture
def secrets(tmp_path) -> SecretStore:
    store = SecretStore(tmp_path / "secrets.json")
    store.put("dropbox:default", {"access_token": "dropbox-token"})
    store.put("box:default", {"access_token": "box-token"})
    store.put(
        "quickbooks:default",
        {
            "access_token": "quickbooks-token",
            "realm_id": "realm-7",
            "environment": "sandbox",
        },
    )
    store.put(
        "whatsapp:default",
        {"access_token": "whatsapp-token", "phone_number_id": "phone-9"},
    )
    accounts.add_account(
        store,
        "google_drive",
        "work@example.com",
        {"access_token": "drive-token", "account": "work@example.com"},
    )
    return store


def _by_name(tools):
    return {tool.__name__: tool for tool in tools}


def test_composite_factory_preserves_names_schemas_and_metadata(secrets) -> None:
    tools = make_files_business_tools(secrets, roots=["unused"], request_fn=lambda *a, **k: {})

    assert [tool.__name__ for tool in tools] == [row[0] for row in EXPECTED_TOOLS]
    for tool, (name, required, capabilities, approval) in zip(tools, EXPECTED_TOOLS):
        tool_schema = tool.__link_schema__
        metadata = tool.__aisuite_tool_metadata__
        assert tool_schema["type"] == "function"
        assert tool_schema["function"]["name"] == name
        assert tool_schema["function"]["parameters"]["required"] == required
        assert tool.__doc__ == tool_schema["function"]["description"]
        assert metadata.name == name
        assert metadata.category == "connector"
        assert metadata.capabilities == capabilities
        assert metadata.requires_approval is approval
        assert metadata.risk_level == ("medium" if approval else "low")


def test_named_factories_preserve_each_connector_order(secrets) -> None:
    factories = [
        make_dropbox_tools,
        make_box_tools,
        make_quickbooks_tools,
        make_whatsapp_tools,
        make_drive_tools,
    ]
    expected = [
        [row[0] for row in EXPECTED_TOOLS[0:3]],
        [row[0] for row in EXPECTED_TOOLS[3:6]],
        [row[0] for row in EXPECTED_TOOLS[6:10]],
        [row[0] for row in EXPECTED_TOOLS[10:12]],
        [row[0] for row in EXPECTED_TOOLS[12:15]],
    ]

    assert [
        [tool.__name__ for tool in factory(secrets, roots=[], request_fn=lambda *a, **k: {})]
        for factory in factories
    ] == expected


def test_dropbox_fake_request_covers_path_clamp_and_text_read(secrets) -> None:
    calls: list[dict[str, Any]] = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if url.endswith("/download"):
            return {"ok": True, "data": "abcdef"}
        return {"ok": True, "data": {}}

    tools = _by_name(make_dropbox_tools(secrets, request_fn=fake_request))
    tools["dropbox_search"]("plan", max_results=99)
    tools["dropbox_list_folder"](" Team ")
    out = tools["dropbox_read_file"]("notes.txt", max_chars=3)

    assert calls[0]["json"] == {"query": "plan", "options": {"max_results": 20}}
    assert calls[1]["json"] == {"path": "/Team"}
    assert calls[2]["headers"]["Dropbox-API-Arg"] == '{"path": "/notes.txt"}'
    assert out == {"path": "notes.txt", "text": "abc", "truncated": True}


def test_box_fake_request_covers_search_and_text_read(secrets) -> None:
    calls: list[dict[str, Any]] = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if url.endswith("/content"):
            return {"ok": True, "data": {"value": 1}}
        return {"ok": True, "data": {}}

    tools = _by_name(make_box_tools(secrets, request_fn=fake_request))
    tools["box_search"]("roadmap", max_results=0)
    tools["box_list_folder"]("42")
    out = tools["box_read_file"]("7", max_chars=5)

    assert calls[0]["method"] == "GET"
    assert calls[0]["params"] == {"query": "roadmap", "limit": 10}
    assert calls[1]["url"].endswith("/folders/42/items")
    assert out == {"file_id": "7", "text": "{'val", "truncated": True}


def test_quickbooks_fake_request_covers_sandbox_query_and_report(secrets) -> None:
    calls: list[dict[str, Any]] = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return {"ok": True, "data": {}}

    tools = _by_name(make_quickbooks_tools(secrets, request_fn=fake_request))
    tools["quickbooks_query"](" SELECT * FROM Invoice ", max_results=500)
    tools["quickbooks_list_customers"](2)
    tools["quickbooks_list_invoices"](3)
    tools["quickbooks_get_report"]("Profit/Loss", start_date="2026-01-01")

    assert all(
        call["url"].startswith("https://sandbox-quickbooks.api.intuit.com/v3/company/realm-7/")
        for call in calls
    )
    assert calls[0]["params"] == {"query": "SELECT * FROM Invoice MAXRESULTS 100"}
    assert calls[1]["params"] == {"query": "SELECT * FROM Customer MAXRESULTS 2"}
    assert calls[2]["params"] == {
        "query": "SELECT * FROM Invoice ORDERBY TxnDate DESC MAXRESULTS 3"
    }
    assert calls[3]["url"].endswith("/reports/Profit%2FLoss")
    assert calls[3]["params"] == {"start_date": "2026-01-01"}


def test_whatsapp_fake_request_covers_text_and_template_payloads(secrets) -> None:
    calls: list[dict[str, Any]] = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return {"ok": True, "data": {"id": "message-1"}}

    tools = _by_name(make_whatsapp_tools(secrets, request_fn=fake_request))
    tools["whatsapp_send_message"]("15550001111", "x" * 4100)
    tools["whatsapp_send_template"]("15550002222", "welcome", "zh_CN")

    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith("/phone-9/messages")
    assert len(calls[0]["json"]["text"]["body"]) == 4096
    assert calls[1]["json"] == {
        "messaging_product": "whatsapp",
        "to": "15550002222",
        "type": "template",
        "template": {"name": "welcome", "language": {"code": "zh_CN"}},
    }


def test_drive_fake_request_covers_account_query_and_native_type_error(secrets) -> None:
    calls: list[dict[str, Any]] = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if "/files/" in url:
            return {
                "ok": True,
                "data": {
                    "id": "drawing-1",
                    "name": "Sketch",
                    "mimeType": "application/vnd.google-apps.drawing",
                },
            }
        return {"ok": True, "data": {"files": []}}

    tools = _by_name(make_drive_tools(secrets, request_fn=fake_request))
    search = tools["drive_search_files"]("CEO's \\ plan", max_results=99)
    listing = tools["drive_list_folder"]("team's", max_results=99)
    refused = tools["drive_read_file"]("drawing-1")

    assert search["account"] == "work@example.com"
    assert calls[0]["params"]["q"] == (
        "(name contains 'CEO\\'s \\\\ plan' or fullText contains "
        "'CEO\\'s \\\\ plan') and trashed=false"
    )
    assert calls[0]["params"]["pageSize"] == 20
    assert listing["account"] == "work@example.com"
    assert calls[1]["params"]["q"] == "'team\\'s' in parents and trashed=false"
    assert calls[1]["params"]["pageSize"] == 50
    assert refused == {
        "account": "work@example.com",
        "error": "cannot read application/vnd.google-apps.drawing as text",
        "file": {
            "id": "drawing-1",
            "name": "Sketch",
            "mimeType": "application/vnd.google-apps.drawing",
        },
    }
    assert len(calls) == 3


def test_drive_read_file_exports_google_doc_and_propagates_metadata_error(secrets) -> None:
    responses = iter(
        [
            {
                "ok": True,
                "data": {
                    "id": "doc-1",
                    "name": "Plan",
                    "mimeType": "application/vnd.google-apps.document",
                },
            },
            {"ok": True, "data": "document body"},
            {"error": "HTTP 404", "details": "missing"},
        ]
    )
    calls: list[dict[str, Any]] = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return next(responses)

    read = _by_name(make_drive_tools(secrets, request_fn=fake_request))["drive_read_file"]
    exported = read("doc-1", max_chars=8)
    failed = read("missing")

    assert calls[1]["url"].endswith("/files/doc-1/export")
    assert calls[1]["params"] == {"mimeType": "text/plain"}
    assert exported["content"] == "document"
    assert exported["truncated"] is True
    assert failed == {
        "account": "work@example.com",
        "error": "HTTP 404",
        "details": "missing",
    }
