"""CRM, product analytics, and prospecting connector tools.

The factories in this module are intentionally explicit.  Each one preserves the
legacy tool surface while allowing callers to inject the HTTP transport.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional
from urllib.parse import quote

from ...secrets import SecretStore
from ..tool_utils import (
    GEN_ACCOUNT_PROP,
    account_profile,
    acct_result,
    attach,
    bearer_headers,
    clamp,
    profile,
    request,
    schema,
)


_HS_NOTE_ASSOC = {"contacts": 202, "companies": 190, "deals": 214, "tickets": 228}
_HS_KINDS = ("contacts", "companies", "deals", "tickets")
_PORTAL_PROP = {
    "type": "string",
    "description": "Portal (hub id or name) to use; omit for the default portal.",
}


def _now_ms() -> int:
    from time import time

    return int(time() * 1000)


def _hubspot_profile(
    secrets: SecretStore, portal: str = ""
) -> tuple[str, str, Optional[dict[str, str]]]:
    """Resolve the requested or default portal and its current bearer token."""
    from .. import hubspot_portals

    hub_id, key, portal_profile = hubspot_portals.resolve(secrets, portal)
    if portal_profile is None:
        hint = (
            f"no hubspot portal matching {portal!r}"
            if portal
            else "hubspot is not connected"
        )
        return "", "", {"error": hint}
    if portal_profile.get("managed"):
        from ...cloud import ensure_fresh_connector_token
        from ...config import load_config

        ensure_fresh_connector_token(
            secrets, load_config(), "hubspot", profile_key=key
        )
        portal_profile = secrets.get(key) or portal_profile
    token = portal_profile.get("token") or portal_profile.get("access_token") or ""
    if not token:
        return "", "", {"error": f"hubspot portal {hub_id} has no usable token"}
    name = str(portal_profile.get("account") or f"portal {hub_id}")
    return name, token, None


def _hubspot_result(
    secrets: SecretStore, portal_name: str, result: dict[str, Any]
) -> dict[str, Any]:
    """Apply the model-facing hidden-field policy and stamp the portal name."""
    from .. import hubspot_portals

    if not result.get("ok"):
        return result
    hidden = hubspot_portals.get_hidden_fields(secrets)
    data, removed = hubspot_portals.strip_hidden(result.get("data"), hidden)
    out = {**result, "data": data, "portal": portal_name}
    if removed:
        out["_display"] = {"hidden_fields": removed, "connector": "hubspot"}
    return out


def make_hubspot_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build HubSpot CRM tools."""
    del roots
    tools: list[Callable[..., Any]] = []

    def hubspot_search(
        query: str = "",
        object_type: str = "contacts",
        max_results: int = 10,
        properties: str = "",
        filters: str = "",
        portal: str = "",
    ) -> dict[str, Any]:
        name, token, err = _hubspot_profile(secrets, portal)
        if err:
            return err
        kind = object_type if object_type in _HS_KINDS else "contacts"
        body: dict[str, Any] = {"limit": clamp(max_results, ceiling=100)}
        if query:
            body["query"] = query
        if properties:
            body["properties"] = [
                item.strip() for item in properties.split(",") if item.strip()
            ]
        if filters:
            try:
                parsed = json.loads(filters)
            except ValueError:
                return {"error": "filters must be a JSON array of filter objects"}
            if not isinstance(parsed, list) or not all(
                isinstance(item, dict)
                and item.get("property")
                and item.get("operator")
                for item in parsed
            ):
                return {"error": "each filter needs at least 'property' and 'operator'"}
            body["filterGroups"] = [{"filters": parsed}]
        if not query and not filters:
            return {"error": "provide a query, filters, or both"}
        result = request_fn(
            "POST",
            f"https://api.hubapi.com/crm/v3/objects/{kind}/search",
            headers=bearer_headers(token),
            json=body,
        )
        return _hubspot_result(secrets, name, result)

    hubspot_search.__name__ = "hubspot_search"
    tools.append(
        attach(
            hubspot_search,
            schema(
                "hubspot_search",
                "Search HubSpot CRM contacts, companies, deals, or tickets (object_type). "
                "Custom properties are only returned if named in `properties`, and only "
                "matchable via `filters` (free-text query searches default fields only).",
                {
                    "query": {"type": "string", "description": "Free-text search"},
                    "object_type": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "properties": {
                        "type": "string",
                        "description": "Comma-separated property names to return "
                        "(include custom properties here)",
                    },
                    "filters": {
                        "type": "string",
                        "description": 'JSON array of {"property", "operator", "value"} '
                        "objects, ANDed together. Operators: EQ, NEQ, LT, LTE, GT, GTE, "
                        "CONTAINS_TOKEN, HAS_PROPERTY, NOT_HAS_PROPERTY, IN",
                    },
                    "portal": _PORTAL_PROP,
                },
                [],
            ),
            caps=["hubspot", "read"],
        )
    )

    def hubspot_get_object(
        object_type: str,
        object_id: str,
        properties: str = "",
        associations: str = "",
        portal: str = "",
    ) -> dict[str, Any]:
        name, token, err = _hubspot_profile(secrets, portal)
        if err:
            return err
        kind = object_type if object_type in _HS_KINDS else "contacts"
        params: dict[str, Any] = {}
        if properties:
            params["properties"] = properties
        if associations:
            params["associations"] = associations
        result = request_fn(
            "GET",
            f"https://api.hubapi.com/crm/v3/objects/{kind}/{object_id}",
            headers=bearer_headers(token),
            params=params or None,
        )
        return _hubspot_result(secrets, name, result)

    hubspot_get_object.__name__ = "hubspot_get_object"
    tools.append(
        attach(
            hubspot_get_object,
            schema(
                "hubspot_get_object",
                "Read a HubSpot CRM record by ID. Custom properties are only "
                "returned if named in `properties`; pass `associations` to also get "
                "linked record ids.",
                {
                    "object_type": {"type": "string"},
                    "object_id": {"type": "string"},
                    "properties": {
                        "type": "string",
                        "description": "Comma-separated property names to return",
                    },
                    "associations": {
                        "type": "string",
                        "description": "Comma-separated object types to return "
                        "associated ids for (e.g. companies,contacts)",
                    },
                    "portal": _PORTAL_PROP,
                },
                ["object_type", "object_id"],
            ),
            caps=["hubspot", "read"],
        )
    )

    def hubspot_create_contact(
        email: str, first_name: str = "", last_name: str = "", portal: str = ""
    ) -> dict[str, Any]:
        name, token, err = _hubspot_profile(secrets, portal)
        if err:
            return err
        props = {"email": email}
        if first_name:
            props["firstname"] = first_name
        if last_name:
            props["lastname"] = last_name
        result = request_fn(
            "POST",
            "https://api.hubapi.com/crm/v3/objects/contacts",
            headers=bearer_headers(token),
            json={"properties": props},
        )
        return _hubspot_result(secrets, name, result)

    hubspot_create_contact.__name__ = "hubspot_create_contact"
    tools.append(
        attach(
            hubspot_create_contact,
            schema(
                "hubspot_create_contact",
                "Create a HubSpot contact. Requires user approval; the `portal` "
                "argument names the portal on the approval card.",
                {
                    "email": {"type": "string"},
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                    "portal": _PORTAL_PROP,
                },
                ["email"],
            ),
            approval=True,
            caps=["hubspot", "write"],
        )
    )

    def hubspot_update_object(
        object_type: str, object_id: str, properties: dict, portal: str = ""
    ) -> dict[str, Any]:
        name, token, err = _hubspot_profile(secrets, portal)
        if err:
            return err
        kind = object_type if object_type in _HS_KINDS else "contacts"
        if not isinstance(properties, dict) or not properties:
            return {"error": "properties must be a non-empty object"}
        result = request_fn(
            "PATCH",
            f"https://api.hubapi.com/crm/v3/objects/{kind}/{object_id}",
            headers=bearer_headers(token),
            json={"properties": properties},
        )
        return _hubspot_result(secrets, name, result)

    hubspot_update_object.__name__ = "hubspot_update_object"
    tools.append(
        attach(
            hubspot_update_object,
            schema(
                "hubspot_update_object",
                "Update properties on a HubSpot CRM record (no deletes exist). "
                "Requires user approval.",
                {
                    "object_type": {"type": "string"},
                    "object_id": {"type": "string"},
                    "properties": {"type": "object"},
                    "portal": _PORTAL_PROP,
                },
                ["object_type", "object_id", "properties"],
            ),
            approval=True,
            caps=["hubspot", "write"],
        )
    )

    def hubspot_log_note(
        object_type: str, object_id: str, note: str, portal: str = ""
    ) -> dict[str, Any]:
        name, token, err = _hubspot_profile(secrets, portal)
        if err:
            return err
        kind = object_type if object_type in _HS_KINDS else "contacts"
        result = request_fn(
            "POST",
            "https://api.hubapi.com/crm/v3/objects/notes",
            headers=bearer_headers(token),
            json={
                "properties": {
                    "hs_note_body": note,
                    "hs_timestamp": _now_ms(),
                },
                "associations": [
                    {
                        "to": {"id": object_id},
                        "types": [
                            {
                                "associationCategory": "HUBSPOT_DEFINED",
                                "associationTypeId": _HS_NOTE_ASSOC[kind],
                            }
                        ],
                    }
                ],
            },
        )
        return _hubspot_result(secrets, name, result)

    hubspot_log_note.__name__ = "hubspot_log_note"
    tools.append(
        attach(
            hubspot_log_note,
            schema(
                "hubspot_log_note",
                "Log a note on a HubSpot record's timeline. Requires user approval.",
                {
                    "object_type": {"type": "string"},
                    "object_id": {"type": "string"},
                    "note": {"type": "string"},
                    "portal": _PORTAL_PROP,
                },
                ["object_type", "object_id", "note"],
            ),
            approval=True,
            caps=["hubspot", "write"],
        )
    )

    def hubspot_create_task(
        title: str, due: str = "", notes: str = "", portal: str = ""
    ) -> dict[str, Any]:
        name, token, err = _hubspot_profile(secrets, portal)
        if err:
            return err
        props: dict[str, Any] = {
            "hs_task_subject": title,
            "hs_task_status": "NOT_STARTED",
            "hs_timestamp": due or _now_ms(),
        }
        if notes:
            props["hs_task_body"] = notes
        result = request_fn(
            "POST",
            "https://api.hubapi.com/crm/v3/objects/tasks",
            headers=bearer_headers(token),
            json={"properties": props},
        )
        return _hubspot_result(secrets, name, result)

    hubspot_create_task.__name__ = "hubspot_create_task"
    tools.append(
        attach(
            hubspot_create_task,
            schema(
                "hubspot_create_task",
                "Create a HubSpot task (due = epoch ms or ISO date). Requires user approval.",
                {
                    "title": {"type": "string"},
                    "due": {"type": "string"},
                    "notes": {"type": "string"},
                    "portal": _PORTAL_PROP,
                },
                ["title"],
            ),
            approval=True,
            caps=["hubspot", "write"],
        )
    )

    return tools


