"""Model providers and persisted desktop settings.

This service is intentionally independent of :class:`SessionManager`.  Its three
process-level dependencies are explicit: the secret store, the manager state
directory (which owns ``prefs.json``), and a callback that invalidates cached
provider clients.  Native file/folder pickers do not belong to this domain.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Optional

from ...connectors import experimental_enabled, set_experimental_enabled
from ...providers import (
    get_descriptor,
    provider_descriptors,
    verify_provider_key,
)
from ...secrets import SecretStore

MODEL_PURPOSES = ("chat", "memory", "title")


class SettingsService:
    """Own provider configuration and ``prefs.json`` backed settings.

    ``state_path`` is the manager's state directory, not the SecretStore path.
    Those locations intentionally remain independent when a manager is created
    with an explicit ``data_dir``.
    """

    DEFAULT_SCRATCH_BASE = "~/Smallink"
    DEFAULT_SESSIONS_PEEK = 5
    DEFAULT_PDF_MAX_PAGES = 20
    DEFAULT_PDF_MAX_MB = 10
    # Keep this a class-level extension point, matching SessionManager's old
    # contract and the registry consistency tests that inspect it directly.
    COMPAT_MODELS = {
        "zai": ["glm-5.2", "glm-4.6"],
        "deepseek": ["deepseek-v4-flash", "deepseek-v4-pro"],
        "kimi": ["kimi-k2.6", "kimi-k2.5"],
        "minimax": [
            "MiniMax-M2.5",
            "MiniMax-M2.5-highspeed",
            "MiniMax-M3",
        ],
        "qwen": ["qwen3-max", "qwen3-coder-plus", "qwen-plus"],
        "xai": ["grok-4.3", "grok-4"],
        "mistral": ["mistral-large-latest", "mistral-small-latest"],
    }

    def __init__(
        self,
        *,
        secrets: SecretStore,
        refresh_provider: Callable[[Optional[str]], None],
        state_path: str | Path,
        model: str = "gpt-5.6-sol",
        on_model_change: Optional[Callable[[Any], None]] = None,
        suggested_models: Optional[Callable[[str], list[str]]] = None,
        ollama_alive: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.secrets = secrets
        self._refresh_provider_callback = refresh_provider
        self._on_model_change = on_model_change
        self._suggested_models_callback = suggested_models
        self._ollama_alive_callback = ollama_alive
        self.state_path = Path(state_path).expanduser()
        self.state_path.mkdir(parents=True, exist_ok=True)
        self._prefs = self._load_prefs()
        persisted_model = self._prefs.get("default_model")
        self.model = (
            persisted_model.strip()
            if isinstance(persisted_model, str) and persisted_model.strip()
            else model
        )
        if self._on_model_change is not None:
            self._on_model_change(self.model)

        # Engines consult this module-level setting, so restore it as soon as the
        # service loads persisted preferences.
        from ...pdf_support import set_fallback_mode

        set_fallback_mode(self.pdf_settings()["pdf_fallback"])

    @property
    def prefs(self) -> dict[str, Any]:
        """The live preference mapping, for manager-owned adjacent domains."""
        return self._prefs

    def _prefs_path(self) -> Path:
        return self.state_path / "prefs.json"

    def _load_prefs(self) -> dict[str, Any]:
        try:
            loaded = json.loads(self._prefs_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _save_prefs(self) -> None:
        self._prefs_path().write_text(
            json.dumps(self._prefs, indent=2), encoding="utf-8"
        )

    # -- web search ---------------------------------------------------------

    def get_web_search(self) -> dict[str, Any]:
        from ...config import load_config
        from ...web import provider_names

        profile = self.secrets.get("web_search:default") or {}
        provider = (
            profile.get("provider")
            or load_config().web_search_provider
            or "duckduckgo"
        )
        return {
            "provider": provider,
            "has_key": bool(profile.get("api_key")),
            "providers": provider_names(),
        }

    def set_web_search(
        self, provider: str, api_key: Optional[str] = None
    ) -> dict[str, Any]:
        from ...web import provider_names

        if provider not in provider_names():
            return {"ok": False, "error": f"unknown provider: {provider}"}
        profile: dict[str, Any] = {"provider": provider}
        if api_key:
            profile["api_key"] = api_key
        self.secrets.put("web_search:default", profile)
        return {"ok": True, "provider": provider}

    # -- providers ----------------------------------------------------------

    def get_providers(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for descriptor in provider_descriptors():
            profile = self.secrets.get(f"provider:{descriptor.name}") or {}
            if descriptor.needs_key:
                configured = bool(profile.get("api_key")) or bool(
                    descriptor.env_key and os.environ.get(descriptor.env_key)
                )
            else:
                # Preserve the Settings UI contract: keyless providers are
                # presented as configured even before explicit enablement.
                configured = True
            values = {
                field.key: profile.get(field.key)
                for field in descriptor.fields
                if not field.secret and profile.get(field.key)
            }
            out.append(
                {
                    **descriptor.to_dict(),
                    "configured": configured,
                    "values": values,
                    "suggested_models": self._suggested_models(descriptor.name),
                    "key_set_at": profile.get("key_set_at"),
                    "last_used_at": (
                        self._prefs.get("provider_last_used") or {}
                    ).get(descriptor.name),
                }
            )
        return out

    def note_provider_use(self, name: str) -> None:
        """Record provider use, throttled to one preference write per minute."""
        now = time.time()
        used = self._prefs.setdefault("provider_last_used", {})
        if now - float(used.get(name) or 0) < 60:
            return
        used[name] = now
        try:
            self._save_prefs()
        except OSError:
            pass

    def _suggested_models(self, name: str) -> list[str]:
        if self._suggested_models_callback is not None:
            return self._suggested_models_callback(name)
        return self._default_suggested_models(name)

    def _default_suggested_models(self, name: str) -> list[str]:
        if name == "ollama":
            return [model.split(":", 1)[-1] for model in self._ollama_models()]
        if name == "trae":
            from ...providers.trae_provider import trae_model_ids

            return trae_model_ids()
        from ...providers.matrix import models_for_provider

        return list(
            dict.fromkeys(
                [*models_for_provider(name), *self.COMPAT_MODELS.get(name, [])]
            )
        )

    def set_provider(
        self, name: str, fields: Optional[dict[str, Any]]
    ) -> dict[str, Any]:
        descriptor = get_descriptor(name)
        if descriptor is None:
            return {"ok": False, "error": f"unknown provider: {name}"}
        fields = fields or {}
        profile = dict(self.secrets.get(f"provider:{name}") or {})
        for field in descriptor.fields:
            if field.key not in fields:
                continue
            value = fields.get(field.key)
            if isinstance(value, str):
                value = value.strip()
            if value:
                profile[field.key] = value
            elif not field.required:
                profile.pop(field.key, None)
        missing = [
            field.label
            for field in descriptor.fields
            if field.required and not profile.get(field.key)
        ]
        if missing:
            return {"ok": False, "error": "missing: " + ", ".join(missing)}
        if isinstance(fields.get("api_key"), str) and fields["api_key"].strip():
            profile["key_set_at"] = date.today().isoformat()
        if not descriptor.needs_key:
            profile["_enabled"] = True
        self.secrets.put(f"provider:{name}", profile)
        self._refresh_provider(name)

        recommended = descriptor.recommended_model
        added: Optional[str] = None
        if recommended and recommended in self._suggested_models(name):
            added = recommended if name == "openai" else f"{name}:{recommended}"
            self.add_model(added)
        if added and not self._provider_configured(
            self._model_provider(self.model)
        ):
            self.set_default_model(added)
        return {
            "ok": True,
            "provider": name,
            "recommended_model": recommended,
        }

    def remove_provider(self, name: str) -> dict[str, Any]:
        if get_descriptor(name) is None:
            return {"ok": False, "error": f"unknown provider: {name}"}
        self.secrets.delete(f"provider:{name}")
        self._refresh_provider(name)
        return {"ok": True, "provider": name}

    def verify_provider(
        self, name: str, fields: Optional[dict[str, Any]]
    ) -> dict[str, Any]:
        descriptor = get_descriptor(name)
        if descriptor is None:
            return {"ok": False, "error": f"unknown provider: {name}"}
        fields = fields or {}
        profile = self.secrets.get(f"provider:{name}") or {}
        api_key = (
            fields.get("api_key") or profile.get("api_key") or ""
        ).strip()
        if not api_key and descriptor.env_key:
            api_key = os.environ.get(descriptor.env_key, "").strip()
        base_url = (
            fields.get("base_url") or profile.get("base_url") or ""
        ).strip()
        if descriptor.needs_key and not api_key:
            return {"ok": False, "error": "Enter an API key to test."}
        return verify_provider_key(name, api_key=api_key, base_url=base_url)

    def _refresh_provider(self, name: Optional[str] = None) -> None:
        self._refresh_provider_callback(name)

    def _model_provider(self, model: str) -> str:
        if ":" in (model or ""):
            prefix = model.split(":", 1)[0]
            if get_descriptor(prefix) is not None:
                return prefix
        return "openai"

    def _provider_configured(self, name: str) -> bool:
        descriptor = get_descriptor(name)
        if descriptor is None:
            return False
        profile = self.secrets.get(f"provider:{name}") or {}
        if not descriptor.needs_key:
            return bool(profile.get("_enabled") or profile)
        return bool(profile.get("api_key")) or bool(
            descriptor.env_key and os.environ.get(descriptor.env_key)
        )

    def _trae_enabled(self) -> bool:
        user_models = self._prefs.get("models")
        user_models = user_models if isinstance(user_models, list) else []
        return (
            self.model.startswith("trae:")
            or any(str(model).startswith("trae:") for model in user_models)
            or self._provider_configured("trae")
        )

    def _ollama_alive(self) -> bool:
        if self._ollama_alive_callback is not None:
            return self._ollama_alive_callback()
        return self._probe_ollama_alive()

    def _probe_ollama_alive(self) -> bool:
        now = time.monotonic()
        cached = getattr(self, "_ollama_alive_cache", None)
        if cached and now - cached[0] < 30:
            return cached[1]
        profile = self.secrets.get("provider:ollama") or {}
        base = (profile.get("base_url") or "http://localhost:11434").strip()
        base = base.rstrip("/")
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        try:
            import httpx

            alive = httpx.get(base + "/api/tags", timeout=0.8).status_code == 200
        except Exception:
            alive = False
        self._ollama_alive_cache = (now, alive)
        return alive

    def _ollama_models(self) -> list[str]:
        profile = self.secrets.get("provider:ollama")
        if not profile:
            return []
        base = (profile.get("base_url") or "http://localhost:11434").strip()
        base = base.rstrip("/")
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        try:
            import httpx

            data = httpx.get(base + "/api/tags", timeout=2.0).json()
            return [
                f"ollama:{item['name']}"
                for item in data.get("models", [])
                if item.get("name")
            ]
        except Exception:
            return []

    # -- models and aggregated settings ------------------------------------

    def _curated_models(self) -> list[str]:
        from ...providers.matrix import MATRIX
        from ...providers.trae_provider import probe_trae_status, trae_model_ids

        trae_models = (
            [f"trae:{slug}" for slug in trae_model_ids()]
            if self._trae_enabled() and probe_trae_status().get("ok")
            else []
        )
        user = self._prefs.get("models")
        user = user if isinstance(user, list) else []
        hidden = set(self._prefs.get("hidden_models") or [])
        models = [
            model
            for model in [*MATRIX, *trae_models, *user]
            if model not in hidden
        ]
        return list(dict.fromkeys([self.model, *models]))

    def add_model(self, model: str) -> dict[str, Any]:
        from ...providers.matrix import MATRIX

        model = (model or "").strip()
        if not model:
            return {"ok": False, "error": "empty model"}
        hidden = [
            item for item in self._prefs.get("hidden_models") or [] if item != model
        ]
        if hidden:
            self._prefs["hidden_models"] = hidden
        else:
            self._prefs.pop("hidden_models", None)
        models = self._prefs.get("models")
        models = models if isinstance(models, list) else []
        if model not in models and model not in MATRIX:
            models.append(model)
        self._prefs["models"] = models
        self._save_prefs()
        return {"ok": True, **self.get_settings()}

    def remove_model(self, model: str) -> dict[str, Any]:
        from ...providers.matrix import MATRIX

        models = self._prefs.get("models")
        models = models if isinstance(models, list) else []
        self._prefs["models"] = [item for item in models if item != model]
        if model in MATRIX:
            hidden = self._prefs.get("hidden_models") or []
            if model not in hidden:
                self._prefs["hidden_models"] = [*hidden, model]
        self._save_prefs()
        return {"ok": True, **self.get_settings()}

    def get_settings(self) -> dict[str, Any]:
        env_key = bool(os.environ.get("OPENAI_API_KEY"))
        stored = bool((self.secrets.get("provider:openai") or {}).get("api_key"))

        from ...providers.trae_provider import probe_trae_status

        trae_enabled = self._trae_enabled()
        trae_ok = probe_trae_status().get("ok", False) if trae_enabled else False

        def selectable(model: str) -> bool:
            provider = self._model_provider(model)
            if provider == "ollama":
                return self._ollama_alive()
            if provider == "trae":
                return trae_ok
            return self._provider_configured(provider)

        models = [model for model in self._curated_models() if selectable(model)]
        if self.model not in models:
            models.insert(0, self.model)

        from ...providers.matrix import model_labels
        from ...providers.trae_provider import discover_trae_models

        labels = model_labels()
        if trae_enabled:
            for item in discover_trae_models():
                labels[f"trae:{item['slug']}"] = item["label"]

        return {
            "provider": "openai",
            "model": self.model,
            "models": models,
            "model_purposes": self._prefs.get("model_purposes") or {},
            "purposes": list(MODEL_PURPOSES),
            "model_labels": labels,
            "has_key": env_key or stored,
            "model_ready": self._provider_configured(
                self._model_provider(self.model)
            ),
            "source": "env" if env_key else ("store" if stored else None),
            "onboarded": bool(self._prefs.get("onboarded")),
            "experimental_connectors": experimental_enabled(self.secrets),
            "surfaces": self._surfaces(),
            "nav_layout": self._nav_layout(),
            "sessions_peek": self.sessions_peek(),
            "scratch_base": self._prefs.get("scratch_base")
            or self.DEFAULT_SCRATCH_BASE,
            "secrets_path": str(self.secrets.path),
            **self.pdf_settings(),
        }

    def set_model_key(self, api_key: str) -> dict[str, Any]:
        api_key = (api_key or "").strip()
        if not api_key:
            return {"ok": False, "error": "empty api key"}
        profile = dict(self.secrets.get("provider:openai") or {})
        profile.update({"type": "api_key", "api_key": api_key})
        self.secrets.put("provider:openai", profile)
        self._refresh_provider("openai")
        return {"ok": True, **self.get_settings()}

    def set_default_model(self, model: str) -> dict[str, Any]:
        model = (model or "").strip()
        if not model:
            return {"ok": False, "error": "empty model"}
        self.model = model
        if self._on_model_change is not None:
            self._on_model_change(model)
        self._prefs["default_model"] = model
        self._save_prefs()
        return {"ok": True, **self.get_settings()}

    def set_model_purposes(
        self, model: str, purposes: list[str]
    ) -> dict[str, Any]:
        model = (model or "").strip()
        if not model:
            return {"ok": False, "error": "empty model"}
        wanted = [purpose for purpose in (purposes or []) if purpose in MODEL_PURPOSES]
        table = self._prefs.get("model_purposes")
        table = table if isinstance(table, dict) else {}
        if wanted:
            table[model] = wanted
        else:
            table.pop(model, None)
        self._prefs["model_purposes"] = table
        self._save_prefs()
        return {"ok": True, **self.get_settings()}

    def model_for_purpose(self, purpose: str) -> str:
        table = self._prefs.get("model_purposes")
        table = table if isinstance(table, dict) else {}
        tagged = [
            model for model, purposes in table.items() if purpose in (purposes or [])
        ]
        if not tagged or self.model in tagged:
            return self.model
        return tagged[0]

    # -- desktop preferences ------------------------------------------------

    def dm_session(self) -> Optional[str]:
        session_id = self._prefs.get("dm_session")
        return session_id or None

    def set_dm_session(self, session_id: Optional[str]) -> dict[str, Any]:
        value = (session_id or "").strip()
        if value:
            self._prefs["dm_session"] = value
        else:
            self._prefs.pop("dm_session", None)
        self._save_prefs()
        return {"ok": True, "dm_session": self.dm_session()}

    def set_experimental_connectors(self, value: bool) -> dict[str, Any]:
        return set_experimental_enabled(self.secrets, value)

    def _surfaces(self) -> dict[str, bool]:
        return {
            "link": True,
            "chat": bool(self._prefs.get("show_chat", False)),
            "code": bool(self._prefs.get("show_code", False)),
        }

    def set_surfaces(
        self, chat: Optional[bool] = None, code: Optional[bool] = None
    ) -> dict[str, Any]:
        if chat is not None:
            self._prefs["show_chat"] = bool(chat)
        if code is not None:
            self._prefs["show_code"] = bool(code)
        self._save_prefs()
        return {"ok": True, "surfaces": self._surfaces()}

    def _nav_layout(self) -> str:
        return "grouped" if self._prefs.get("nav_layout") == "grouped" else "flat"

    def set_nav_layout(self, nav_layout: str) -> dict[str, Any]:
        value = "grouped" if (nav_layout or "").strip() == "grouped" else "flat"
        self._prefs["nav_layout"] = value
        self._save_prefs()
        return {"ok": True, "nav_layout": value}

    def sessions_peek(self) -> int:
        try:
            value = int(
                self._prefs.get("sessions_peek", self.DEFAULT_SESSIONS_PEEK)
            )
        except (TypeError, ValueError):
            value = self.DEFAULT_SESSIONS_PEEK
        return max(1, min(value, 50))

    def set_sessions_peek(self, n: int) -> dict[str, Any]:
        try:
            self._prefs["sessions_peek"] = max(1, min(int(n), 50))
        except (TypeError, ValueError):
            return {"ok": False, "error": "sessions_peek must be a number"}
        self._save_prefs()
        return {"ok": True, "sessions_peek": self.sessions_peek()}

    def pdf_settings(self) -> dict[str, Any]:
        from ...pdf_support import FALLBACK_MODES

        fallback = self._prefs.get("pdf_fallback")
        try:
            pages = int(
                self._prefs.get("pdf_max_pages", self.DEFAULT_PDF_MAX_PAGES)
            )
        except (TypeError, ValueError):
            pages = self.DEFAULT_PDF_MAX_PAGES
        try:
            size_mb = int(
                self._prefs.get("pdf_max_mb", self.DEFAULT_PDF_MAX_MB)
            )
        except (TypeError, ValueError):
            size_mb = self.DEFAULT_PDF_MAX_MB
        return {
            "pdf_fallback": fallback if fallback in FALLBACK_MODES else "text",
            "pdf_max_pages": max(1, min(pages, 100)),
            "pdf_max_mb": max(1, min(size_mb, 10)),
        }

    def set_pdf_settings(
        self,
        fallback: Any = None,
        max_pages: Any = None,
        max_mb: Any = None,
    ) -> dict[str, Any]:
        from ...pdf_support import FALLBACK_MODES, set_fallback_mode

        if fallback is not None:
            if fallback not in FALLBACK_MODES:
                return {
                    "ok": False,
                    "error": "pdf_fallback must be 'text' or 'images'",
                }
            self._prefs["pdf_fallback"] = fallback
        for key, value, ceiling in (
            ("pdf_max_pages", max_pages, 100),
            ("pdf_max_mb", max_mb, 10),
        ):
            if value is None:
                continue
            try:
                self._prefs[key] = max(1, min(int(value), ceiling))
            except (TypeError, ValueError):
                return {"ok": False, "error": f"{key} must be a number"}
        self._save_prefs()
        settings = self.pdf_settings()
        set_fallback_mode(settings["pdf_fallback"])
        return {"ok": True, **settings}

    def set_onboarded(self, value: bool = True) -> dict[str, Any]:
        self._prefs["onboarded"] = bool(value)
        self._save_prefs()
        return {"ok": True, "onboarded": bool(value)}

    def scratch_base(self) -> Path:
        value = self._prefs.get("scratch_base") or self.DEFAULT_SCRATCH_BASE
        return Path(value).expanduser()

    def set_scratch_base(self, path: str) -> dict[str, Any]:
        path = (path or "").strip()
        if not path:
            return {"ok": False, "error": "empty path"}
        try:
            Path(path).expanduser().mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        self._prefs["scratch_base"] = path
        self._save_prefs()
        return {"ok": True, **self.get_settings()}
