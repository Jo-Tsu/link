"""File storage, accounting, messaging, and Google Drive connector tools."""

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

Tool = Callable[..., Any]
RequestFn = Callable[..., dict[str, Any]]


def _dropbox_path(path: str) -> str:
    path = (path or "").strip()
    if path and not path.startswith("/"):
        path = "/" + path
    return path


def make_dropbox_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: RequestFn = request,
) -> list[Tool]:
    """Build Dropbox connector tools in their legacy order."""
    tools: list[Tool] = []

    def dropbox_search(query: str, max_results: int = 10) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "dropbox", "access_token")
        if err:
            return err
        return request_fn(
            "POST",
            "https://api.dropboxapi.com/2/files/search_v2",
            headers=bearer_headers(connector_profile["access_token"]),
            json={"query": query, "options": {"max_results": clamp(max_results)}},
        )

    dropbox_search.__name__ = "dropbox_search"
    tools.append(
        attach(
            dropbox_search,
            schema(
                "dropbox_search",
                "Search Dropbox files and folders by name/content.",
                {"query": {"type": "string"}, "max_results": {"type": "integer"}},
                ["query"],
            ),
            caps=["dropbox", "read"],
        )
    )

    def dropbox_list_folder(path: str = "") -> dict[str, Any]:
        connector_profile, err = profile(secrets, "dropbox", "access_token")
        if err:
            return err
        return request_fn(
            "POST",
            "https://api.dropboxapi.com/2/files/list_folder",
            headers=bearer_headers(connector_profile["access_token"]),
            json={"path": _dropbox_path(path)},
        )

    dropbox_list_folder.__name__ = "dropbox_list_folder"
    tools.append(
        attach(
            dropbox_list_folder,
            schema(
                "dropbox_list_folder",
                "List a Dropbox folder. Empty path is the root.",
                {"path": {"type": "string"}},
                [],
            ),
            caps=["dropbox", "read"],
        )
    )

    def dropbox_read_file(path: str, max_chars: int = 20000) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "dropbox", "access_token")
        if err:
            return err
        out = request_fn(
            "POST",
            "https://content.dropboxapi.com/2/files/download",
            headers={
                "Authorization": f"Bearer {connector_profile['access_token']}",
                "Dropbox-API-Arg": json.dumps({"path": _dropbox_path(path)}),
            },
        )
        if "error" in out:
            return out
        text = out["data"] if isinstance(out["data"], str) else str(out["data"])
        cap = max(1, min(int(max_chars or 20000), 100000))
        return {"path": path, "text": text[:cap], "truncated": len(text) > cap}

    dropbox_read_file.__name__ = "dropbox_read_file"
    tools.append(
        attach(
            dropbox_read_file,
            schema(
                "dropbox_read_file",
                "Read a text file from Dropbox by path.",
                {"path": {"type": "string"}, "max_chars": {"type": "integer"}},
                ["path"],
            ),
            caps=["dropbox", "read"],
        )
    )

    return tools


def make_box_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: RequestFn = request,
) -> list[Tool]:
    """Build Box connector tools in their legacy order."""
    tools: list[Tool] = []

    def box_search(query: str, max_results: int = 10) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "box", "access_token")
        if err:
            return err
        return request_fn(
            "GET",
            "https://api.box.com/2.0/search",
            headers=bearer_headers(connector_profile["access_token"]),
            params={"query": query, "limit": clamp(max_results)},
        )

    box_search.__name__ = "box_search"
    tools.append(
        attach(
            box_search,
            schema(
                "box_search",
                "Search Box files and folders.",
                {"query": {"type": "string"}, "max_results": {"type": "integer"}},
                ["query"],
            ),
            caps=["box", "read"],
        )
    )

    def box_list_folder(folder_id: str = "0") -> dict[str, Any]:
        connector_profile, err = profile(secrets, "box", "access_token")
        if err:
            return err
        return request_fn(
            "GET",
            f"https://api.box.com/2.0/folders/{folder_id}/items",
            headers=bearer_headers(connector_profile["access_token"]),
        )

    box_list_folder.__name__ = "box_list_folder"
    tools.append(
        attach(
            box_list_folder,
            schema(
                "box_list_folder",
                "List items in a Box folder. Folder '0' is the root.",
                {"folder_id": {"type": "string"}},
                [],
            ),
            caps=["box", "read"],
        )
    )

    def box_read_file(file_id: str, max_chars: int = 20000) -> dict[str, Any]:
        connector_profile, err = profile(secrets, "box", "access_token")
        if err:
            return err
        out = request_fn(
            "GET",
            f"https://api.box.com/2.0/files/{file_id}/content",
            headers=bearer_headers(connector_profile["access_token"]),
        )
        if "error" in out:
            return out
        text = out["data"] if isinstance(out["data"], str) else str(out["data"])
        cap = max(1, min(int(max_chars or 20000), 100000))
        return {"file_id": file_id, "text": text[:cap], "truncated": len(text) > cap}

    box_read_file.__name__ = "box_read_file"
    tools.append(
        attach(
            box_read_file,
            schema(
                "box_read_file",
                "Read a text file from Box by file ID.",
                {"file_id": {"type": "string"}, "max_chars": {"type": "integer"}},
                ["file_id"],
            ),
            caps=["box", "read"],
        )
    )

    return tools


