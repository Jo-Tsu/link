"""Design, support, community, and commerce connector tools.

The factories in this module preserve the legacy ``integration_tools`` surfaces
while keeping credential lookup and HTTP execution injectable for composition
and tests.
"""

from __future__ import annotations

from typing import Any, Callable, Optional
from urllib.parse import quote

from ...secrets import SecretStore
from ..tool_utils import attach, bearer_headers, clamp, profile, request, schema


Tool = Callable[..., Any]
RequestFn = Callable[..., dict[str, Any]]

_FIGMA = "https://api.figma.com/v1"
_CANVA = "https://api.canva.com/rest/v1"


def make_zendesk_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: RequestFn = request,
) -> list[Tool]:
    """Build Zendesk connector tools in their legacy order."""
    _ = roots
    tools: list[Tool] = []

    def zendesk_search(query: str) -> dict[str, Any]:
        prof, err = profile(
            secrets, "zendesk", "subdomain", "email", "api_token"
        )
        if err:
            return err
        return request_fn(
            "GET",
            f"https://{prof['subdomain']}.zendesk.com/api/v2/search.json",
            auth=(f"{prof['email']}/token", prof["api_token"]),
            params={"query": query},
        )

    zendesk_search.__name__ = "zendesk_search"
    tools.append(
        attach(
            zendesk_search,
            schema(
                "zendesk_search",
                "Search Zendesk tickets/users/articles.",
                {"query": {"type": "string"}},
                ["query"],
            ),
            caps=["zendesk", "read"],
        )
    )

    def zendesk_get_ticket(ticket_id: int) -> dict[str, Any]:
        prof, err = profile(
            secrets, "zendesk", "subdomain", "email", "api_token"
        )
        if err:
            return err
        return request_fn(
            "GET",
            f"https://{prof['subdomain']}.zendesk.com/api/v2/tickets/{ticket_id}.json",
            auth=(f"{prof['email']}/token", prof["api_token"]),
        )

    zendesk_get_ticket.__name__ = "zendesk_get_ticket"
    tools.append(
        attach(
            zendesk_get_ticket,
            schema(
                "zendesk_get_ticket",
                "Read a Zendesk ticket.",
                {"ticket_id": {"type": "integer"}},
                ["ticket_id"],
            ),
            caps=["zendesk", "read"],
        )
    )

    def zendesk_create_ticket(
        subject: str, body: str, requester_email: str = ""
    ) -> dict[str, Any]:
        prof, err = profile(
            secrets, "zendesk", "subdomain", "email", "api_token"
        )
        if err:
            return err
        ticket: dict[str, Any] = {"subject": subject, "comment": {"body": body}}
        if requester_email:
            ticket["requester"] = {"email": requester_email}
        return request_fn(
            "POST",
            f"https://{prof['subdomain']}.zendesk.com/api/v2/tickets.json",
            auth=(f"{prof['email']}/token", prof["api_token"]),
            json={"ticket": ticket},
        )

    zendesk_create_ticket.__name__ = "zendesk_create_ticket"
    tools.append(
        attach(
            zendesk_create_ticket,
            schema(
                "zendesk_create_ticket",
                "Create a Zendesk ticket. Requires user approval.",
                {
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "requester_email": {"type": "string"},
                },
                ["subject", "body"],
            ),
            approval=True,
            caps=["zendesk", "write"],
        )
    )
    return tools


