"""Gmail and Google Calendar connector tools."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any, Callable, Optional

from ...secrets import SecretStore
from ..tool_utils import attach, request, schema


def _google_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


def _gmail_profile(
    secrets: SecretStore, account: str = ""
) -> tuple[str, Optional[dict[str, Any]], Optional[dict[str, str]]]:
    """Resolve a Gmail account and refresh its managed token in place."""
    from .. import gmail_accounts

    email, key, profile = gmail_accounts.resolve(secrets, account)
    if profile is None:
        hint = (
            f"no gmail account matching {account!r}"
            if account
            else "gmail is not connected"
        )
        return "", None, {"error": hint}
    if profile.get("managed"):
        from ...cloud import ensure_fresh_connector_token
        from ...config import load_config

        ensure_fresh_connector_token(secrets, load_config(), "gmail", profile_key=key)
        profile = secrets.get(key) or profile
    if not profile.get("access_token"):
        return "", None, {"error": f"gmail account {email} has no usable token"}
    return email, profile, None


def _gcal_profile(
    secrets: SecretStore, account: str = ""
) -> tuple[str, Optional[dict[str, Any]], Optional[dict[str, str]]]:
    """Resolve a Google Calendar account and refresh its token in place."""
    from .. import gcal_accounts

    email, key, profile = gcal_accounts.resolve(secrets, account)
    if profile is None:
        hint = (
            f"no google calendar account matching {account!r}"
            if account
            else "google calendar is not connected"
        )
        return "", None, {"error": hint}
    if profile.get("managed"):
        from ...cloud import ensure_fresh_connector_token
        from ...config import load_config

        ensure_fresh_connector_token(
            secrets, load_config(), "google_calendar", profile_key=key
        )
        profile = secrets.get(key) or profile
    if not profile.get("access_token"):
        return (
            "",
            None,
            {"error": f"google calendar account {email} has no usable token"},
        )
    return email, profile, None


def _gmail_filters(secrets: SecretStore) -> Optional[dict[str, list[str]]]:
    from .. import gmail_accounts

    filters = gmail_accounts.get_filters(secrets)
    return filters if (filters["senders"] or filters["labels"]) else None


def _gmail_from_address(message: dict[str, Any]) -> str:
    from email.utils import parseaddr

    for header in (message.get("payload") or {}).get("headers") or []:
        if str(header.get("name", "")).lower() == "from":
            return parseaddr(str(header.get("value") or ""))[1]
    return ""


def _gmail_label_map(
    token: str, request_fn: Callable[..., dict[str, Any]]
) -> dict[str, str]:
    """Return label id to name mappings for filter enforcement."""
    response = request_fn(
        "GET",
        "https://gmail.googleapis.com/gmail/v1/users/me/labels",
        headers=_google_headers(token),
    )
    if not response.get("ok"):
        return {}
    labels = (response.get("data") or {}).get("labels") or []
    return {
        str(label.get("id") or ""): str(label.get("name") or "")
        for label in labels
    }


def _gmail_is_hidden(
    message: dict[str, Any],
    filters: dict[str, list[str]],
    label_map: dict[str, str],
) -> bool:
    from ..gmail_accounts import sender_matches

    if filters["senders"] and sender_matches(
        _gmail_from_address(message), filters["senders"]
    ):
        return True
    if filters["labels"]:
        wanted = {name.lower() for name in filters["labels"]}
        for label_id in message.get("labelIds") or []:
            if (
                label_map.get(str(label_id), "").lower() in wanted
                or str(label_id).lower() in wanted
            ):
                return True
    return False


def make_gmail_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build Gmail connector tools."""
    tools: list[Callable[..., Any]] = []
    account_prop = {
        "type": "string",
        "description": "Mailbox email to use; omit for the default account.",
    }

    def gmail_search_messages(
        query: str, max_results: int = 10, account: str = ""
    ) -> dict[str, Any]:
        email, profile, err = _gmail_profile(secrets, account)
        if err:
            return err
        token = profile["access_token"]
        result = request_fn(
            "GET",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers=_google_headers(token),
            params={"q": query, "maxResults": max(1, min(int(max_results or 10), 20))},
        )
        filters = _gmail_filters(secrets)
        if result.get("ok") and filters:
            # Matching hits are silently omitted. The count is only exposed to
            # the user-facing tool card and audit through the display sidecar.
            data = dict(result.get("data") or {})
            label_map = (
                _gmail_label_map(token, request_fn) if filters["labels"] else {}
            )
            kept, hidden = [], 0
            for message in data.get("messages") or []:
                metadata = request_fn(
                    "GET",
                    "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
                    f"{message.get('id')}",
                    headers=_google_headers(token),
                    params={"format": "metadata", "metadataHeaders": "From"},
                )
                detail = metadata.get("data") if metadata.get("ok") else None
                # Fail open if metadata cannot be read; a direct read enforces
                # the filters again before any message content is returned.
                if isinstance(detail, dict) and _gmail_is_hidden(
                    detail, filters, label_map
                ):
                    hidden += 1
                else:
                    kept.append(message)
            if hidden:
                data["messages"] = kept
                if isinstance(data.get("resultSizeEstimate"), int):
                    data["resultSizeEstimate"] = max(
                        0, data["resultSizeEstimate"] - hidden
                    )
                result = {
                    "ok": True,
                    "data": data,
                    "_display": {
                        "hidden_by_filters": hidden,
                        "connector": "gmail",
                    },
                }
        if result.get("ok"):
            result["account"] = email
        return result

    gmail_search_messages.__name__ = "gmail_search_messages"
    tools.append(
        attach(
            gmail_search_messages,
            schema(
                "gmail_search_messages",
                "Search Gmail messages using Gmail query syntax.",
                {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "account": account_prop,
                },
                ["query"],
            ),
            caps=["gmail", "read"],
        )
    )

    def gmail_get_message(message_id: str, account: str = "") -> dict[str, Any]:
        email, profile, err = _gmail_profile(secrets, account)
        if err:
            return err
        token = profile["access_token"]
        result = request_fn(
            "GET",
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
            headers=_google_headers(token),
            params={"format": "full"},
        )
        filters = _gmail_filters(secrets)
        if result.get("ok") and filters:
            data = result.get("data") or {}
            label_map = (
                _gmail_label_map(token, request_fn) if filters["labels"] else {}
            )
            if isinstance(data, dict) and _gmail_is_hidden(data, filters, label_map):
                return {
                    "error": "HTTP 404",
                    "details": {"error": {"code": 404, "message": "Not Found"}},
                    "_display": {
                        "hidden_by_filters": 1,
                        "connector": "gmail",
                    },
                }
        if result.get("ok"):
            result["account"] = email
        return result

    gmail_get_message.__name__ = "gmail_get_message"
    tools.append(
        attach(
            gmail_get_message,
            schema(
                "gmail_get_message",
                "Read a Gmail message by ID.",
                {"message_id": {"type": "string"}, "account": account_prop},
                ["message_id"],
            ),
            caps=["gmail", "read"],
        )
    )

    def gmail_send_email(
        to: str, subject: str, body: str, cc: str = "", account: str = ""
    ) -> dict[str, Any]:
        email, profile, err = _gmail_profile(secrets, account)
        if err:
            return err
        message = EmailMessage()
        message["To"], message["Subject"] = to, subject
        if cc:
            message["Cc"] = cc
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
        result = request_fn(
            "POST",
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers=_google_headers(profile["access_token"]),
            json={"raw": raw},
        )
        if result.get("ok"):
            result["account"] = email
        return result

    gmail_send_email.__name__ = "gmail_send_email"
    tools.append(
        attach(
            gmail_send_email,
            schema(
                "gmail_send_email",
                "Send an email through Gmail. Requires user approval; the "
                "`account` argument names the sending mailbox on the approval card.",
                {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "cc": {"type": "string"},
                    "account": account_prop,
                },
                ["to", "subject", "body"],
            ),
            approval=True,
            caps=["gmail", "write"],
        )
    )

    return tools