def _qbo_base(connector_profile: dict[str, Any]) -> str:
    env = str(connector_profile.get("environment", "")).lower()
    host = (
        "sandbox-quickbooks.api.intuit.com"
        if env.startswith("sand")
        else "quickbooks.api.intuit.com"
    )
    return f"https://{host}/v3/company/{connector_profile['realm_id']}"


def make_quickbooks_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: RequestFn = request,
) -> list[Tool]:
    """Build QuickBooks connector tools in their legacy order."""
    tools: list[Tool] = []

    def quickbooks_query(query: str, max_results: int = 10) -> dict[str, Any]:
        connector_profile, err = profile(
            secrets, "quickbooks", "access_token", "realm_id"
        )
        if err:
            return err
        q = query.strip()
        if "maxresults" not in q.lower():
            q = f"{q} MAXRESULTS {clamp(max_results, ceiling=100)}"
        return request_fn(
            "GET",
            f"{_qbo_base(connector_profile)}/query",
            headers=bearer_headers(connector_profile["access_token"]),
            params={"query": q},
        )

    quickbooks_query.__name__ = "quickbooks_query"
    tools.append(
        attach(
            quickbooks_query,
            schema(
                "quickbooks_query",
                "Run a QuickBooks Online query, e.g. \"SELECT * FROM Invoice WHERE TotalAmt > '100'\". "
                "Entities include Customer, Invoice, Bill, Payment, Account, Vendor.",
                {"query": {"type": "string"}, "max_results": {"type": "integer"}},
                ["query"],
            ),
            caps=["quickbooks", "read"],
        )
    )

    def quickbooks_list_customers(max_results: int = 10) -> dict[str, Any]:
        connector_profile, err = profile(
            secrets, "quickbooks", "access_token", "realm_id"
        )
        if err:
            return err
        return request_fn(
            "GET",
            f"{_qbo_base(connector_profile)}/query",
            headers=bearer_headers(connector_profile["access_token"]),
            params={
                "query": f"SELECT * FROM Customer MAXRESULTS {clamp(max_results)}"
            },
        )

    quickbooks_list_customers.__name__ = "quickbooks_list_customers"
    tools.append(
        attach(
            quickbooks_list_customers,
            schema(
                "quickbooks_list_customers",
                "List QuickBooks customers.",
                {"max_results": {"type": "integer"}},
                [],
            ),
            caps=["quickbooks", "read"],
        )
    )

    def quickbooks_list_invoices(max_results: int = 10) -> dict[str, Any]:
        connector_profile, err = profile(
            secrets, "quickbooks", "access_token", "realm_id"
        )
        if err:
            return err
        return request_fn(
            "GET",
            f"{_qbo_base(connector_profile)}/query",
            headers=bearer_headers(connector_profile["access_token"]),
            params={
                "query": "SELECT * FROM Invoice ORDERBY TxnDate DESC "
                f"MAXRESULTS {clamp(max_results)}"
            },
        )

    quickbooks_list_invoices.__name__ = "quickbooks_list_invoices"
    tools.append(
        attach(
            quickbooks_list_invoices,
            schema(
                "quickbooks_list_invoices",
                "List recent QuickBooks invoices.",
                {"max_results": {"type": "integer"}},
                [],
            ),
            caps=["quickbooks", "read"],
        )
    )

    def quickbooks_get_report(
        report: str, start_date: str = "", end_date: str = ""
    ) -> dict[str, Any]:
        connector_profile, err = profile(
            secrets, "quickbooks", "access_token", "realm_id"
        )
        if err:
            return err
        params: dict[str, Any] = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return request_fn(
            "GET",
            f"{_qbo_base(connector_profile)}/reports/{quote(report, safe='')}",
            headers=bearer_headers(connector_profile["access_token"]),
            params=params or None,
        )

    quickbooks_get_report.__name__ = "quickbooks_get_report"
    tools.append(
        attach(
            quickbooks_get_report,
            schema(
                "quickbooks_get_report",
                "Run a QuickBooks report such as ProfitAndLoss, BalanceSheet, CashFlow, "
                "AgedReceivables. Dates are YYYY-MM-DD.",
                {
                    "report": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                },
                ["report"],
            ),
            caps=["quickbooks", "read"],
        )
    )

    return tools