def make_discord_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: RequestFn = request,
) -> list[Tool]:
    """Build Discord connector tools in their legacy order."""
    _ = roots
    tools: list[Tool] = []

    def discord_list_channels(guild_id: str) -> dict[str, Any]:
        prof, err = profile(secrets, "discord", "bot_token")
        if err:
            return err
        return request_fn(
            "GET",
            f"https://discord.com/api/v10/guilds/{guild_id}/channels",
            headers={"Authorization": f"Bot {prof['bot_token']}"},
        )

    discord_list_channels.__name__ = "discord_list_channels"
    tools.append(
        attach(
            discord_list_channels,
            schema(
                "discord_list_channels",
                "List channels in a Discord server (guild).",
                {"guild_id": {"type": "string"}},
                ["guild_id"],
            ),
            caps=["discord", "read"],
        )
    )

    def discord_read_messages(
        channel_id: str, max_results: int = 10
    ) -> dict[str, Any]:
        prof, err = profile(secrets, "discord", "bot_token")
        if err:
            return err
        return request_fn(
            "GET",
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {prof['bot_token']}"},
            params={"limit": clamp(max_results, ceiling=50)},
        )

    discord_read_messages.__name__ = "discord_read_messages"
    tools.append(
        attach(
            discord_read_messages,
            schema(
                "discord_read_messages",
                "Read recent messages from a Discord channel.",
                {
                    "channel_id": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                ["channel_id"],
            ),
            caps=["discord", "read"],
        )
    )

    def discord_send_message(channel_id: str, content: str) -> dict[str, Any]:
        prof, err = profile(secrets, "discord", "bot_token")
        if err:
            return err
        return request_fn(
            "POST",
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            headers={"Authorization": f"Bot {prof['bot_token']}"},
            json={"content": content[:2000]},
        )

    discord_send_message.__name__ = "discord_send_message"
    tools.append(
        attach(
            discord_send_message,
            schema(
                "discord_send_message",
                "Send a message to a Discord channel. Requires user approval.",
                {
                    "channel_id": {"type": "string"},
                    "content": {"type": "string"},
                },
                ["channel_id", "content"],
            ),
            approval=True,
            caps=["discord", "write"],
        )
    )
    return tools


def make_stripe_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: RequestFn = request,
) -> list[Tool]:
    """Build Stripe connector tools in their legacy order."""
    _ = roots
    tools: list[Tool] = []

    def stripe_search_customers(
        query: str, max_results: int = 10
    ) -> dict[str, Any]:
        prof, err = profile(secrets, "stripe", "api_key")
        if err:
            return err
        return request_fn(
            "GET",
            "https://api.stripe.com/v1/customers/search",
            headers=bearer_headers(prof["api_key"]),
            params={"query": query, "limit": clamp(max_results)},
        )

    stripe_search_customers.__name__ = "stripe_search_customers"
    tools.append(
        attach(
            stripe_search_customers,
            schema(
                "stripe_search_customers",
                "Search Stripe customers. Query uses Stripe search syntax, e.g. email:'jane@example.com' or name~'Jane'.",
                {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                ["query"],
            ),
            caps=["stripe", "read"],
        )
    )

    def stripe_list_charges(
        customer_id: str = "", max_results: int = 10
    ) -> dict[str, Any]:
        prof, err = profile(secrets, "stripe", "api_key")
        if err:
            return err
        params: dict[str, Any] = {"limit": clamp(max_results)}
        if customer_id:
            params["customer"] = customer_id
        return request_fn(
            "GET",
            "https://api.stripe.com/v1/charges",
            headers=bearer_headers(prof["api_key"]),
            params=params,
        )

    stripe_list_charges.__name__ = "stripe_list_charges"
    tools.append(
        attach(
            stripe_list_charges,
            schema(
                "stripe_list_charges",
                "List Stripe charges, optionally for one customer.",
                {
                    "customer_id": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                [],
            ),
            caps=["stripe", "read"],
        )
    )

    def stripe_list_invoices(
        customer_id: str = "", max_results: int = 10
    ) -> dict[str, Any]:
        prof, err = profile(secrets, "stripe", "api_key")
        if err:
            return err
        params: dict[str, Any] = {"limit": clamp(max_results)}
        if customer_id:
            params["customer"] = customer_id
        return request_fn(
            "GET",
            "https://api.stripe.com/v1/invoices",
            headers=bearer_headers(prof["api_key"]),
            params=params,
        )

    stripe_list_invoices.__name__ = "stripe_list_invoices"
    tools.append(
        attach(
            stripe_list_invoices,
            schema(
                "stripe_list_invoices",
                "List Stripe invoices, optionally for one customer.",
                {
                    "customer_id": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                [],
            ),
            caps=["stripe", "read"],
        )
    )
    return tools


def _figma_headers(prof: dict[str, Any]) -> dict[str, str]:
    return {"X-Figma-Token": str(prof.get("access_token", ""))}


def _figma_summarize(node: dict[str, Any], depth: int) -> dict[str, Any]:
    out = {
        "id": node.get("id"),
        "name": node.get("name"),
        "type": node.get("type"),
    }
    children = node.get("children") or []
    if depth > 0 and children:
        out["children"] = [_figma_summarize(child, depth - 1) for child in children]
    elif children:
        out["child_count"] = len(children)
    return out


def make_figma_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: RequestFn = request,
) -> list[Tool]:
    """Build Figma connector tools in their legacy order."""
    _ = roots
    tools: list[Tool] = []

    def figma_get_file(file_key: str) -> dict[str, Any]:
        prof, err = profile(secrets, "figma", "access_token")
        if err:
            return err
        result = request_fn(
            "GET",
            f"{_FIGMA}/files/{quote(file_key)}",
            headers=_figma_headers(prof),
            params={"depth": 2},
        )
        if not result.get("ok"):
            return result
        data = result.get("data") or {}
        doc = data.get("document") or {}
        return {
            "ok": True,
            "name": data.get("name"),
            "last_modified": data.get("lastModified"),
            "pages": [
                _figma_summarize(page, 1) for page in (doc.get("children") or [])
            ],
        }

    figma_get_file.__name__ = "figma_get_file"
    tools.append(
        attach(
            figma_get_file,
            schema(
                "figma_get_file",
                "Read a Figma file's pages and top-level frames (file key is in the URL).",
                {"file_key": {"type": "string"}},
                ["file_key"],
            ),
            caps=["figma", "read"],
        )
    )

    def figma_get_comments(file_key: str) -> dict[str, Any]:
        prof, err = profile(secrets, "figma", "access_token")
        if err:
            return err
        return request_fn(
            "GET",
            f"{_FIGMA}/files/{quote(file_key)}/comments",
            headers=_figma_headers(prof),
        )

    figma_get_comments.__name__ = "figma_get_comments"
    tools.append(
        attach(
            figma_get_comments,
            schema(
                "figma_get_comments",
                "List comments on a Figma file.",
                {"file_key": {"type": "string"}},
                ["file_key"],
            ),
            caps=["figma", "read"],
        )
    )

    def figma_post_comment(
        file_key: str, message: str, reply_to: str = ""
    ) -> dict[str, Any]:
        prof, err = profile(secrets, "figma", "access_token")
        if err:
            return err
        body: dict[str, Any] = {"message": message}
        if reply_to:
            body["comment_id"] = reply_to
        return request_fn(
            "POST",
            f"{_FIGMA}/files/{quote(file_key)}/comments",
            headers=_figma_headers(prof),
            json=body,
        )

    figma_post_comment.__name__ = "figma_post_comment"
    tools.append(
        attach(
            figma_post_comment,
            schema(
                "figma_post_comment",
                "Comment on a Figma file (optionally replying to a comment). Requires user approval.",
                {
                    "file_key": {"type": "string"},
                    "message": {"type": "string"},
                    "reply_to": {"type": "string"},
                },
                ["file_key", "message"],
            ),
            approval=True,
            caps=["figma", "write"],
        )
    )

    def figma_export_images(
        file_key: str, node_ids: str, format: str = "png", scale: int = 2
    ) -> dict[str, Any]:
        prof, err = profile(secrets, "figma", "access_token")
        if err:
            return err
        return request_fn(
            "GET",
            f"{_FIGMA}/images/{quote(file_key)}",
            headers=_figma_headers(prof),
            params={"ids": node_ids, "format": format, "scale": scale},
        )

    figma_export_images.__name__ = "figma_export_images"
    tools.append(
        attach(
            figma_export_images,
            schema(
                "figma_export_images",
                "Render Figma nodes to image URLs (node ids comma-separated; png/svg/pdf).",
                {
                    "file_key": {"type": "string"},
                    "node_ids": {"type": "string"},
                    "format": {"type": "string"},
                    "scale": {"type": "integer"},
                },
                ["file_key", "node_ids"],
            ),
            caps=["figma", "read"],
        )
    )
    return tools


def make_docusign_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: RequestFn = request,
) -> list[Tool]:
    """Build Docusign connector tools in their legacy order."""
    _ = roots
    tools: list[Tool] = []

    def docusign_ctx(
        prof: dict[str, Any],
    ) -> tuple[Optional[dict[str, Any]], Optional[dict[str, str]]]:
        token = str(prof.get("access_token", ""))
        account_id = prof.get("account_id")
        base_uri = prof.get("base_uri")
        if not (account_id and base_uri):
            info = request_fn(
                "GET",
                "https://account.docusign.com/oauth/userinfo",
                headers=bearer_headers(token),
            )
            if not info.get("ok"):
                return None, {
                    "error": "docusign account discovery failed",
                    "details": str(info.get("details") or info.get("error")),
                }
            accounts = (info.get("data") or {}).get("accounts") or []
            chosen = next(
                (account for account in accounts if account.get("is_default")),
                accounts[0] if accounts else None,
            )
            if not chosen:
                return None, {"error": "docusign token has no accounts"}
            account_id = chosen.get("account_id")
            base_uri = chosen.get("base_uri")
            secrets.put(
                "docusign:default",
                {**prof, "account_id": account_id, "base_uri": base_uri},
            )
        return {
            "token": token,
            "base": (
                f"{str(base_uri).rstrip('/')}/restapi/v2.1/accounts/{account_id}"
            ),
        }, None

    def docusign_list_envelopes(
        status: str = "", since_days: int = 30
    ) -> dict[str, Any]:
        prof, err = profile(secrets, "docusign", "access_token")
        if err:
            return err
        ctx, err = docusign_ctx(prof)
        if err:
            return err
        from datetime import datetime, timedelta, timezone

        params: dict[str, Any] = {
            "from_date": (
                datetime.now(timezone.utc) - timedelta(days=max(1, int(since_days)))
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        }
        if status:
            params["status"] = status
        return request_fn(
            "GET",
            f"{ctx['base']}/envelopes",
            headers=bearer_headers(ctx["token"]),
            params=params,
        )

    docusign_list_envelopes.__name__ = "docusign_list_envelopes"
    tools.append(
        attach(
            docusign_list_envelopes,
            schema(
                "docusign_list_envelopes",
                "List recent Docusign envelopes, optionally by status (sent/delivered/completed/declined/voided).",
                {
                    "status": {"type": "string"},
                    "since_days": {"type": "integer"},
                },
                [],
            ),
            caps=["docusign", "read"],
        )
    )

    def docusign_get_envelope(envelope_id: str) -> dict[str, Any]:
        prof, err = profile(secrets, "docusign", "access_token")
        if err:
            return err
        ctx, err = docusign_ctx(prof)
        if err:
            return err
        return request_fn(
            "GET",
            f"{ctx['base']}/envelopes/{quote(envelope_id)}",
            headers=bearer_headers(ctx["token"]),
            params={"include": "recipients"},
        )

    docusign_get_envelope.__name__ = "docusign_get_envelope"
    tools.append(
        attach(
            docusign_get_envelope,
            schema(
                "docusign_get_envelope",
                "Read a Docusign envelope's status and per-signer progress.",
                {"envelope_id": {"type": "string"}},
                ["envelope_id"],
            ),
            caps=["docusign", "read"],
        )
    )

    def docusign_list_templates(max_results: int = 10) -> dict[str, Any]:
        prof, err = profile(secrets, "docusign", "access_token")
        if err:
            return err
        ctx, err = docusign_ctx(prof)
        if err:
            return err
        return request_fn(
            "GET",
            f"{ctx['base']}/templates",
            headers=bearer_headers(ctx["token"]),
            params={"count": clamp(max_results)},
        )

    docusign_list_templates.__name__ = "docusign_list_templates"
    tools.append(
        attach(
            docusign_list_templates,
            schema(
                "docusign_list_templates",
                "List Docusign templates (template ids are needed to send).",
                {"max_results": {"type": "integer"}},
                [],
            ),
            caps=["docusign", "read"],
        )
    )

    def docusign_send_from_template(
        template_id: str,
        recipient_email: str,
        recipient_name: str,
        role_name: str = "Signer",
        subject: str = "",
    ) -> dict[str, Any]:
        prof, err = profile(secrets, "docusign", "access_token")
        if err:
            return err
        ctx, err = docusign_ctx(prof)
        if err:
            return err
        body: dict[str, Any] = {
            "templateId": template_id,
            "templateRoles": [
                {
                    "email": recipient_email,
                    "name": recipient_name,
                    "roleName": role_name,
                }
            ],
            "status": "sent",
        }
        if subject:
            body["emailSubject"] = subject
        return request_fn(
            "POST",
            f"{ctx['base']}/envelopes",
            headers=bearer_headers(ctx["token"]),
            json=body,
        )

    docusign_send_from_template.__name__ = "docusign_send_from_template"
    tools.append(
        attach(
            docusign_send_from_template,
            schema(
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
            ),
            approval=True,
            caps=["docusign", "write"],
        )
    )
    return tools


def make_canva_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: RequestFn = request,
) -> list[Tool]:
    """Build Canva connector tools in their legacy order."""
    _ = roots
    tools: list[Tool] = []

    def canva_list_designs(
        query: str = "", max_results: int = 10
    ) -> dict[str, Any]:
        prof, err = profile(secrets, "canva", "access_token")
        if err:
            return err
        params: dict[str, Any] = {"limit": clamp(max_results)}
        if query:
            params["query"] = query
        return request_fn(
            "GET",
            f"{_CANVA}/designs",
            headers=bearer_headers(prof["access_token"]),
            params=params,
        )

    canva_list_designs.__name__ = "canva_list_designs"
    tools.append(
        attach(
            canva_list_designs,
            schema(
                "canva_list_designs",
                "List (or text-search) Canva designs.",
                {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                [],
            ),
            caps=["canva", "read"],
        )
    )

    def canva_get_design(design_id: str) -> dict[str, Any]:
        prof, err = profile(secrets, "canva", "access_token")
        if err:
            return err
        return request_fn(
            "GET",
            f"{_CANVA}/designs/{quote(design_id)}",
            headers=bearer_headers(prof["access_token"]),
        )

    canva_get_design.__name__ = "canva_get_design"
    tools.append(
        attach(
            canva_get_design,
            schema(
                "canva_get_design",
                "Read a Canva design's metadata (title, pages, urls).",
                {"design_id": {"type": "string"}},
                ["design_id"],
            ),
            caps=["canva", "read"],
        )
    )

    def canva_export_design(
        design_id: str, format: str = "pdf"
    ) -> dict[str, Any]:
        prof, err = profile(secrets, "canva", "access_token")
        if err:
            return err
        return request_fn(
            "POST",
            f"{_CANVA}/exports",
            headers=bearer_headers(prof["access_token"]),
            json={"design_id": design_id, "format": {"type": format}},
        )

    canva_export_design.__name__ = "canva_export_design"
    tools.append(
        attach(
            canva_export_design,
            schema(
                "canva_export_design",
                "Start rendering a Canva design to pdf/png/jpg; returns an export job to poll.",
                {
                    "design_id": {"type": "string"},
                    "format": {"type": "string"},
                },
                ["design_id"],
            ),
            caps=["canva", "read"],
        )
    )

    def canva_get_export(export_id: str) -> dict[str, Any]:
        prof, err = profile(secrets, "canva", "access_token")
        if err:
            return err
        return request_fn(
            "GET",
            f"{_CANVA}/exports/{quote(export_id)}",
            headers=bearer_headers(prof["access_token"]),
        )

    canva_get_export.__name__ = "canva_get_export"
    tools.append(
        attach(
            canva_get_export,
            schema(
                "canva_get_export",
                "Check a Canva export job; returns download URLs when finished.",
                {"export_id": {"type": "string"}},
                ["export_id"],
            ),
            caps=["canva", "read"],
        )
    )
    return tools


def make_design_commerce_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: RequestFn = request,
) -> list[Tool]:
    """Build this extraction batch in legacy global order."""
    tools: list[Tool] = []
    for factory in (
        make_zendesk_tools,
        make_discord_tools,
        make_stripe_tools,
        make_figma_tools,
        make_docusign_tools,
        make_canva_tools,
    ):
        tools.extend(factory(secrets, roots=roots, request_fn=request_fn))
    return tools


__all__ = [
    "make_zendesk_tools",
    "make_discord_tools",
    "make_stripe_tools",
    "make_figma_tools",
    "make_docusign_tools",
    "make_canva_tools",
    "make_design_commerce_tools",
]
