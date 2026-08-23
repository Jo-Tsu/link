from __future__ import annotations

import inspect
from typing import Any, Callable

from smallink.connectors.tools_domain.design_commerce import (
    make_canva_tools,
    make_design_commerce_tools,
    make_discord_tools,
    make_docusign_tools,
    make_figma_tools,
    make_stripe_tools,
    make_zendesk_tools,
)


class FakeSecrets:
    def __init__(self, profiles: dict[str, dict[str, Any]]) -> None:
        self.profiles = profiles
        self.puts: list[tuple[str, dict[str, Any]]] = []

    def get(self, key: str) -> dict[str, Any] | None:
        value = self.profiles.get(key)
        return dict(value) if value is not None else None

    def put(self, key: str, value: dict[str, Any]) -> None:
        stored = dict(value)
        self.profiles[key] = stored
        self.puts.append((key, stored))


class FakeRequest:
    def __init__(
        self, handler: Callable[[str, str, dict[str, Any]], dict[str, Any]] | None = None
    ) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.handler = handler

    def __call__(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((method, url, kwargs))
        if self.handler is not None:
            return self.handler(method, url, kwargs)
        return {"ok": True, "data": {"url": url}}


def _by_name(tools: list[Callable[..., Any]]) -> dict[str, Callable[..., Any]]:
    return {tool.__name__: tool for tool in tools}


EXPECTED_SURFACES = [
    (
        "zendesk_search",
        "Search Zendesk tickets/users/articles.",
        {"query": {"type": "string"}},
        ["query"],
        ["zendesk", "read"],
        False,
    ),
    (
        "zendesk_get_ticket",
        "Read a Zendesk ticket.",
        {"ticket_id": {"type": "integer"}},
        ["ticket_id"],
        ["zendesk", "read"],
        False,
    ),
    (
        "zendesk_create_ticket",
        "Create a Zendesk ticket. Requires user approval.",
        {
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "requester_email": {"type": "string"},
        },
        ["subject", "body"],
        ["zendesk", "write"],
        True,
    ),
    (
        "discord_list_channels",
        "List channels in a Discord server (guild).",
        {"guild_id": {"type": "string"}},
        ["guild_id"],
        ["discord", "read"],
        False,
    ),
    (
        "discord_read_messages",
        "Read recent messages from a Discord channel.",
        {
            "channel_id": {"type": "string"},
            "max_results": {"type": "integer"},
        },
        ["channel_id"],
        ["discord", "read"],
        False,
    ),
    (
        "discord_send_message",
        "Send a message to a Discord channel. Requires user approval.",
        {
            "channel_id": {"type": "string"},
            "content": {"type": "string"},
        },
        ["channel_id", "content"],
        ["discord", "write"],
        True,
    ),
    (
        "stripe_search_customers",
        "Search Stripe customers. Query uses Stripe search syntax, e.g. email:'jane@example.com' or name~'Jane'.",
        {"query": {"type": "string"}, "max_results": {"type": "integer"}},
        ["query"],
        ["stripe", "read"],
        False,
    ),
    (
        "stripe_list_charges",
        "List Stripe charges, optionally for one customer.",
        {
            "customer_id": {"type": "string"},
            "max_results": {"type": "integer"},
        },
        [],
        ["stripe", "read"],
        False,
    ),
    (
        "stripe_list_invoices",
        "List Stripe invoices, optionally for one customer.",
        {
            "customer_id": {"type": "string"},
            "max_results": {"type": "integer"},
        },
        [],
        ["stripe", "read"],
        False,
    ),
    (
        "figma_get_file",
        "Read a Figma file's pages and top-level frames (file key is in the URL).",
        {"file_key": {"type": "string"}},
        ["file_key"],
        ["figma", "read"],
        False,
    ),
    (
        "figma_get_comments",
        "List comments on a Figma file.",
        {"file_key": {"type": "string"}},
        ["file_key"],
        ["figma", "read"],
        False,
    ),
    (
        "figma_post_comment",
        "Comment on a Figma file (optionally replying to a comment). Requires user approval.",
        {
            "file_key": {"type": "string"},
            "message": {"type": "string"},
            "reply_to": {"type": "string"},
        },
        ["file_key", "message"],
        ["figma", "write"],
        True,
    ),
    (
        "figma_export_images",
        "Render Figma nodes to image URLs (node ids comma-separated; png/svg/pdf).",
        {
            "file_key": {"type": "string"},
            "node_ids": {"type": "string"},
            "format": {"type": "string"},
            "scale": {"type": "integer"},
        },
        ["file_key", "node_ids"],
        ["figma", "read"],
        False,
    ),
    (
        "docusign_list_envelopes",
        "List recent Docusign envelopes, optionally by status (sent/delivered/completed/declined/voided).",
        {"status": {"type": "string"}, "since_days": {"type": "integer"}},
        [],
        ["docusign", "read"],
        False,
    ),
    (
        "docusign_get_envelope",
        "Read a Docusign envelope's status and per-signer progress.",
        {"envelope_id": {"type": "string"}},
        ["envelope_id"],
        ["docusign", "read"],
        False,
    ),
    (
        "docusign_list_templates",
        "List Docusign templates (template ids are needed to send).",
        {"max_results": {"type": "integer"}},
        [],
        ["docusign", "read"],
        False,
    ),
    (
        "docusign_send_from_template",
        "Send a Docusign template to one signer for signature. Requires user approval.",
        {
            "template_id": {"type": "string"},
            "recipient_email": {"type": "string"},
            "recipient_name": {"type": "string"},
            "role_name": {"type": "string"},
            "subject": {"type": "string"},
        },
        ["template_id", "recipient_email", "recipient_name"],
        ["docusign", "write"],
        True,
    ),
    (
        "canva_list_designs",
        "List (or text-search) Canva designs.",
        {"query": {"type": "string"}, "max_results": {"type": "integer"}},
        [],
        ["canva", "read"],
        False,
    ),
    (
        "canva_get_design",
        "Read a Canva design's metadata (title, pages, urls).",
        {"design_id": {"type": "string"}},
        ["design_id"],
        ["canva", "read"],
        False,
    ),
    (
        "canva_export_design",
        "Start rendering a Canva design to pdf/png/jpg; returns an export job to poll.",
        {"design_id": {"type": "string"}, "format": {"type": "string"}},
        ["design_id"],
        ["canva", "read"],
        False,
    ),
    (
        "canva_get_export",
        "Check a Canva export job; returns download URLs when finished.",
        {"export_id": {"type": "string"}},
        ["export_id"],
        ["canva", "read"],
        False,
    ),
]


def test_factories_have_common_signature_and_composite_preserves_legacy_order() -> None:
    factories = (
        make_zendesk_tools,
        make_discord_tools,
        make_stripe_tools,
        make_figma_tools,
        make_docusign_tools,
        make_canva_tools,
        make_design_commerce_tools,
    )
    for factory in factories:
        signature = inspect.signature(factory)
        assert list(signature.parameters) == ["secrets", "roots", "request_fn"]
        assert signature.parameters["roots"].kind is inspect.Parameter.KEYWORD_ONLY
        assert signature.parameters["request_fn"].kind is inspect.Parameter.KEYWORD_ONLY

    tools = make_design_commerce_tools(FakeSecrets({}), request_fn=FakeRequest())
    assert [tool.__name__ for tool in tools] == [row[0] for row in EXPECTED_SURFACES]


def test_all_tool_schemas_and_metadata_match_legacy_surface() -> None:
    tools = make_design_commerce_tools(FakeSecrets({}), request_fn=FakeRequest())
    assert len(tools) == len(EXPECTED_SURFACES)

    for tool, (name, description, properties, required, caps, approval) in zip(
        tools, EXPECTED_SURFACES, strict=True
    ):
        assert tool.__name__ == name
        assert tool.__doc__ == description
        assert tool.__link_schema__ == {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }
        metadata = tool.__aisuite_tool_metadata__
        assert metadata.name == name
        assert metadata.category == "connector"
        assert metadata.capabilities == caps
        assert metadata.requires_approval is approval
        assert metadata.risk_level == ("medium" if approval else "low")


def test_zendesk_create_ticket_uses_basic_auth_and_requester() -> None:
    secrets = FakeSecrets(
        {
            "zendesk:default": {
                "subdomain": "acme",
                "email": "agent@example.com",
                "api_token": "zd-secret",
            }
        }
    )
    request_fn = FakeRequest()
    tool = _by_name(make_zendesk_tools(secrets, request_fn=request_fn))[
        "zendesk_create_ticket"
    ]

    result = tool("Printer offline", "Please investigate", "user@example.com")

    assert result["ok"] is True
    assert request_fn.calls == [
        (
            "POST",
            "https://acme.zendesk.com/api/v2/tickets.json",
            {
                "auth": ("agent@example.com/token", "zd-secret"),
                "json": {
                    "ticket": {
                        "subject": "Printer offline",
                        "comment": {"body": "Please investigate"},
                        "requester": {"email": "user@example.com"},
                    }
                },
            },
        )
    ]


def test_discord_send_message_uses_bot_auth_and_legacy_length_limit() -> None:
    secrets = FakeSecrets({"discord:default": {"bot_token": "bot-secret"}})
    request_fn = FakeRequest()
    tool = _by_name(make_discord_tools(secrets, request_fn=request_fn))[
        "discord_send_message"
    ]

    tool("channel/1", "x" * 2001)

    assert request_fn.calls == [
        (
            "POST",
            "https://discord.com/api/v10/channels/channel/1/messages",
            {
                "headers": {"Authorization": "Bot bot-secret"},
                "json": {"content": "x" * 2000},
            },
        )
    ]


def test_stripe_list_charges_clamps_limit_and_adds_customer() -> None:
    secrets = FakeSecrets({"stripe:default": {"api_key": "sk_test"}})
    request_fn = FakeRequest()
    tool = _by_name(make_stripe_tools(secrets, request_fn=request_fn))[
        "stripe_list_charges"
    ]

    tool("cus_123", 999)

    assert request_fn.calls == [
        (
            "GET",
            "https://api.stripe.com/v1/charges",
            {
                "headers": {
                    "Authorization": "Bearer sk_test",
                    "Accept": "application/json",
                },
                "params": {"limit": 20, "customer": "cus_123"},
            },
        )
    ]


def test_figma_get_file_quotes_key_and_summarizes_tree() -> None:
    def figma_response(
        _method: str, _url: str, _kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "data": {
                "name": "Checkout",
                "lastModified": "2026-08-23T10:00:00Z",
                "document": {
                    "children": [
                        {
                            "id": "0:1",
                            "name": "Page",
                            "type": "CANVAS",
                            "children": [
                                {
                                    "id": "1:2",
                                    "name": "Frame",
                                    "type": "FRAME",
                                    "children": [
                                        {
                                            "id": "2:3",
                                            "name": "Text",
                                            "type": "TEXT",
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                },
            },
        }

    secrets = FakeSecrets({"figma:default": {"access_token": "fig-secret"}})
    request_fn = FakeRequest(figma_response)
    tool = _by_name(make_figma_tools(secrets, request_fn=request_fn))["figma_get_file"]

    result = tool("key with space")

    assert request_fn.calls == [
        (
            "GET",
            "https://api.figma.com/v1/files/key%20with%20space",
            {"headers": {"X-Figma-Token": "fig-secret"}, "params": {"depth": 2}},
        )
    ]
    assert result == {
        "ok": True,
        "name": "Checkout",
        "last_modified": "2026-08-23T10:00:00Z",
        "pages": [
            {
                "id": "0:1",
                "name": "Page",
                "type": "CANVAS",
                "children": [
                    {
                        "id": "1:2",
                        "name": "Frame",
                        "type": "FRAME",
                        "child_count": 1,
                    }
                ],
            }
        ],
    }


def test_docusign_discovers_default_account_caches_it_and_lists_templates() -> None:
    def docusign_response(
        _method: str, url: str, _kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        if url.endswith("/oauth/userinfo"):
            return {
                "ok": True,
                "data": {
                    "accounts": [
                        {
                            "account_id": "acct-1",
                            "base_uri": "https://demo.docusign.net/",
                            "is_default": True,
                        }
                    ]
                },
            }
        return {"ok": True, "data": {"envelopeTemplates": []}}

    secrets = FakeSecrets({"docusign:default": {"access_token": "ds-secret"}})
    request_fn = FakeRequest(docusign_response)
    tool = _by_name(make_docusign_tools(secrets, request_fn=request_fn))[
        "docusign_list_templates"
    ]

    result = tool(200)

    auth = {"Authorization": "Bearer ds-secret", "Accept": "application/json"}
    assert request_fn.calls == [
        (
            "GET",
            "https://account.docusign.com/oauth/userinfo",
            {"headers": auth},
        ),
        (
            "GET",
            "https://demo.docusign.net/restapi/v2.1/accounts/acct-1/templates",
            {"headers": auth, "params": {"count": 20}},
        ),
    ]
    assert secrets.puts == [
        (
            "docusign:default",
            {
                "access_token": "ds-secret",
                "account_id": "acct-1",
                "base_uri": "https://demo.docusign.net/",
            },
        )
    ]
    assert result == {"ok": True, "data": {"envelopeTemplates": []}}


def test_canva_export_design_preserves_nested_format_payload() -> None:
    secrets = FakeSecrets({"canva:default": {"access_token": "canva-secret"}})
    request_fn = FakeRequest()
    tool = _by_name(make_canva_tools(secrets, request_fn=request_fn))[
        "canva_export_design"
    ]

    tool("design/one", "png")

    assert request_fn.calls == [
        (
            "POST",
            "https://api.canva.com/rest/v1/exports",
            {
                "headers": {
                    "Authorization": "Bearer canva-secret",
                    "Accept": "application/json",
                },
                "json": {
                    "design_id": "design/one",
                    "format": {"type": "png"},
                },
            },
        )
    ]