def make_whatsapp_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: RequestFn = request,
) -> list[Tool]:
    """Build WhatsApp connector tools in their legacy order."""
    tools: list[Tool] = []

    def whatsapp_send_message(to: str, text: str) -> dict[str, Any]:
        connector_profile, err = profile(
            secrets, "whatsapp", "access_token", "phone_number_id"
        )
        if err:
            return err
        return request_fn(
            "POST",
            f"https://graph.facebook.com/v21.0/{connector_profile['phone_number_id']}/messages",
            headers=bearer_headers(connector_profile["access_token"]),
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text[:4096]},
            },
        )

    whatsapp_send_message.__name__ = "whatsapp_send_message"
    tools.append(
        attach(
            whatsapp_send_message,
            schema(
                "whatsapp_send_message",
                "Send a WhatsApp text message. Only delivered if the recipient messaged "
                "this number within the last 24 hours; otherwise use "
                "whatsapp_send_template. Requires user approval.",
                {"to": {"type": "string"}, "text": {"type": "string"}},
                ["to", "text"],
            ),
            approval=True,
            caps=["whatsapp", "write"],
        )
    )

    def whatsapp_send_template(
        to: str, template_name: str, language_code: str = "en_US"
    ) -> dict[str, Any]:
        connector_profile, err = profile(
            secrets, "whatsapp", "access_token", "phone_number_id"
        )
        if err:
            return err
        return request_fn(
            "POST",
            f"https://graph.facebook.com/v21.0/{connector_profile['phone_number_id']}/messages",
            headers=bearer_headers(connector_profile["access_token"]),
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": language_code},
                },
            },
        )

    whatsapp_send_template.__name__ = "whatsapp_send_template"
    tools.append(
        attach(
            whatsapp_send_template,
            schema(
                "whatsapp_send_template",
                "Send a pre-approved WhatsApp template message (works outside the "
                "24-hour service window). Requires user approval.",
                {
                    "to": {"type": "string"},
                    "template_name": {"type": "string"},
                    "language_code": {"type": "string"},
                },
                ["to", "template_name"],
            ),
            approval=True,
            caps=["whatsapp", "write"],
        )
    )

    return tools


_DRIVE = "https://www.googleapis.com/drive/v3"
_DRIVE_FIELDS = "files(id,name,mimeType,modifiedTime,size,webViewLink)"
_DRIVE_EXPORTS = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}


def _google_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _drive_quote(term: str) -> str:
    return term.replace("\\", "\\\\").replace("'", "\\'")


