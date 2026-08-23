"""Cloud router — sign-in, managed OAuth, gallery status."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, Request

from ..loopback_pages import _browser_page, _CONNECT_FAILED_DETAIL, _connector_title


def cloud_router(manager: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/v1/cloud/status")
    def cloud_status() -> dict[str, Any]:
        from ... import cloud
        from ...config import load_config

        return {
            "available": cloud.available(load_config()),
            **cloud.status(manager.secrets),
            "telemetry_enabled": cloud.telemetry_enabled(manager.secrets),
        }

    @router.post("/v1/cloud/telemetry")
    def cloud_telemetry(body: dict) -> dict[str, Any]:
        from ... import cloud

        return cloud.set_telemetry_enabled(
            manager.secrets, bool((body or {}).get("enabled", True))
        )

    @router.post("/v1/cloud/login")
    def cloud_login() -> dict[str, Any]:
        import webbrowser

        from ... import cloud
        from ...config import load_config

        out = cloud.begin_login(load_config())
        if not out.get("ok"):
            return out
        webbrowser.open(out["authorize_url"])
        return out

    @router.post("/v1/cloud/logout")
    def cloud_logout() -> dict[str, Any]:
        from ... import cloud

        return cloud.logout(manager.secrets)

    @router.get("/auth/callback")
    async def cloud_auth_callback(code: str = "", state: str = "", error: str = ""):
        from fastapi.responses import HTMLResponse

        from ... import cloud
        from ...config import load_config

        signin_failed_detail = (
            "Close this tab and try signing in again from Smallink."
        )
        if error:
            return HTMLResponse(
                _browser_page(
                    "Sign-in failed", signin_failed_detail, ok=False, error=error
                ),
                status_code=400,
            )
        result = await asyncio.to_thread(
            lambda: cloud.complete_login(manager.secrets, load_config(), code, state)
        )
        if not result.get("ok"):
            return HTMLResponse(
                _browser_page(
                    "Sign-in failed",
                    signin_failed_detail,
                    ok=False,
                    error=result.get("error", ""),
                ),
                status_code=400,
            )

        async def _restore_connections() -> None:
            try:
                out = await asyncio.to_thread(
                    lambda: cloud.sync_connections(manager.secrets, load_config())
                )
                if out.get("restored"):
                    await manager.refresh_gateway()
            except Exception:
                pass

        asyncio.get_running_loop().create_task(_restore_connections())
        return HTMLResponse(
            _browser_page(
                "Signed in",
                "You're signed in to Smallink Cloud. "
                "You can close this tab and return to Smallink.",
            )
        )

    @router.post("/v1/connectors/{name}/connect-managed")
    async def connector_connect_managed(
        name: str, body: Optional[dict] = None
    ) -> dict[str, Any]:
        import webbrowser

        from ... import cloud
        from ...config import load_config
        from ...connectors.descriptors import get_descriptor

        d = get_descriptor(name)
        if d is not None and d.managed_paused:
            return {
                "ok": False,
                "error": f"one-click connect for {d.title} is coming soon — connect manually for now",
            }
        access = str((body or {}).get("access") or "")
        flow = str((body or {}).get("flow") or "")
        out = await asyncio.to_thread(
            lambda: cloud.begin_managed_connect(
                manager.secrets, load_config(), name, access=access, flow=flow
            )
        )
        if out.get("ok"):
            webbrowser.open(out["authorize_url"])
        return out

    @router.post("/oauth/callback")
    async def managed_oauth_callback(request: Request) -> Any:
        from fastapi.responses import HTMLResponse

        from ... import cloud
        from ...connectors.setup import (
            managed_connect_connector,
            managed_connect_slack_install,
        )

        form = await request.form()
        data = {k: str(v) for k, v in form.items()}
        connector = data.get("connector", "")
        if not cloud.consume_managed_state(data.get("app_state", "")):
            return HTMLResponse(
                _browser_page(
                    "Connection failed",
                    _CONNECT_FAILED_DETAIL,
                    ok=False,
                    error="unknown or expired connection attempt",
                ),
                status_code=400,
            )
        if data.get("error"):
            return HTMLResponse(
                _browser_page(
                    "Connection failed",
                    _CONNECT_FAILED_DETAIL,
                    ok=False,
                    error=data["error"],
                ),
                status_code=400,
            )
        if connector == "github" and data.get("installation_id"):
            from ...connectors.github_installs import managed_connect_install

            result = managed_connect_install(manager.secrets, data)
            if result.get("ok"):
                await manager.refresh_gateway()
            if not result.get("ok"):
                return HTMLResponse(
                    _browser_page(
                        "Connection failed",
                        _CONNECT_FAILED_DETAIL,
                        ok=False,
                        error=result.get("error", ""),
                    ),
                    status_code=400,
                )
            return HTMLResponse(
                _browser_page(
                    "GitHub connected",
                    "You can close this tab and return to Smallink.",
                    connector="github",
                )
            )
        if not connector or not data.get("access_token"):
            return HTMLResponse(
                _browser_page(
                    "Connection failed",
                    _CONNECT_FAILED_DETAIL,
                    ok=False,
                    error="missing fields",
                ),
                status_code=400,
            )
        if connector == "slack" and data.get("team_id"):
            result = managed_connect_slack_install(manager.secrets, data)
            if result.get("ok"):
                await manager.refresh_gateway()
        elif connector == "gmail":
            from ...connectors import gmail_accounts

            result = gmail_accounts.managed_connect_account(
                manager.secrets, cloud.managed_profile_from_callback(data)
            )
        elif connector == "google_calendar":
            from ...connectors import gcal_accounts

            result = gcal_accounts.managed_connect_account(
                manager.secrets, cloud.managed_profile_from_callback(data)
            )
        elif connector == "hubspot" and data.get("hub_id"):
            from ...connectors import hubspot_portals

            profile = cloud.managed_profile_from_callback(data)
            profile["hub_id"] = data.get("hub_id", "")
            if data.get("sandbox"):
                profile["sandbox"] = True
            result = hubspot_portals.managed_connect_portal(manager.secrets, profile)
        else:
            result = managed_connect_connector(
                manager.secrets, connector, cloud.managed_profile_from_callback(data)
            )
        if not result.get("ok"):
            return HTMLResponse(
                _browser_page(
                    "Connection failed",
                    _CONNECT_FAILED_DETAIL,
                    ok=False,
                    error=result.get("error", ""),
                ),
                status_code=400,
            )
        return HTMLResponse(
            _browser_page(
                f"{_connector_title(connector)} connected",
                "You can close this tab and return to Smallink.",
                connector=connector,
            )
        )

    return router