def _notion_headers(notion_profile: dict[str, Any]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {notion_profile['access_token']}",
        "Notion-Version": "2022-06-28",
    }


def _notion_blocks_text(blocks: list[dict]) -> str:
    lines = []
    for block in blocks:
        content = block.get(block.get("type", ""), {})
        texts = content.get("rich_text") or content.get("title") or []
        line = "".join(
            item.get("plain_text", "") for item in texts if isinstance(item, dict)
        )
        if line:
            lines.append(line)
    return "\n".join(lines)


def make_notion_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build Notion workspace tools."""
    del roots
    tools: list[Callable[..., Any]] = []

    def notion_search(
        query: str, max_results: int = 10, account: str = ""
    ) -> dict[str, Any]:
        aid, notion_profile, err = account_profile(
            secrets, "notion", account, "access_token"
        )
        if err:
            return err
        result = request_fn(
            "POST",
            "https://api.notion.com/v1/search",
            headers=_notion_headers(notion_profile),
            json={"query": query, "page_size": clamp(max_results, ceiling=100)},
        )
        return acct_result(aid, result)

    notion_search.__name__ = "notion_search"
    tools.append(
        attach(
            notion_search,
            schema(
                "notion_search",
                "Search Notion pages and databases the integration can see.",
                {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "account": GEN_ACCOUNT_PROP,
                },
                ["query"],
            ),
            caps=["notion", "read"],
        )
    )

    def notion_read_page(page_id: str, account: str = "") -> dict[str, Any]:
        aid, notion_profile, err = account_profile(
            secrets, "notion", account, "access_token"
        )
        if err:
            return err
        page = request_fn(
            "GET",
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=_notion_headers(notion_profile),
        )
        if "error" in page:
            return acct_result(aid, page)
        blocks = request_fn(
            "GET",
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            headers=_notion_headers(notion_profile),
            params={"page_size": 100},
        )
        text = (
            _notion_blocks_text((blocks.get("data") or {}).get("results") or [])
            if "error" not in blocks
            else ""
        )
        return acct_result(
            aid,
            {
                "ok": True,
                "properties": (page.get("data") or {}).get("properties"),
                "url": (page.get("data") or {}).get("url"),
                "text": text,
            },
        )

    notion_read_page.__name__ = "notion_read_page"
    tools.append(
        attach(
            notion_read_page,
            schema(
                "notion_read_page",
                "Read a Notion page: properties plus its content flattened to text.",
                {"page_id": {"type": "string"}, "account": GEN_ACCOUNT_PROP},
                ["page_id"],
            ),
            caps=["notion", "read"],
        )
    )

    def notion_query_database(
        database_id: str,
        filter_json: str = "",
        max_results: int = 10,
        account: str = "",
    ) -> dict[str, Any]:
        aid, notion_profile, err = account_profile(
            secrets, "notion", account, "access_token"
        )
        if err:
            return err
        body: dict[str, Any] = {"page_size": clamp(max_results, ceiling=100)}
        if filter_json:
            try:
                body["filter"] = json.loads(filter_json)
            except ValueError:
                return {"error": "filter_json must be a Notion filter object (JSON)"}
        result = request_fn(
            "POST",
            f"https://api.notion.com/v1/databases/{database_id}/query",
            headers=_notion_headers(notion_profile),
            json=body,
        )
        return acct_result(aid, result)

    notion_query_database.__name__ = "notion_query_database"
    tools.append(
        attach(
            notion_query_database,
            schema(
                "notion_query_database",
                "Query a Notion database, optionally with a Notion filter object.",
                {
                    "database_id": {"type": "string"},
                    "filter_json": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "account": GEN_ACCOUNT_PROP,
                },
                ["database_id"],
            ),
            caps=["notion", "read"],
        )
    )

    def notion_create_page(
        parent_page_id: str, title: str, content: str = "", account: str = ""
    ) -> dict[str, Any]:
        aid, notion_profile, err = account_profile(
            secrets, "notion", account, "access_token"
        )
        if err:
            return err
        children = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"text": {"content": line}}]},
            }
            for line in content.splitlines()
            if line.strip()
        ]
        result = request_fn(
            "POST",
            "https://api.notion.com/v1/pages",
            headers=_notion_headers(notion_profile),
            json={
                "parent": {"page_id": parent_page_id},
                "properties": {"title": {"title": [{"text": {"content": title}}]}},
                "children": children,
            },
        )
        return acct_result(aid, result)

    notion_create_page.__name__ = "notion_create_page"
    tools.append(
        attach(
            notion_create_page,
            schema(
                "notion_create_page",
                "Create a Notion page under a parent page (plain-text paragraphs).",
                {
                    "parent_page_id": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "account": GEN_ACCOUNT_PROP,
                },
                ["parent_page_id", "title"],
            ),
            approval=True,
            caps=["notion", "write"],
        )
    )

    return tools


def make_attio_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build Attio CRM tools."""
    del roots
    tools: list[Callable[..., Any]] = []

    def attio_list_objects(account: str = "") -> dict[str, Any]:
        aid, attio_profile, err = account_profile(
            secrets, "attio", account, "access_token"
        )
        if err:
            return err
        result = request_fn(
            "GET",
            "https://api.attio.com/v2/objects",
            headers=bearer_headers(attio_profile["access_token"]),
        )
        return acct_result(aid, result)

    attio_list_objects.__name__ = "attio_list_objects"
    tools.append(
        attach(
            attio_list_objects,
            schema(
                "attio_list_objects",
                "List Attio object types (companies, people, deals, custom).",
                {"account": GEN_ACCOUNT_PROP},
                [],
            ),
            caps=["attio", "read"],
        )
    )

    def attio_query_records(
        object_type: str,
        filter_json: str = "",
        max_results: int = 10,
        account: str = "",
    ) -> dict[str, Any]:
        aid, attio_profile, err = account_profile(
            secrets, "attio", account, "access_token"
        )
        if err:
            return err
        body: dict[str, Any] = {"limit": clamp(max_results, ceiling=100)}
        if filter_json:
            try:
                body["filter"] = json.loads(filter_json)
            except ValueError:
                return {"error": "filter_json must be an Attio filter object (JSON)"}
        result = request_fn(
            "POST",
            f"https://api.attio.com/v2/objects/{object_type}/records/query",
            headers=bearer_headers(attio_profile["access_token"]),
            json=body,
        )
        return acct_result(aid, result)

    attio_query_records.__name__ = "attio_query_records"
    tools.append(
        attach(
            attio_query_records,
            schema(
                "attio_query_records",
                "List/filter records of an Attio object (e.g. companies, people); "
                "filter_json is an Attio filter object.",
                {
                    "object_type": {"type": "string"},
                    "filter_json": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "account": GEN_ACCOUNT_PROP,
                },
                ["object_type"],
            ),
            caps=["attio", "read"],
        )
    )

    def attio_get_record(
        object_type: str, record_id: str, account: str = ""
    ) -> dict[str, Any]:
        aid, attio_profile, err = account_profile(
            secrets, "attio", account, "access_token"
        )
        if err:
            return err
        result = request_fn(
            "GET",
            f"https://api.attio.com/v2/objects/{object_type}/records/{record_id}",
            headers=bearer_headers(attio_profile["access_token"]),
        )
        return acct_result(aid, result)

    attio_get_record.__name__ = "attio_get_record"
    tools.append(
        attach(
            attio_get_record,
            schema(
                "attio_get_record",
                "Read one Attio record by object type and record id.",
                {
                    "object_type": {"type": "string"},
                    "record_id": {"type": "string"},
                    "account": GEN_ACCOUNT_PROP,
                },
                ["object_type", "record_id"],
            ),
            caps=["attio", "read"],
        )
    )

    def attio_create_note(
        parent_object: str,
        parent_record_id: str,
        title: str,
        content: str,
        account: str = "",
    ) -> dict[str, Any]:
        aid, attio_profile, err = account_profile(
            secrets, "attio", account, "access_token"
        )
        if err:
            return err
        result = request_fn(
            "POST",
            "https://api.attio.com/v2/notes",
            headers=bearer_headers(attio_profile["access_token"]),
            json={
                "data": {
                    "parent_object": parent_object,
                    "parent_record_id": parent_record_id,
                    "title": title,
                    "format": "plaintext",
                    "content": content,
                }
            },
        )
        return acct_result(aid, result)

    attio_create_note.__name__ = "attio_create_note"
    tools.append(
        attach(
            attio_create_note,
            schema(
                "attio_create_note",
                "Log a note on an Attio record (e.g. a company or person).",
                {
                    "parent_object": {"type": "string"},
                    "parent_record_id": {"type": "string"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "account": GEN_ACCOUNT_PROP,
                },
                ["parent_object", "parent_record_id", "title", "content"],
            ),
            approval=True,
            caps=["attio", "write"],
        )
    )

    return tools


def _posthog_base(posthog_profile: dict[str, Any]) -> str:
    return str(posthog_profile.get("base_url") or "https://us.posthog.com").rstrip(
        "/"
    )


def make_posthog_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build PostHog analytics tools."""
    del roots
    tools: list[Callable[..., Any]] = []

    def posthog_query(hogql: str, account: str = "") -> dict[str, Any]:
        aid, posthog_profile, err = account_profile(
            secrets, "posthog", account, "api_key", "project_id"
        )
        if err:
            return err
        result = request_fn(
            "POST",
            f"{_posthog_base(posthog_profile)}/api/projects/"
            f"{posthog_profile['project_id']}/query",
            headers=bearer_headers(posthog_profile["api_key"]),
            json={"query": {"kind": "HogQLQuery", "query": hogql}},
        )
        return acct_result(aid, result)

    posthog_query.__name__ = "posthog_query"
    tools.append(
        attach(
            posthog_query,
            schema(
                "posthog_query",
                "Run a HogQL (SQL-like) query against PostHog analytics, e.g. "
                "SELECT event, count() FROM events WHERE timestamp > now() - "
                "INTERVAL 7 DAY GROUP BY event.",
                {"hogql": {"type": "string"}, "account": GEN_ACCOUNT_PROP},
                ["hogql"],
            ),
            caps=["posthog", "read"],
        )
    )

    def posthog_list_insights(
        query: str = "", max_results: int = 10, account: str = ""
    ) -> dict[str, Any]:
        aid, posthog_profile, err = account_profile(
            secrets, "posthog", account, "api_key", "project_id"
        )
        if err:
            return err
        params: dict[str, Any] = {"limit": clamp(max_results)}
        if query:
            params["search"] = query
        result = request_fn(
            "GET",
            f"{_posthog_base(posthog_profile)}/api/projects/"
            f"{posthog_profile['project_id']}/insights",
            headers=bearer_headers(posthog_profile["api_key"]),
            params=params,
        )
        return acct_result(aid, result)

    posthog_list_insights.__name__ = "posthog_list_insights"
    tools.append(
        attach(
            posthog_list_insights,
            schema(
                "posthog_list_insights",
                "List saved PostHog insights (dashboards' building blocks).",
                {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "account": GEN_ACCOUNT_PROP,
                },
                [],
            ),
            caps=["posthog", "read"],
        )
    )

    return tools


def make_mixpanel_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build Mixpanel analytics tools."""
    del roots
    tools: list[Callable[..., Any]] = []

    def mixpanel_segmentation(
        event: str,
        from_date: str,
        to_date: str,
        unit: str = "day",
        where: str = "",
        account: str = "",
    ) -> dict[str, Any]:
        aid, mixpanel_profile, err = account_profile(
            secrets,
            "mixpanel",
            account,
            "username",
            "secret",
            "project_id",
        )
        if err:
            return err
        params = {
            "project_id": mixpanel_profile["project_id"],
            "event": event,
            "from_date": from_date,
            "to_date": to_date,
            "unit": (
                unit if unit in ("minute", "hour", "day", "week", "month") else "day"
            ),
        }
        if where:
            params["where"] = where
        result = request_fn(
            "GET",
            "https://mixpanel.com/api/query/segmentation",
            params=params,
            auth=(mixpanel_profile["username"], mixpanel_profile["secret"]),
        )
        return acct_result(aid, result)

    mixpanel_segmentation.__name__ = "mixpanel_segmentation"
    tools.append(
        attach(
            mixpanel_segmentation,
            schema(
                "mixpanel_segmentation",
                "Mixpanel event counts over a date range (YYYY-MM-DD), optionally "
                'filtered by a `where` expression like properties["plan"]=="pro".',
                {
                    "event": {"type": "string"},
                    "from_date": {"type": "string"},
                    "to_date": {"type": "string"},
                    "unit": {"type": "string"},
                    "where": {"type": "string"},
                    "account": GEN_ACCOUNT_PROP,
                },
                ["event", "from_date", "to_date"],
            ),
            caps=["mixpanel", "read"],
        )
    )

    def mixpanel_top_events(
        max_results: int = 10, account: str = ""
    ) -> dict[str, Any]:
        aid, mixpanel_profile, err = account_profile(
            secrets,
            "mixpanel",
            account,
            "username",
            "secret",
            "project_id",
        )
        if err:
            return err
        result = request_fn(
            "GET",
            "https://mixpanel.com/api/query/events/top",
            params={
                "project_id": mixpanel_profile["project_id"],
                "type": "general",
                "limit": clamp(max_results, ceiling=100),
            },
            auth=(mixpanel_profile["username"], mixpanel_profile["secret"]),
        )
        return acct_result(aid, result)

    mixpanel_top_events.__name__ = "mixpanel_top_events"
    tools.append(
        attach(
            mixpanel_top_events,
            schema(
                "mixpanel_top_events",
                "Today's top Mixpanel events by volume.",
                {"max_results": {"type": "integer"}, "account": GEN_ACCOUNT_PROP},
                [],
            ),
            caps=["mixpanel", "read"],
        )
    )

    return tools


def make_amplitude_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build Amplitude analytics tools."""
    del roots
    tools: list[Callable[..., Any]] = []

    def amplitude_active_users(
        start: str, end: str, metric: str = "active", account: str = ""
    ) -> dict[str, Any]:
        aid, amplitude_profile, err = account_profile(
            secrets, "amplitude", account, "api_key", "secret_key"
        )
        if err:
            return err
        result = request_fn(
            "GET",
            "https://amplitude.com/api/2/users",
            params={
                "m": metric if metric in ("active", "new") else "active",
                "start": start.replace("-", ""),
                "end": end.replace("-", ""),
                "i": 1,
            },
            auth=(amplitude_profile["api_key"], amplitude_profile["secret_key"]),
        )
        return acct_result(aid, result)

    amplitude_active_users.__name__ = "amplitude_active_users"
    tools.append(
        attach(
            amplitude_active_users,
            schema(
                "amplitude_active_users",
                "Amplitude daily active or new users between two dates (YYYYMMDD "
                "or YYYY-MM-DD).",
                {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "metric": {"type": "string", "description": "active | new"},
                    "account": GEN_ACCOUNT_PROP,
                },
                ["start", "end"],
            ),
            caps=["amplitude", "read"],
        )
    )

    def amplitude_event_totals(
        event_type: str, start: str, end: str, account: str = ""
    ) -> dict[str, Any]:
        aid, amplitude_profile, err = account_profile(
            secrets, "amplitude", account, "api_key", "secret_key"
        )
        if err:
            return err
        result = request_fn(
            "GET",
            "https://amplitude.com/api/2/events/segmentation",
            params={
                "e": json.dumps({"event_type": event_type}),
                "start": start.replace("-", ""),
                "end": end.replace("-", ""),
                "m": "totals",
            },
            auth=(amplitude_profile["api_key"], amplitude_profile["secret_key"]),
        )
        return acct_result(aid, result)

    amplitude_event_totals.__name__ = "amplitude_event_totals"
    tools.append(
        attach(
            amplitude_event_totals,
            schema(
                "amplitude_event_totals",
                "Daily totals for one Amplitude event between two dates.",
                {
                    "event_type": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "account": GEN_ACCOUNT_PROP,
                },
                ["event_type", "start", "end"],
            ),
            caps=["amplitude", "read"],
        )
    )

    return tools


def _apollo_headers(apollo_profile: dict[str, Any]) -> dict[str, str]:
    return {
        "X-Api-Key": apollo_profile["api_key"],
        "Content-Type": "application/json",
    }


def make_apollo_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build Apollo enrichment and people-search tools."""
    del roots
    tools: list[Callable[..., Any]] = []

    def apollo_enrich_person(
        email: str = "", name: str = "", company_domain: str = "", account: str = ""
    ) -> dict[str, Any]:
        if not email and not name:
            return {"error": "provide an email, a name, or both"}
        aid, apollo_profile, err = account_profile(
            secrets, "apollo", account, "api_key"
        )
        if err:
            return err
        body: dict[str, Any] = {}
        if email:
            body["email"] = email
        if name:
            body["name"] = name
        if company_domain:
            body["domain"] = company_domain
        result = request_fn(
            "POST",
            "https://api.apollo.io/api/v1/people/match",
            headers=_apollo_headers(apollo_profile),
            json=body,
        )
        return acct_result(aid, result)

    apollo_enrich_person.__name__ = "apollo_enrich_person"
    tools.append(
        attach(
            apollo_enrich_person,
            schema(
                "apollo_enrich_person",
                "Enrich a person from Apollo: title, company, LinkedIn, location "
                "— by email and/or name (+ optional company domain).",
                {
                    "email": {"type": "string"},
                    "name": {"type": "string"},
                    "company_domain": {"type": "string"},
                    "account": GEN_ACCOUNT_PROP,
                },
                [],
            ),
            caps=["apollo", "read"],
        )
    )

    def apollo_enrich_company(domain: str, account: str = "") -> dict[str, Any]:
        aid, apollo_profile, err = account_profile(
            secrets, "apollo", account, "api_key"
        )
        if err:
            return err
        result = request_fn(
            "GET",
            "https://api.apollo.io/api/v1/organizations/enrich",
            headers=_apollo_headers(apollo_profile),
            params={"domain": domain},
        )
        return acct_result(aid, result)

    apollo_enrich_company.__name__ = "apollo_enrich_company"
    tools.append(
        attach(
            apollo_enrich_company,
            schema(
                "apollo_enrich_company",
                "Enrich a company from Apollo by domain: size, industry, funding, "
                "tech stack.",
                {"domain": {"type": "string"}, "account": GEN_ACCOUNT_PROP},
                ["domain"],
            ),
            caps=["apollo", "read"],
        )
    )

    def apollo_search_people(
        query: str, max_results: int = 10, account: str = ""
    ) -> dict[str, Any]:
        aid, apollo_profile, err = account_profile(
            secrets, "apollo", account, "api_key"
        )
        if err:
            return err
        result = request_fn(
            "POST",
            "https://api.apollo.io/api/v1/mixed_people/search",
            headers=_apollo_headers(apollo_profile),
            json={"q_keywords": query, "page": 1, "per_page": clamp(max_results)},
        )
        return acct_result(aid, result)

    apollo_search_people.__name__ = "apollo_search_people"
    tools.append(
        attach(
            apollo_search_people,
            schema(
                "apollo_search_people",
                "Keyword-search people in Apollo's B2B database (e.g. 'VP "
                "engineering fintech Berlin').",
                {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "account": GEN_ACCOUNT_PROP,
                },
                ["query"],
            ),
            caps=["apollo", "read"],
        )
    )

    return tools


def _hunter_get(
    hunter_profile: dict[str, Any],
    path: str,
    params: dict[str, Any],
    *,
    request_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    return request_fn(
        "GET",
        f"https://api.hunter.io/v2/{path}",
        params={**params, "api_key": hunter_profile["api_key"]},
    )


def make_hunter_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build Hunter email-discovery tools."""
    del roots
    tools: list[Callable[..., Any]] = []

    def hunter_domain_search(
        domain: str, max_results: int = 10, account: str = ""
    ) -> dict[str, Any]:
        aid, hunter_profile, err = account_profile(
            secrets, "hunter", account, "api_key"
        )
        if err:
            return err
        result = _hunter_get(
            hunter_profile,
            "domain-search",
            {"domain": domain, "limit": clamp(max_results)},
            request_fn=request_fn,
        )
        return acct_result(aid, result)

    hunter_domain_search.__name__ = "hunter_domain_search"
    tools.append(
        attach(
            hunter_domain_search,
            schema(
                "hunter_domain_search",
                "Find published email addresses for a company domain (Hunter).",
                {
                    "domain": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "account": GEN_ACCOUNT_PROP,
                },
                ["domain"],
            ),
            caps=["hunter", "read"],
        )
    )

    def hunter_find_email(
        domain: str, first_name: str, last_name: str, account: str = ""
    ) -> dict[str, Any]:
        aid, hunter_profile, err = account_profile(
            secrets, "hunter", account, "api_key"
        )
        if err:
            return err
        result = _hunter_get(
            hunter_profile,
            "email-finder",
            {"domain": domain, "first_name": first_name, "last_name": last_name},
            request_fn=request_fn,
        )
        return acct_result(aid, result)

    hunter_find_email.__name__ = "hunter_find_email"
    tools.append(
        attach(
            hunter_find_email,
            schema(
                "hunter_find_email",
                "Find a person's most likely email address from their name and "
                "company domain (Hunter).",
                {
                    "domain": {"type": "string"},
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                    "account": GEN_ACCOUNT_PROP,
                },
                ["domain", "first_name", "last_name"],
            ),
            caps=["hunter", "read"],
        )
    )

    def hunter_verify_email(email: str, account: str = "") -> dict[str, Any]:
        aid, hunter_profile, err = account_profile(
            secrets, "hunter", account, "api_key"
        )
        if err:
            return err
        return acct_result(
            aid,
            _hunter_get(
                hunter_profile,
                "email-verifier",
                {"email": email},
                request_fn=request_fn,
            ),
        )

    hunter_verify_email.__name__ = "hunter_verify_email"
    tools.append(
        attach(
            hunter_verify_email,
            schema(
                "hunter_verify_email",
                "Check whether an email address is deliverable (Hunter).",
                {"email": {"type": "string"}, "account": GEN_ACCOUNT_PROP},
                ["email"],
            ),
            caps=["hunter", "read"],
        )
    )

    return tools


_CLOSE = "https://api.close.com/api/v1"


def _close_auth(close_profile: dict[str, Any]) -> tuple[str, str]:
    return (str(close_profile.get("api_key", "")), "")


def make_close_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build Close CRM tools."""
    del roots
    tools: list[Callable[..., Any]] = []

    def close_search_leads(query: str, max_results: int = 10) -> dict[str, Any]:
        close_profile, err = profile(secrets, "close", "api_key")
        if err:
            return err
        return request_fn(
            "GET",
            f"{_CLOSE}/lead/",
            auth=_close_auth(close_profile),
            params={"query": query, "_limit": clamp(max_results)},
        )

    close_search_leads.__name__ = "close_search_leads"
    tools.append(
        attach(
            close_search_leads,
            schema(
                "close_search_leads",
                'Search Close leads (supports Close\'s search syntax, e.g. "status:potential acme").',
                {"query": {"type": "string"}, "max_results": {"type": "integer"}},
                ["query"],
            ),
            caps=["close", "read"],
        )
    )

    def close_get_lead(lead_id: str) -> dict[str, Any]:
        close_profile, err = profile(secrets, "close", "api_key")
        if err:
            return err
        return request_fn(
            "GET", f"{_CLOSE}/lead/{quote(lead_id)}/", auth=_close_auth(close_profile)
        )

    close_get_lead.__name__ = "close_get_lead"
    tools.append(
        attach(
            close_get_lead,
            schema(
                "close_get_lead",
                "Read a Close lead (contacts, opportunities, addresses) by id.",
                {"lead_id": {"type": "string"}},
                ["lead_id"],
            ),
            caps=["close", "read"],
        )
    )

    def close_list_opportunities(
        lead_id: str = "", max_results: int = 10
    ) -> dict[str, Any]:
        close_profile, err = profile(secrets, "close", "api_key")
        if err:
            return err
        params: dict[str, Any] = {"_limit": clamp(max_results)}
        if lead_id:
            params["lead_id"] = lead_id
        return request_fn(
            "GET", f"{_CLOSE}/opportunity/", auth=_close_auth(close_profile), params=params
        )

    close_list_opportunities.__name__ = "close_list_opportunities"
    tools.append(
        attach(
            close_list_opportunities,
            schema(
                "close_list_opportunities",
                "List Close opportunities, optionally for one lead.",
                {"lead_id": {"type": "string"}, "max_results": {"type": "integer"}},
                [],
            ),
            caps=["close", "read"],
        )
    )

    def close_create_lead(
        name: str, contact_name: str = "", contact_email: str = ""
    ) -> dict[str, Any]:
        close_profile, err = profile(secrets, "close", "api_key")
        if err:
            return err
        body: dict[str, Any] = {"name": name}
        if contact_name or contact_email:
            contact: dict[str, Any] = {"name": contact_name}
            if contact_email:
                contact["emails"] = [{"email": contact_email}]
            body["contacts"] = [contact]
        return request_fn(
            "POST", f"{_CLOSE}/lead/", auth=_close_auth(close_profile), json=body
        )

    close_create_lead.__name__ = "close_create_lead"
    tools.append(
        attach(
            close_create_lead,
            schema(
                "close_create_lead",
                "Create a Close lead (company), optionally with one contact. Requires user approval.",
                {
                    "name": {"type": "string"},
                    "contact_name": {"type": "string"},
                    "contact_email": {"type": "string"},
                },
                ["name"],
            ),
            approval=True,
            caps=["close", "write"],
        )
    )

    def close_update_opportunity(
        opportunity_id: str, status_id: str = "", note: str = ""
    ) -> dict[str, Any]:
        close_profile, err = profile(secrets, "close", "api_key")
        if err:
            return err
        body: dict[str, Any] = {}
        if status_id:
            body["status_id"] = status_id
        if note:
            body["note"] = note
        if not body:
            return {"error": "nothing to update: pass status_id or note"}
        return request_fn(
            "PUT",
            f"{_CLOSE}/opportunity/{quote(opportunity_id)}/",
            auth=_close_auth(close_profile),
            json=body,
        )

    close_update_opportunity.__name__ = "close_update_opportunity"
    tools.append(
        attach(
            close_update_opportunity,
            schema(
                "close_update_opportunity",
                "Update a Close opportunity's status or note. Requires user approval.",
                {
                    "opportunity_id": {"type": "string"},
                    "status_id": {"type": "string"},
                    "note": {"type": "string"},
                },
                ["opportunity_id"],
            ),
            approval=True,
            caps=["close", "write"],
        )
    )

    def close_log_note(lead_id: str, note: str) -> dict[str, Any]:
        close_profile, err = profile(secrets, "close", "api_key")
        if err:
            return err
        return request_fn(
            "POST",
            f"{_CLOSE}/activity/note/",
            auth=_close_auth(close_profile),
            json={"lead_id": lead_id, "note": note},
        )

    close_log_note.__name__ = "close_log_note"
    tools.append(
        attach(
            close_log_note,
            schema(
                "close_log_note",
                "Log a note on a Close lead's timeline. Requires user approval.",
                {"lead_id": {"type": "string"}, "note": {"type": "string"}},
                ["lead_id", "note"],
            ),
            approval=True,
            caps=["close", "write"],
        )
    )

    return tools


def make_crm_analytics_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build all CRM/analytics tools in their legacy global order."""
    tools: list[Callable[..., Any]] = []
    for factory in (
        make_hubspot_tools,
        make_notion_tools,
        make_attio_tools,
        make_posthog_tools,
        make_mixpanel_tools,
        make_amplitude_tools,
        make_apollo_tools,
        make_hunter_tools,
        make_close_tools,
    ):
        tools.extend(factory(secrets, roots=roots, request_fn=request_fn))
    return tools


__all__ = [
    "make_amplitude_tools",
    "make_apollo_tools",
    "make_attio_tools",
    "make_close_tools",
    "make_crm_analytics_tools",
    "make_hubspot_tools",
    "make_hunter_tools",
    "make_mixpanel_tools",
    "make_notion_tools",
    "make_posthog_tools",
]