def make_gcal_tools(
    secrets: SecretStore,
    *,
    roots: Optional[list[Any]] = None,
    request_fn: Callable[..., dict[str, Any]] = request,
) -> list[Callable[..., Any]]:
    """Build Google Calendar connector tools."""
    tools: list[Callable[..., Any]] = []
    account_prop = {
        "type": "string",
        "description": "Google account email to use; omit for the default account.",
    }

    def gcal_result(email: str, result: dict[str, Any]) -> dict[str, Any]:
        if result.get("ok"):
            result["account"] = email
        return result

    def gcal_list_events(
        calendar_id: str = "primary",
        time_min: str = "",
        time_max: str = "",
        max_results: int = 10,
        account: str = "",
    ) -> dict[str, Any]:
        email, profile, err = _gcal_profile(secrets, account)
        if err:
            return err
        params: dict[str, Any] = {
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": max(1, min(int(max_results or 10), 20)),
        }
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        return gcal_result(
            email,
            request_fn(
                "GET",
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
                headers=_google_headers(profile["access_token"]),
                params=params,
            ),
        )

    gcal_list_events.__name__ = "gcal_list_events"
    tools.append(
        attach(
            gcal_list_events,
            schema(
                "gcal_list_events",
                "List Google Calendar events. time_min/time_max should be RFC3339 timestamps when provided.",
                {
                    "calendar_id": {"type": "string"},
                    "time_min": {"type": "string"},
                    "time_max": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "account": account_prop,
                },
                [],
            ),
            caps=["calendar", "read"],
        )
    )

    def gcal_free_busy(
        time_min: str,
        time_max: str,
        calendars: str = "primary",
        timezone: str = "UTC",
        account: str = "",
    ) -> dict[str, Any]:
        email, profile, err = _gcal_profile(secrets, account)
        if err:
            return err
        items = [
            {"id": calendar.strip()}
            for calendar in str(calendars or "primary").split(",")
            if calendar.strip()
        ]
        return gcal_result(
            email,
            request_fn(
                "POST",
                "https://www.googleapis.com/calendar/v3/freeBusy",
                headers=_google_headers(profile["access_token"]),
                json={
                    "timeMin": time_min,
                    "timeMax": time_max,
                    "timeZone": timezone,
                    "items": items,
                },
            ),
        )

    gcal_free_busy.__name__ = "gcal_free_busy"
    tools.append(
        attach(
            gcal_free_busy,
            schema(
                "gcal_free_busy",
                "Look up busy intervals (availability) for one or more calendars. "
                "time_min/time_max are RFC3339 timestamps; calendars is a comma-separated list of calendar ids.",
                {
                    "time_min": {"type": "string"},
                    "time_max": {"type": "string"},
                    "calendars": {"type": "string"},
                    "timezone": {"type": "string"},
                    "account": account_prop,
                },
                ["time_min", "time_max"],
            ),
            caps=["calendar", "read"],
        )
    )

    def gcal_create_event(
        summary: str,
        start: str,
        end: str,
        calendar_id: str = "primary",
        timezone: str = "UTC",
        description: str = "",
        account: str = "",
    ) -> dict[str, Any]:
        email, profile, err = _gcal_profile(secrets, account)
        if err:
            return err
        payload = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start, "timeZone": timezone},
            "end": {"dateTime": end, "timeZone": timezone},
        }
        return gcal_result(
            email,
            request_fn(
                "POST",
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
                headers=_google_headers(profile["access_token"]),
                json=payload,
            ),
        )

    gcal_create_event.__name__ = "gcal_create_event"
    tools.append(
        attach(
            gcal_create_event,
            schema(
                "gcal_create_event",
                "Create a Google Calendar event. Requires user approval.",
                {
                    "summary": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "calendar_id": {"type": "string"},
                    "timezone": {"type": "string"},
                    "description": {"type": "string"},
                    "account": account_prop,
                },
                ["summary", "start", "end"],
            ),
            approval=True,
            caps=["calendar", "write"],
        )
    )

    def gcal_update_event(
        event_id: str,
        calendar_id: str = "primary",
        summary: str = "",
        start: str = "",
        end: str = "",
        timezone: str = "UTC",
        description: str = "",
        account: str = "",
    ) -> dict[str, Any]:
        email, profile, err = _gcal_profile(secrets, account)
        if err:
            return err
        payload: dict[str, Any] = {}
        if summary:
            payload["summary"] = summary
        if description:
            payload["description"] = description
        if start:
            payload["start"] = {"dateTime": start, "timeZone": timezone}
        if end:
            payload["end"] = {"dateTime": end, "timeZone": timezone}
        if not payload:
            return {
                "error": "nothing to update — pass summary, description, start, or end"
            }
        return gcal_result(
            email,
            request_fn(
                "PATCH",
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}",
                headers=_google_headers(profile["access_token"]),
                json=payload,
            ),
        )

    gcal_update_event.__name__ = "gcal_update_event"
    tools.append(
        attach(
            gcal_update_event,
            schema(
                "gcal_update_event",
                "Update fields of a Google Calendar event (only the provided fields change). Requires user approval.",
                {
                    "event_id": {"type": "string"},
                    "calendar_id": {"type": "string"},
                    "summary": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "timezone": {"type": "string"},
                    "description": {"type": "string"},
                    "account": account_prop,
                },
                ["event_id"],
            ),
            approval=True,
            caps=["calendar", "write"],
        )
    )

    def gcal_delete_event(
        event_id: str, calendar_id: str = "primary", account: str = ""
    ) -> dict[str, Any]:
        email, profile, err = _gcal_profile(secrets, account)
        if err:
            return err
        return gcal_result(
            email,
            request_fn(
                "DELETE",
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}",
                headers=_google_headers(profile["access_token"]),
            ),
        )

    gcal_delete_event.__name__ = "gcal_delete_event"
    tools.append(
        attach(
            gcal_delete_event,
            schema(
                "gcal_delete_event",
                "Delete a Google Calendar event. Requires user approval.",
                {
                    "event_id": {"type": "string"},
                    "calendar_id": {"type": "string"},
                    "account": account_prop,
                },
                ["event_id"],
            ),
            approval=True,
            caps=["calendar", "write"],
        )
    )

    return tools
