from __future__ import annotations

import inspect
from typing import Any, Callable

from smallink.connectors.tool_utils import request
from smallink.connectors.tools_domain.browser import make_browser_tools
from smallink.connectors.tools_domain.google_workspace import (
    make_gcal_tools,
    make_gmail_tools,
)
from smallink.connectors.tools_domain.microsoft import make_outlook_tools


class _FakeSecrets:
    def __init__(self, profiles: dict[str, dict[str, Any]] | None = None) -> None:
        self.profiles = dict(profiles or {})

    def get(self, profile: str) -> dict[str, Any] | None:
        value = self.profiles.get(profile)
        return dict(value) if value is not None else None

    def put(self, profile: str, data: dict[str, Any]) -> None:
        self.profiles[profile] = dict(data)

    def status(self) -> list[dict[str, Any]]:
        return [{"profile": key} for key in self.profiles]


def _tools_by_name(tools: list[Callable[..., Any]]) -> dict[str, Callable[..., Any]]:
    return {tool.__name__: tool for tool in tools}


def test_factory_contracts_have_stable_order_schema_metadata_and_signature() -> None:
    secrets = _FakeSecrets()
    factories = (
        (make_browser_tools, ["browser_read_url"]),
        (
            make_gmail_tools,
            ["gmail_search_messages", "gmail_get_message", "gmail_send_email"],
        ),
        (
            make_gcal_tools,
            [
                "gcal_list_events",
                "gcal_free_busy",
                "gcal_create_event",
                "gcal_update_event",
                "gcal_delete_event",
            ],
        ),
        (
            make_outlook_tools,
            [
                "outlook_search_messages",
                "outlook_send_mail",
                "outlook_list_events",
                "outlook_create_event",
                "outlook_update_event",
                "outlook_delete_event",
                "outlook_respond_event",
            ],
        ),
    )

    for factory, expected_names in factories:
        signature = inspect.signature(factory)
        assert list(signature.parameters) == ["secrets", "roots", "request_fn"]
        assert signature.parameters["roots"].kind is inspect.Parameter.KEYWORD_ONLY
        assert signature.parameters["request_fn"].kind is inspect.Parameter.KEYWORD_ONLY
        assert signature.parameters["roots"].default is None
        assert signature.parameters["request_fn"].default is request

        tools = factory(secrets)
        assert [tool.__name__ for tool in tools] == expected_names
        for tool in tools:
            tool_schema = tool.__link_schema__
            metadata = tool.__aisuite_tool_metadata__
            assert tool_schema["type"] == "function"
            assert tool_schema["function"]["name"] == tool.__name__
            assert tool_schema["function"]["parameters"]["type"] == "object"
            assert metadata.name == tool.__name__
            assert metadata.category == "connector"
            assert metadata.capabilities


