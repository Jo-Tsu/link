"""Focused contract tests for the extracted settings service."""

from __future__ import annotations

import json
from datetime import date

import pytest

from smallink import pdf_support
from smallink.secrets import SecretStore
from smallink.server.services.settings import SettingsService


@pytest.fixture(autouse=True)
def _reset_pdf_fallback():
    pdf_support.set_fallback_mode("text")
    yield
    pdf_support.set_fallback_mode("text")


def _service(tmp_path, *, model="gpt-5.6-sol"):
    invalidated: list[str | None] = []
    service = SettingsService(
        secrets=SecretStore(path=tmp_path / "secrets.json"),
        refresh_provider=invalidated.append,
        state_path=tmp_path / "manager-state",
        model=model,
    )
    return service, invalidated


def _no_live_model_probes(monkeypatch, service):
    monkeypatch.setattr(service, "_ollama_alive", lambda: False)
    monkeypatch.setattr(service, "_ollama_models", lambda: [])


def test_defaults_and_prefs_roundtrip_without_full_manager(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    service, _ = _service(tmp_path)
    _no_live_model_probes(monkeypatch, service)

    settings = service.get_settings()
    assert settings["model"] == "gpt-5.6-sol"
    assert settings["models"] == ["gpt-5.6-sol"]
    assert settings["surfaces"] == {
        "link": True,
        "chat": False,
        "code": False,
    }
    assert settings["nav_layout"] == "flat"
    assert settings["sessions_peek"] == 5
    assert settings["scratch_base"] == "~/Smallink"
    assert service.pdf_settings() == {
        "pdf_fallback": "text",
        "pdf_max_pages": 20,
        "pdf_max_mb": 10,
    }

    service.set_default_model("custom:model")
    service.set_model_purposes("memory:model", ["memory", "bogus"])
    service.set_surfaces(chat=True)
    service.set_nav_layout("grouped")
    service.set_sessions_peek(500)
    service.set_onboarded(True)
    service.set_dm_session(" session-1 ")
    assert service.set_pdf_settings("images", 0, 99) == {
        "ok": True,
        "pdf_fallback": "images",
        "pdf_max_pages": 1,
        "pdf_max_mb": 10,
    }

    reborn = SettingsService(
        secrets=service.secrets,
        refresh_provider=lambda _name: None,
        state_path=tmp_path / "manager-state",
        model="ignored",
    )
    _no_live_model_probes(monkeypatch, reborn)
    restored = reborn.get_settings()
    assert reborn.model == "custom:model"
    assert reborn.model_for_purpose("memory") == "memory:model"
    assert restored["surfaces"]["chat"] is True
    assert restored["nav_layout"] == "grouped"
    assert restored["sessions_peek"] == 50
    assert restored["onboarded"] is True
    assert reborn.dm_session() == "session-1"
    assert reborn.pdf_settings()["pdf_fallback"] == "images"


def test_provider_config_is_sanitized_and_invalidates_router(
    tmp_path, monkeypatch
):
    service, invalidated = _service(tmp_path)
    _no_live_model_probes(monkeypatch, service)
    monkeypatch.setattr(service, "_suggested_models", lambda _name: [])

    assert service.set_provider("no-such-provider", {}) == {
        "ok": False,
        "error": "unknown provider: no-such-provider",
    }
    missing = service.set_provider("deepseek", {})
    assert missing["ok"] is False and missing["error"].startswith("missing: ")

    result = service.set_provider(
        "deepseek",
        {"api_key": " secret-key ", "base_url": " https://example.test/v1 "},
    )
    assert result == {
        "ok": True,
        "provider": "deepseek",
        "recommended_model": "deepseek-v4-flash",
    }
    assert invalidated == ["deepseek"]
    stored = service.secrets.get("provider:deepseek")
    assert stored == {
        "api_key": "secret-key",
        "base_url": "https://example.test/v1",
        "key_set_at": date.today().isoformat(),
    }
    provider = next(
        item for item in service.get_providers() if item["name"] == "deepseek"
    )
    assert provider["configured"] is True
    assert provider["values"] == {"base_url": "https://example.test/v1"}
    assert "api_key" not in provider["values"]
    assert "secret-key" not in json.dumps(provider)

    assert service.remove_provider("deepseek") == {
        "ok": True,
        "provider": "deepseek",
    }
    assert invalidated == ["deepseek", "deepseek"]
    assert service.secrets.get("provider:deepseek") is None


def test_provider_verification_uses_injected_store_without_persisting_form_key(
    tmp_path, monkeypatch
):
    import smallink.server.services.settings as settings_module

    service, _ = _service(tmp_path)
    service.secrets.put(
        "provider:openai",
        {"api_key": "stored", "base_url": "https://stored.test/v1"},
    )
    seen = {}

    def fake_verify(name, *, api_key=None, base_url=None):
        seen.update(name=name, api_key=api_key, base_url=base_url)
        return {"ok": True}

    monkeypatch.setattr(settings_module, "verify_provider_key", fake_verify)
    assert service.verify_provider(
        "openai",
        {"api_key": "transient", "base_url": "https://form.test/v1"},
    ) == {"ok": True}
    assert seen == {
        "name": "openai",
        "api_key": "transient",
        "base_url": "https://form.test/v1",
    }
    assert service.secrets.get("provider:openai")["api_key"] == "stored"


def test_model_key_web_search_and_scratch_contracts(tmp_path, monkeypatch):
    service, invalidated = _service(tmp_path)
    _no_live_model_probes(monkeypatch, service)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert service.set_model_key("  ") == {
        "ok": False,
        "error": "empty api key",
    }
    result = service.set_model_key(" sk-test ")
    assert result["ok"] is True and result["source"] == "store"
    assert invalidated == ["openai"]
    assert "sk-test" not in json.dumps(result)

    assert service.set_web_search("not-real")["ok"] is False
    assert service.set_web_search("tavily", "tv-key") == {
        "ok": True,
        "provider": "tavily",
    }
    assert service.get_web_search()["has_key"] is True
    # Preserve the existing replacement contract: omitting a key clears the old one.
    service.set_web_search("duckduckgo")
    assert service.get_web_search()["has_key"] is False

    assert service.set_scratch_base("  ") == {
        "ok": False,
        "error": "empty path",
    }
    scratch = tmp_path / "scratch area"
    scratch_result = service.set_scratch_base(str(scratch))
    assert scratch_result["ok"] is True
    assert scratch_result["scratch_base"] == str(scratch)
    assert service.scratch_base() == scratch and scratch.is_dir()


def test_invalid_prefs_are_ignored_and_numeric_preferences_keep_contract(
    tmp_path, monkeypatch
):
    state = tmp_path / "manager-state"
    state.mkdir()
    (state / "prefs.json").write_text("[]", encoding="utf-8")
    service = SettingsService(
        secrets=SecretStore(path=tmp_path / "secrets.json"),
        refresh_provider=lambda _name: None,
        state_path=state,
    )
    assert service.prefs == {}

    (state / "prefs.json").write_text(
        json.dumps({"default_model": 123}), encoding="utf-8"
    )
    service = SettingsService(
        secrets=SecretStore(path=tmp_path / "secrets.json"),
        refresh_provider=lambda _name: None,
        state_path=state,
        model="fallback-model",
    )
    assert service.model == "fallback-model"

    (state / "prefs.json").write_text("{broken", encoding="utf-8")
    service = SettingsService(
        secrets=SecretStore(path=tmp_path / "secrets.json"),
        refresh_provider=lambda _name: None,
        state_path=state,
    )
    _no_live_model_probes(monkeypatch, service)
    assert service.prefs == {}
    assert service.set_sessions_peek("bad") == {
        "ok": False,
        "error": "sessions_peek must be a number",
    }
    assert service.set_pdf_settings(max_pages="bad") == {
        "ok": False,
        "error": "pdf_max_pages must be a number",
    }
    assert service.set_nav_layout("bogus") == {
        "ok": True,
        "nav_layout": "flat",
    }


def test_provider_use_is_throttled_persisted_and_tolerates_write_failure(
    tmp_path, monkeypatch
):
    import smallink.server.services.settings as settings_module

    service, _ = _service(tmp_path)
    clock = iter((100.0, 150.0, 161.0, 222.0))
    monkeypatch.setattr(settings_module.time, "time", lambda: next(clock))

    service.note_provider_use("deepseek")
    assert service.prefs["provider_last_used"]["deepseek"] == 100.0
    first_disk = json.loads(service._prefs_path().read_text(encoding="utf-8"))
    assert first_disk["provider_last_used"]["deepseek"] == 100.0

    service.note_provider_use("deepseek")
    assert service.prefs["provider_last_used"]["deepseek"] == 100.0
    service.note_provider_use("deepseek")
    assert service.prefs["provider_last_used"]["deepseek"] == 161.0

    monkeypatch.setattr(
        service, "_save_prefs", lambda: (_ for _ in ()).throw(OSError("disk"))
    )
    service.note_provider_use("deepseek")
    assert service.prefs["provider_last_used"]["deepseek"] == 222.0


def test_model_change_callback_covers_restore_set_and_provider_auto_default(
    tmp_path, monkeypatch
):
    state = tmp_path / "manager-state"
    state.mkdir()
    (state / "prefs.json").write_text(
        json.dumps({"default_model": "restored:model"}), encoding="utf-8"
    )
    changes = []
    service = SettingsService(
        secrets=SecretStore(path=tmp_path / "secrets.json"),
        refresh_provider=lambda _name: None,
        state_path=state,
        model="constructor:model",
        on_model_change=changes.append,
    )
    _no_live_model_probes(monkeypatch, service)
    assert changes == ["restored:model"]

    service.set_default_model("explicit:model")
    assert changes[-1] == "explicit:model"

    # A first configured provider can change the default from inside
    # set_provider; this must notify the composition root too.
    service.secrets.delete("provider:openai")
    monkeypatch.setattr(
        service,
        "_suggested_models",
        lambda name: ["claude-fable-5"] if name == "anthropic" else [],
    )
    service.set_provider("anthropic", {"api_key": "sk-ant-test"})
    assert service.model == "anthropic:claude-fable-5"
    assert changes[-1] == "anthropic:claude-fable-5"


def test_pdf_global_fallback_matches_persisted_and_failed_update_order(
    tmp_path, monkeypatch
):
    state = tmp_path / "manager-state"
    state.mkdir()
    (state / "prefs.json").write_text(
        json.dumps({"pdf_fallback": "images"}), encoding="utf-8"
    )
    service = SettingsService(
        secrets=SecretStore(path=tmp_path / "secrets.json"),
        refresh_provider=lambda _name: None,
        state_path=state,
    )
    _no_live_model_probes(monkeypatch, service)
    assert pdf_support.fallback_mode() == "images"

    # Legacy ordering mutates prefs first, but a later numeric soft error
    # returns before saving or updating the PDF module global.
    result = service.set_pdf_settings(fallback="text", max_pages="bad")
    assert result == {
        "ok": False,
        "error": "pdf_max_pages must be a number",
    }
    assert service.prefs["pdf_fallback"] == "text"
    assert pdf_support.fallback_mode() == "images"
    assert json.loads(service._prefs_path().read_text(encoding="utf-8"))[
        "pdf_fallback"
    ] == "images"


def test_compat_models_remain_a_class_extension_point(tmp_path):
    service, _ = _service(tmp_path)
    service.COMPAT_MODELS = {"deepseek": ["custom-suggestion"]}
    assert "custom-suggestion" in service._suggested_models("deepseek")


def test_manager_wiring_shares_prefs_and_synchronizes_every_model_change(
    tmp_path, monkeypatch
):
    from smallink.server.manager import SessionManager

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "prefs.json").write_text(
        json.dumps({"default_model": "restored:model"}), encoding="utf-8"
    )
    manager = SessionManager(data_dir=data_dir)
    _no_live_model_probes(monkeypatch, manager.settings_service)

    assert manager.model == manager.settings_service.model == "restored:model"
    assert manager._prefs is manager.settings_service.prefs
    assert manager.memory_service._preferences is manager.settings_service.prefs
    assert manager.memory_service._model_for_purpose.__self__ is manager.settings_service

    manager.settings_service.set_default_model("explicit:model")
    assert manager.model == "explicit:model"

    manager.secrets.delete("provider:openai")
    monkeypatch.setattr(
        manager.settings_service,
        "_suggested_models",
        lambda name: ["claude-fable-5"] if name == "anthropic" else [],
    )
    manager.settings_service.set_provider(
        "anthropic", {"api_key": "sk-ant-test"}
    )
    assert manager.model == manager.settings_service.model == (
        "anthropic:claude-fable-5"
    )


def test_provider_router_on_use_and_http_routes_target_service(
    tmp_path, monkeypatch
):
    from fastapi.testclient import TestClient

    from smallink.providers import ProviderRouter
    from smallink.server.app import create_app
    from smallink.server.manager import SessionManager

    manager = SessionManager(data_dir=tmp_path / "data")
    assert isinstance(manager.provider, ProviderRouter)
    assert manager.provider._on_use.__self__ is manager.settings_service

    manager.provider._note_use("deepseek:any-model")
    assert manager.settings_service.prefs["provider_last_used"]["deepseek"] > 0

    def stale_manager_facade():
        raise AssertionError("settings router called the manager facade")

    monkeypatch.setattr(manager, "get_settings", stale_manager_facade)
    client = TestClient(create_app(manager))
    assert client.get("/v1/settings").json()["model"] == manager.model

    response = client.post(
        "/v1/settings/default-model", json={"model": "router:model"}
    ).json()
    assert response["model"] == "router:model"
    assert manager.model == manager.settings_service.model == "router:model"
