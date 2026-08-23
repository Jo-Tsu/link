"""Settings router — model config, providers, web search, nav, PDF, surfaces."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

from ..services.settings import SettingsService


def settings_router(settings: SettingsService) -> APIRouter:
    router = APIRouter()

    # -- model providers (OpenAI, Ollama, ...) ----------------------------------
    @router.get("/v1/providers")
    def providers_get() -> list[dict[str, Any]]:
        return settings.get_providers()

    @router.post("/v1/providers")
    def providers_set(body: dict) -> dict[str, Any]:
        name = (body or {}).get("name", "")
        if not name:
            return {"ok": False, "error": "name required"}
        return settings.set_provider(name, (body or {}).get("fields"))

    @router.delete("/v1/providers/{name}")
    def providers_remove(name: str) -> dict[str, Any]:
        return settings.remove_provider(name)

    @router.post("/v1/providers/verify")
    async def providers_verify(body: dict) -> dict[str, Any]:
        name = (body or {}).get("name", "") or "openai"
        return await asyncio.to_thread(
            settings.verify_provider, name, (body or {}).get("fields")
        )

    # -- web search -------------------------------------------------------------
    @router.get("/v1/web-search")
    def web_search_get() -> dict[str, Any]:
        return settings.get_web_search()

    @router.post("/v1/web-search")
    def web_search_set(body: dict) -> dict[str, Any]:
        provider = (body or {}).get("provider", "")
        if not provider:
            return {"ok": False, "error": "provider required"}
        return settings.set_web_search(provider, (body or {}).get("api_key"))

    # -- settings (model API key) -----------------------------------------------
    @router.get("/v1/settings")
    def settings_get() -> dict[str, Any]:
        return settings.get_settings()

    @router.post("/v1/settings/model-key")
    def settings_set_model_key(body: dict) -> dict[str, Any]:
        return settings.set_model_key((body or {}).get("api_key", ""))

    @router.post("/v1/settings/default-model")
    def settings_set_default_model(body: dict) -> dict[str, Any]:
        return settings.set_default_model((body or {}).get("model", ""))

    @router.post("/v1/settings/models/add")
    def settings_models_add(body: dict) -> dict[str, Any]:
        return settings.add_model((body or {}).get("model", ""))

    @router.post("/v1/settings/models/remove")
    def settings_models_remove(body: dict) -> dict[str, Any]:
        return settings.remove_model((body or {}).get("model", ""))

    @router.post("/v1/settings/model-purposes")
    def settings_set_model_purposes(body: dict) -> dict[str, Any]:
        body = body or {}
        return settings.set_model_purposes(
            body.get("model", ""), body.get("purposes") or []
        )

    @router.post("/v1/settings/onboarded")
    def settings_set_onboarded(body: dict) -> dict[str, Any]:
        return settings.set_onboarded(bool((body or {}).get("value", True)))

    @router.post("/v1/settings/experimental-connectors")
    def settings_set_experimental(body: dict) -> dict[str, Any]:
        return settings.set_experimental_connectors(bool((body or {}).get("value")))

    @router.post("/v1/settings/surfaces")
    def settings_set_surfaces(body: dict) -> dict[str, Any]:
        b = body or {}
        return settings.set_surfaces(chat=b.get("chat"), code=b.get("code"))

    @router.post("/v1/settings/scratch-base")
    def settings_set_scratch_base(body: dict) -> dict[str, Any]:
        return settings.set_scratch_base(str((body or {}).get("path", "")))

    @router.post("/v1/settings/nav-layout")
    def settings_set_nav_layout(body: dict) -> dict[str, Any]:
        return settings.set_nav_layout(str((body or {}).get("nav_layout", "")))

    @router.post("/v1/settings/sessions-peek")
    def settings_set_sessions_peek(body: dict) -> dict[str, Any]:
        return settings.set_sessions_peek((body or {}).get("sessions_peek", 5))

    @router.post("/v1/settings/pdf")
    def settings_set_pdf(body: dict) -> dict[str, Any]:
        b = body or {}
        return settings.set_pdf_settings(
            fallback=b.get("pdf_fallback"),
            max_pages=b.get("pdf_max_pages"),
            max_mb=b.get("pdf_max_mb"),
        )

    @router.post("/v1/attachments/inspect-pdf")
    def attachments_inspect_pdf(body: dict) -> dict[str, Any]:
        from ...pdf_support import inspect

        return inspect(str((body or {}).get("data_url", "")))

    # -- direct-message routing -------------------------------------------------
    @router.get("/v1/messaging/dm-route")
    def dm_route_get() -> dict[str, Any]:
        return {"dm_session": settings.dm_session()}

    @router.post("/v1/messaging/dm-route")
    def dm_route_set(body: dict) -> dict[str, Any]:
        return settings.set_dm_session((body or {}).get("session_id", ""))

    return router