def test_browser_factory_uses_injected_request_and_rejects_bad_urls() -> None:
    calls: list[dict[str, Any]] = []

    def fake_request(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        calls.append({"method": method, "url": url, **kwargs})
        return {"ok": True, "data": "<head>skip</head><p>Hello world</p>"}

    read_url = make_browser_tools(_FakeSecrets(), request_fn=fake_request)[0]
    assert read_url("file:///tmp/nope") == {
        "error": "url must start with http:// or https://"
    }
    assert calls == []

    out = read_url("https://example.test/page", max_chars=5)
    assert out == {
        "url": "https://example.test/page",
        "text": "Hello",
        "truncated": True,
    }
    assert calls == [
        {
            "method": "GET",
            "url": "https://example.test/page",
            "headers": {"User-Agent": "link/0.1 (+connector)"},
        }
    ]


def test_gmail_factory_injects_filter_requests_and_preserves_account_errors() -> None:
    secrets = _FakeSecrets(
        {
            "gmail:default": {
                "type": "oauth",
                "enabled": True,
                "default_account": "me@example.com",
                "filters": {"labels": ["Private"]},
            },
            "gmail:account:me@example.com": {
                "access_token": "gmail-token",
                "account": "me@example.com",
            },
        }
    )
    calls: list[dict[str, Any]] = []

    def fake_request(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        calls.append({"method": method, "url": url, **kwargs})
        if url.endswith("/labels"):
            return {
                "ok": True,
                "data": {"labels": [{"id": "Label_7", "name": "Private"}]},
            }
        if url.endswith("/messages/m1"):
            return {
                "ok": True,
                "data": {
                    "id": "m1",
                    "labelIds": ["Label_7"],
                    "payload": {"headers": []},
                },
            }
        if url.endswith("/messages"):
            return {
                "ok": True,
                "data": {"messages": [{"id": "m1"}], "resultSizeEstimate": 1},
            }
        raise AssertionError(f"unexpected request: {method} {url}")

    search = _tools_by_name(
        make_gmail_tools(secrets, request_fn=fake_request)
    )["gmail_search_messages"]
    out = search("newer:1d", max_results=99)
    assert out["ok"] is True
    assert out["account"] == "me@example.com"
    assert out["data"]["messages"] == []
    assert out["data"]["resultSizeEstimate"] == 0
    assert out["_display"] == {
        "hidden_by_filters": 1,
        "connector": "gmail",
    }
    assert [call["url"].rsplit("/", 1)[-1] for call in calls] == [
        "messages",
        "labels",
        "m1",
    ]
    assert calls[0]["params"] == {"q": "newer:1d", "maxResults": 20}
    assert all(
        call["headers"]["Authorization"] == "Bearer gmail-token"
        for call in calls
    )

    before = len(calls)
    assert search("x", account="missing@example.com") == {
        "error": "no gmail account matching 'missing@example.com'"
    }
    assert len(calls) == before


def test_gcal_factory_uses_injected_request_and_keeps_empty_update_error() -> None:
    secrets = _FakeSecrets(
        {
            "google_calendar:default": {
                "type": "oauth",
                "enabled": True,
                "default_account": "me@example.com",
            },
            "google_calendar:account:me@example.com": {
                "access_token": "calendar-token",
                "account": "me@example.com",
            },
        }
    )
    calls: list[dict[str, Any]] = []

    def fake_request(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        calls.append({"method": method, "url": url, **kwargs})
        return {"ok": True, "data": {"items": []}}

    tools = _tools_by_name(make_gcal_tools(secrets, request_fn=fake_request))
    out = tools["gcal_list_events"](calendar_id="team@example.com", max_results=99)
    assert out == {"ok": True, "data": {"items": []}, "account": "me@example.com"}
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/calendars/team@example.com/events")
    assert calls[0]["headers"]["Authorization"] == "Bearer calendar-token"
    assert calls[0]["params"] == {
        "singleEvents": True,
        "orderBy": "startTime",
        "maxResults": 20,
    }

    before = len(calls)
    assert tools["gcal_update_event"]("event-1") == {
        "error": "nothing to update — pass summary, description, start, or end"
    }
    assert len(calls) == before


def test_outlook_factory_uses_injected_request_and_validates_responses() -> None:
    secrets = _FakeSecrets(
        {
            "outlook:default": {
                "type": "oauth",
                "enabled": True,
                "default_account": "ops@example.com",
            },
            "outlook:account:ops@example.com": {
                "access_token": "graph-token",
                "account": "ops@example.com",
            },
        }
    )
    calls: list[dict[str, Any]] = []

    def fake_request(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        calls.append({"method": method, "url": url, **kwargs})
        return {"ok": True, "data": {"value": []}}

    tools = _tools_by_name(make_outlook_tools(secrets, request_fn=fake_request))
    out = tools["outlook_search_messages"]("quarterly plan", max_results=99)
    assert out == {
        "account": "ops@example.com",
        "ok": True,
        "data": {"value": []},
    }
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "https://graph.microsoft.com/v1.0/me/messages"
    assert calls[0]["headers"]["Authorization"] == "Bearer graph-token"
    assert calls[0]["params"] == {"$top": 20, "$search": '"quarterly plan"'}

    before = len(calls)
    assert tools["outlook_respond_event"]("event-1", "maybe") == {
        "error": "response must be one of: accept, decline, tentative"
    }
    assert len(calls) == before
