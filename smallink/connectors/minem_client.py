"""Local MineM CLI adapter.

MineM owns its runtime discovery, application launch, and API compatibility checks.
Smallink deliberately talks to that public CLI instead of reading MineM's database or
calling private HTTP endpoints. This keeps the connector on the same contract a human
uses from Terminal and lets MineM choose its own dynamic localhost port.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable, Optional

_MAX_STDOUT = 8 * 1024 * 1024
_DEFAULT_TIMEOUT = 30.0
_ASSET_TYPES = {"all", "report", "page", "resource"}


class MineMClient:
    """Invoke the installed MineM CLI with a small, read-only command surface."""

    def __init__(self, command: Optional[Iterable[str]] = None):
        self._command = list(command) if command else None

    def command(self) -> list[str] | None:
        if self._command:
            return list(self._command)

        packaged = Path(
            "/Applications/MineM.app/Contents/Resources/sidecar/minem-server"
        )
        if packaged.is_file() and os.access(packaged, os.X_OK):
            return [str(packaged), "--cli"]

        user_cli = Path.home() / ".local" / "bin" / "minem"
        if user_cli.is_file() and os.access(user_cli, os.X_OK):
            return [str(user_cli)]

        discovered = shutil.which("minem")
        return [discovered] if discovered else None

    def inspect(self) -> dict[str, Any]:
        """Inspect installation/runtime state without launching MineM."""
        command = self.command()
        app_installed = Path("/Applications/MineM.app").is_dir()
        manifest = self._read_manifest()
        pid = _safe_int(manifest.get("pid"))
        running = bool(pid and _pid_alive(pid))
        return {
            "app_installed": app_installed,
            "cli_available": bool(command),
            "health": "running" if running else "offline",
            "runtime_url": _loopback_url(manifest.get("baseUrl")),
            "runtime_pid": pid if running else None,
        }

    def connect(self) -> dict[str, Any]:
        """Launch MineM if needed and verify the public CLI contract."""
        if not self.command():
            return {
                "ok": False,
                "error": "MineM is not installed, or its CLI could not be found.",
                **self.inspect(),
            }
        payload = self._run(["status"], timeout=40)
        if not payload.get("ok"):
            return {
                "ok": False,
                "error": _error_message(payload),
                "error_code": _error_code(payload),
                **self.inspect(),
            }
        return self._normalise_status(payload)

    def status(self) -> dict[str, Any]:
        payload = self._run(["status"])
        if not payload.get("ok"):
            return {
                "ok": False,
                "error": _error_message(payload),
                "error_code": _error_code(payload),
                **self.inspect(),
            }
        return self._normalise_status(payload)

    def search_assets(
        self, query: str, asset_type: str = "all", limit: int = 10
    ) -> dict[str, Any]:
        query = str(query or "").strip()
        if not query:
            return {"ok": False, "error": "query is required"}
        kind = asset_type if asset_type in _ASSET_TYPES else "all"
        count = _clamp(limit, default=10, ceiling=20)
        payload = self._run(
            ["asset", "search", query, "--type", kind, "--limit", str(count)]
        )
        return _normalise_collection(payload, "results", limit=count)

    def get_asset(self, reference: str) -> dict[str, Any]:
        return self._resource(["asset", "get", _reference(reference)])

    def get_report_pages(self, reference: str, limit: int = 60) -> dict[str, Any]:
        payload = self._run(["report", "pages", _reference(reference)])
        return _normalise_collection(
            payload, "pages", limit=_clamp(limit, default=60, ceiling=100)
        )

    def get_versions(self, reference: str, limit: int = 20) -> dict[str, Any]:
        payload = self._run(["asset", "versions", _reference(reference)])
        return _normalise_collection(
            payload, "versions", limit=_clamp(limit, default=20, ceiling=50)
        )

    def get_lineage(self, reference: str) -> dict[str, Any]:
        return self._resource(["asset", "lineage", _reference(reference)])

    def _resource(self, args: list[str]) -> dict[str, Any]:
        payload = self._run(args)
        if not payload.get("ok"):
            return _normalise_error(payload)
        return {
            "ok": True,
            "resource": _bounded(payload.get("resource")),
            "data": _bounded(payload.get("data")),
            "links": _safe_links(payload.get("links")),
            "warnings": _bounded(payload.get("warnings") or []),
        }

    def _run(
        self, args: list[str], *, timeout: float = _DEFAULT_TIMEOUT
    ) -> dict[str, Any]:
        command = self.command()
        if not command:
            return {"ok": False, "error": {"code": "CLI_NOT_FOUND", "message": "MineM CLI not found"}}
        try:
            completed = subprocess.run(
                [
                    *command,
                    *args,
                    "--output",
                    "json",
                    "--no-input",
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env={**os.environ, "NO_COLOR": "1"},
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "error": {
                    "code": "CLI_TIMEOUT",
                    "message": "MineM did not respond before the connector timed out.",
                },
            }
        except OSError as exc:
            return {
                "ok": False,
                "error": {"code": "CLI_START_FAILED", "message": str(exc)},
            }

        stdout = completed.stdout or ""
        if len(stdout.encode("utf-8", errors="ignore")) > _MAX_STDOUT:
            return {
                "ok": False,
                "error": {
                    "code": "CLI_OUTPUT_TOO_LARGE",
                    "message": "MineM returned more data than the connector accepts.",
                },
            }
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            detail = (completed.stderr or stdout or "MineM returned no JSON").strip()
            return {
                "ok": False,
                "error": {
                    "code": "CLI_INVALID_RESPONSE",
                    "message": f"MineM CLI returned invalid JSON: {detail[:500]}",
                },
            }
        if not isinstance(payload, dict):
            return {
                "ok": False,
                "error": {
                    "code": "CLI_INVALID_RESPONSE",
                    "message": "MineM returned an unexpected response.",
                },
            }
        return payload

    def _normalise_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        release = data.get("release") if isinstance(data.get("release"), dict) else {}
        stats = data.get("stats") if isinstance(data.get("stats"), dict) else {}
        version = _first(
            release,
            "version",
            "appVersion",
            fallback=_first(data, "version", "appVersion"),
        )
        api_version = _first(
            release,
            "apiVersion",
            "api_version",
            fallback=_first(data, "apiVersion", "api_version"),
        )
        visible = _first(
            stats,
            "visibleAssets",
            "visibleAssetCount",
            "visible_assets",
            "total",
            fallback=_first(
                data, "visibleAssets", "visibleAssetCount", "visible_assets"
            ),
        )
        public_stats = {
            key: _bounded(stats[key])
            for key in (
                "assetCount",
                "visibleAssetCount",
                "rawAssetCount",
                "versionedAssetCount",
                "uploadCount",
                "categories",
                "types",
            )
            if key in stats
        }
        server_url = _loopback_url(
            (payload.get("meta") or {}).get("serverUrl")
            if isinstance(payload.get("meta"), dict)
            else ""
        )
        return {
            "ok": True,
            "health": "running",
            "app_installed": True,
            "cli_available": True,
            "app_version": str(version or ""),
            "api_version": api_version,
            "visible_asset_count": visible,
            "stats": public_stats,
            "runtime_url": server_url,
            "account": f"MineM {version}".strip() if version else "MineM local",
        }

    @staticmethod
    def _read_manifest() -> dict[str, Any]:
        candidates = [
            Path.home()
            / "Library"
            / "Application Support"
            / "MineM"
            / "runtime"
            / "service.json",
            Path.home()
            / "Library"
            / "Application Support"
            / "com.minem.materialos"
            / "runtime"
            / "service.json",
        ]
        for path in candidates:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                return value
        return {}


_DEFAULT_CLIENT: MineMClient | None = None


def get_minem_client() -> MineMClient:
    global _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        _DEFAULT_CLIENT = MineMClient()
    return _DEFAULT_CLIENT


def _normalise_collection(
    payload: dict[str, Any], key: str, *, limit: int
) -> dict[str, Any]:
    if not payload.get("ok"):
        return _normalise_error(payload)
    data = payload.get("data")
    if isinstance(data, list):
        items = data
        metadata: dict[str, Any] = {}
    elif isinstance(data, dict):
        raw = data.get("items")
        if not isinstance(raw, list):
            raw = data.get(key)
        items = raw if isinstance(raw, list) else []
        metadata = {
            k: _bounded(v)
            for k, v in data.items()
            if k not in {"items", key}
            and k in {"count", "total", "query", "type", "pagination"}
        }
    else:
        items = []
        metadata = {}
    selected = [_bounded(item) for item in items[:limit]]
    pagination = metadata.get("pagination")
    total = (
        pagination.get("total")
        if isinstance(pagination, dict)
        else metadata.get("total")
    )
    has_next = bool(
        isinstance(pagination, dict) and pagination.get("hasNext")
    )
    return {
        "ok": True,
        key: selected,
        "count": len(selected),
        "truncated": bool(
            len(items) > len(selected)
            or has_next
            or (isinstance(total, int) and total > len(selected))
        ),
        **metadata,
        "links": _safe_links(payload.get("links")),
        "warnings": _bounded(payload.get("warnings") or []),
    }


def _normalise_error(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": False,
        "error": _error_message(payload),
        "error_code": _error_code(payload),
    }


def _error_message(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or "MineM command failed")
    return str(error or "MineM command failed")


def _error_code(payload: dict[str, Any]) -> str:
    error = payload.get("error")
    return str(error.get("code") or "") if isinstance(error, dict) else ""


def _reference(value: str) -> str:
    ref = str(value or "").strip()
    if not ref:
        raise ValueError("reference is required")
    if len(ref) > 300:
        raise ValueError("reference is too long")
    return ref


def _bounded(value: Any, *, depth: int = 0) -> Any:
    """Bound model-facing CLI data while preserving MineM's public fields."""
    if depth > 8:
        return "[nested data omitted]"
    if isinstance(value, str):
        return value if len(value) <= 20_000 else value[:20_000] + "\n[truncated]"
    if isinstance(value, list):
        return [_bounded(v, depth=depth + 1) for v in value[:100]]
    if isinstance(value, dict):
        return {
            str(k): _bounded(v, depth=depth + 1)
            for k, v in list(value.items())[:100]
            if str(k).lower() not in {"token", "access_token", "refresh_token"}
        }
    return value


def _safe_links(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        str(k): str(v)
        for k, v in value.items()
        if isinstance(v, str)
        and (v.startswith("/") or _loopback_url(v))
    }


def _loopback_url(value: Any) -> str:
    text = str(value or "").strip()
    return (
        text
        if text.startswith(("http://127.0.0.1:", "http://localhost:"))
        else ""
    )


def _first(mapping: dict[str, Any], *keys: str, fallback: Any = None) -> Any:
    for key in keys:
        if mapping.get(key) is not None:
            return mapping[key]
    return fallback


def _clamp(value: Any, *, default: int, ceiling: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(1, min(number, ceiling))


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False
