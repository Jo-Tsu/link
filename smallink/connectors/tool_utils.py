"""Shared helpers for connector tool modules.

Every connector tool file uses these for schema generation, metadata attachment,
HTTP calls, and profile resolution. Extracted from the monolithic integration_tools.py
to eliminate duplication across connector modules.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Callable, Optional
from urllib.parse import quote

import aisuite as ai

from ..secrets import SecretStore
from .tool_defs import approval_for_tool


def meta(
    name: str, *, approval: bool = False, capabilities: Optional[list[str]] = None
):
    """Build aisuite ToolMetadata for a connector tool."""
    return ai.ToolMetadata(
        name=name,
        category="connector",
        risk_level="medium" if approval else "low",
        capabilities=capabilities or ["integration"],
        requires_approval=approval,
    )


def schema(
    name: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    """Build an OpenAI-format function tool schema."""
    return {
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


def attach(
    fn: Callable[..., Any],
    tool_schema: dict[str, Any],
    *,
    approval: bool = True,
    caps: Optional[list[str]] = None,
):
    """Attach schema and metadata to a tool function."""
    name = tool_schema["function"]["name"]
    approval = approval_for_tool(name, default=approval)
    fn.__link_schema__ = tool_schema
    fn.__aisuite_tool_metadata__ = meta(name, approval=approval, capabilities=caps)
    fn.__doc__ = tool_schema["function"]["description"]
    return fn


def profile(
    secrets: SecretStore, name: str, *keys: str
) -> tuple[Optional[dict[str, Any]], Optional[dict[str, str]]]:
    """(profile_dict, err) for a single-account connector."""
    prof = secrets.get(f"{name}:default") or {}
    if prof.get("managed"):
        from ..cloud import ensure_fresh_connector_token
        from ..config import load_config

        ensure_fresh_connector_token(secrets, load_config(), name)
        prof = secrets.get(f"{name}:default") or {}
    missing = [k for k in keys if not prof.get(k)]
    if missing:
        return None, {"error": f"{name} is not connected; missing {', '.join(missing)}"}
    return prof, None


def account_profile(
    secrets: SecretStore, connector: str, account: str = "", *keys: str
) -> tuple[str, Optional[dict[str, Any]], Optional[dict[str, str]]]:
    """(account_id, profile, err) for multi-account connectors."""
    from . import accounts as _accounts

    account_id, key, prof = _accounts.resolve(secrets, connector, account)
    if prof is None:
        hint = (
            f"no {connector} account matching {account!r}"
            if account
            else f"{connector} is not connected"
        )
        return "", None, {"error": hint}
    if prof.get("managed"):
        from ..cloud import ensure_fresh_connector_token
        from ..config import load_config

        ensure_fresh_connector_token(secrets, load_config(), connector, profile_key=key)
        prof = secrets.get(key) or prof
    missing = [k for k in keys if not prof.get(k)]
    if missing:
        return (
            account_id,
            None,
            {"error": f"{connector} is not connected; missing {', '.join(missing)}"},
        )
    return account_id, prof, None


def acct_result(account_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Stamp which account served a tool call."""
    if isinstance(result, dict) and account_id:
        return {"account": account_id, **result}
    return result


GEN_ACCOUNT_PROP = {
    "type": "string",
    "description": "Which connected account to use (default account when empty)",
}


def request(
    method: str, url: str, *, headers=None, params=None, json=None, auth=None
) -> dict[str, Any]:
    """Make an HTTP request, returning {ok, data} or {error}."""
    try:
        import httpx

        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            resp = client.request(
                method, url, headers=headers, params=params, json=json, auth=auth
            )
            ctype = resp.headers.get("content-type", "")
            data: Any = resp.json() if "json" in ctype.lower() else resp.text
            if resp.status_code >= 400:
                return {"error": f"HTTP {resp.status_code}", "details": data}
            return {"ok": True, "data": data}
    except Exception as exc:
        return {"error": str(exc)}


def bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def clamp(n: Any, default: int = 10, ceiling: int = 20) -> int:
    """Clamp an integer to [1, ceiling]."""
    return max(1, min(int(n or default), ceiling))


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag.lower() in self._SKIP:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._SKIP:
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = data.strip()
        if text:
            self.parts.append(text)


def html_to_text(html: str) -> str:
    """Convert HTML to plain text."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    return re.sub(r"\n{3,}", "\n\n", "\n".join(parser.parts))