def make_drive_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: RequestFn = request,
) -> list[Tool]:
    """Build read-only Google Drive tools in their legacy order."""
    tools: list[Tool] = []

    def drive_search_files(
        query: str, max_results: int = 10, account: str = ""
    ) -> dict[str, Any]:
        aid, connector_profile, err = account_profile(
            secrets, "google_drive", account, "access_token"
        )
        if err:
            return err
        q = _drive_quote(query)
        return acct_result(
            aid,
            request_fn(
                "GET",
                f"{_DRIVE}/files",
                headers=_google_headers(connector_profile["access_token"]),
                params={
                    "q": f"(name contains '{q}' or fullText contains '{q}') and trashed=false",
                    "pageSize": clamp(max_results),
                    "fields": _DRIVE_FIELDS,
                },
            ),
        )

    drive_search_files.__name__ = "drive_search_files"
    tools.append(
        attach(
            drive_search_files,
            schema(
                "drive_search_files",
                "Search Google Drive files by name or content.",
                {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "account": GEN_ACCOUNT_PROP,
                },
                ["query"],
            ),
            caps=["google_drive", "read"],
        )
    )

    def drive_list_folder(
        folder_id: str = "root", max_results: int = 20, account: str = ""
    ) -> dict[str, Any]:
        aid, connector_profile, err = account_profile(
            secrets, "google_drive", account, "access_token"
        )
        if err:
            return err
        return acct_result(
            aid,
            request_fn(
                "GET",
                f"{_DRIVE}/files",
                headers=_google_headers(connector_profile["access_token"]),
                params={
                    "q": f"'{_drive_quote(folder_id)}' in parents and trashed=false",
                    "pageSize": clamp(max_results, default=20, ceiling=50),
                    "fields": _DRIVE_FIELDS,
                },
            ),
        )

    drive_list_folder.__name__ = "drive_list_folder"
    tools.append(
        attach(
            drive_list_folder,
            schema(
                "drive_list_folder",
                "List a Google Drive folder's contents ('root' for My Drive).",
                {
                    "folder_id": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "account": GEN_ACCOUNT_PROP,
                },
                [],
            ),
            caps=["google_drive", "read"],
        )
    )

    def drive_read_file(
        file_id: str, max_chars: int = 20000, account: str = ""
    ) -> dict[str, Any]:
        aid, connector_profile, err = account_profile(
            secrets, "google_drive", account, "access_token"
        )
        if err:
            return err
        headers = _google_headers(connector_profile["access_token"])
        meta = request_fn(
            "GET",
            f"{_DRIVE}/files/{quote(file_id)}",
            headers=headers,
            params={"fields": "id,name,mimeType,size"},
        )
        if not meta.get("ok"):
            return acct_result(aid, meta)
        info = meta.get("data") or {}
        mime = str(info.get("mimeType", ""))
        export_mime = _DRIVE_EXPORTS.get(mime)
        if export_mime:
            body = request_fn(
                "GET",
                f"{_DRIVE}/files/{quote(file_id)}/export",
                headers=headers,
                params={"mimeType": export_mime},
            )
        elif mime.startswith("application/vnd.google-apps"):
            return acct_result(
                aid, {"error": f"cannot read {mime} as text", "file": info}
            )
        else:
            body = request_fn(
                "GET",
                f"{_DRIVE}/files/{quote(file_id)}",
                headers=headers,
                params={"alt": "media"},
            )
        if not body.get("ok"):
            return acct_result(aid, body)
        text = body.get("data")
        if not isinstance(text, str):
            text = json.dumps(text)
        return acct_result(
            aid,
            {
                "ok": True,
                "file": info,
                "content": text[: max(1, int(max_chars))],
                "truncated": len(text) > max_chars,
            },
        )

    drive_read_file.__name__ = "drive_read_file"
    tools.append(
        attach(
            drive_read_file,
            schema(
                "drive_read_file",
                "Read a Drive file as text (Docs/Sheets/Slides export; other text files download).",
                {
                    "file_id": {"type": "string"},
                    "max_chars": {"type": "integer"},
                    "account": GEN_ACCOUNT_PROP,
                },
                ["file_id"],
            ),
            caps=["google_drive", "read"],
        )
    )

    return tools


def make_files_business_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: RequestFn = request,
) -> list[Tool]:
    """Build all tools in the order of their legacy connector groups."""
    tools: list[Tool] = []
    for factory in (
        make_dropbox_tools,
        make_box_tools,
        make_quickbooks_tools,
        make_whatsapp_tools,
        make_drive_tools,
    ):
        tools.extend(factory(secrets, roots=roots, request_fn=request_fn))
    return tools
