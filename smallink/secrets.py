"""Secret store — one canonical, file-backed store for connector/MCP credentials.

Design (from OpenClaw): secrets **never enter the model's context, prompts, or traces**.
The store holds profiles keyed by `connector[:account]`; values may be literals OR
`${ENV_VAR}` references resolved at read time from the process env / `~/.config/link/.env`.

v1 is a `0600` JSON file behind this interface; the interface is what callers depend on, so
a Keychain / age-encrypted backend can swap in later without touching them.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_IS_WINDOWS = sys.platform == "win32"
_KEYCHAIN_SERVICE = "com.smallink.secrets"


def state_dir() -> Path:
    """Where Smallink keeps its state.

    Resolution order:
    1. `$LINK_STATE_DIR` — explicit override on any OS (used by tests/sidecars).
    2. Windows: `%APPDATA%\\link` (e.g. `C:\\Users\\You\\AppData\\Roaming\\link`),
       the native per-user app-data location.
    3. macOS / Linux: `~/.config/link`.
    """
    base = os.environ.get("LINK_STATE_DIR")
    if base:
        return Path(base).expanduser()
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "link"
    return Path.home() / ".config" / "link"


def _load_dotenv(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _restrict_to_user(path: Path, *, is_dir: bool) -> None:
    """Restrict a path so only the current user can access it.

    POSIX expresses this with mode bits (0700 dir / 0600 file). Windows has no such bits —
    `os.chmod` there only toggles the read-only flag, so a 0600 chmod is a silent no-op and
    the file inherits broad ACLs (SYSTEM, Administrators, …). Use an ACL instead: strip
    inherited entries and grant the current user alone. Best-effort on Windows so a transient
    icacls failure never blocks saving a key."""
    if _IS_WINDOWS:
        user = os.environ.get("USERNAME")
        if not user:
            return
        domain = os.environ.get("USERDOMAIN")
        account = f"{domain}\\{user}" if domain else user
        # A directory grant MUST be inheritable — (OI) object-inherit for files, (CI)
        # container-inherit for subdirs — so everything created inside (the SQLite stores,
        # conversations, …) inherits the user's access. Without these flags, /inheritance:r
        # leaves the directory with a non-inheritable ACE and any child file ends up with an
        # empty DACL → sqlite3 "unable to open database file", crashing the server on launch.
        grant = f"{account}:(OI)(CI)F" if is_dir else f"{account}:F"
        try:
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", grant],
                capture_output=True,
                check=False,
            )
        except OSError:
            pass
        return
    os.chmod(path, 0o700 if is_dir else 0o600)


def write_private_text(path: str | Path, content: str) -> Path:
    """Atomically write a user-only text file using the SecretStore's OS protections."""
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        _restrict_to_user(target.parent, is_dir=True)
    except OSError:
        pass
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    _restrict_to_user(tmp, is_dir=False)
    os.replace(tmp, target)
    return target


class SecretStore:
    """System credential store with a restricted-file compatibility fallback."""

    def __init__(
        self,
        path: Optional[str | Path] = None,
        *,
        backend: Optional[str] = None,
    ) -> None:
        self.path = Path(path).expanduser() if path else state_dir() / "secrets.json"
        self.index_path = self.path.with_name("secrets.index.json")
        self._dotenv_path = self.path.parent / ".env"
        self._lock = threading.Lock()
        requested = backend or os.environ.get("SMALLINK_SECRET_BACKEND", "")
        if requested in {"file", "system"}:
            self.backend = requested
        elif path is not None or os.environ.get("PYTEST_CURRENT_TEST"):
            self.backend = "file"
        else:
            self.backend = "system"
        if self.backend == "system" and not self._system_available():
            self.backend = "file"
        if self.backend == "system":
            self._migrate_file_store()

    # -- reads ------------------------------------------------------------------
    def get(self, profile: str) -> Optional[dict[str, Any]]:
        """Return a profile with `${VAR}` refs resolved, or None if absent."""
        data = self._read().get(profile)
        if data is None:
            return None
        return self.resolve(data)

    def resolve(self, value: Any) -> Any:
        """Resolve `${VAR}` refs in a value (recursively) from env + the local `.env`."""
        env = _load_dotenv(self._dotenv_path)

        def _walk(v: Any) -> Any:
            if isinstance(v, str):
                return _REF.sub(
                    lambda m: os.environ.get(m.group(1))
                    or env.get(m.group(1))
                    or m.group(0),
                    v,
                )
            if isinstance(v, dict):
                return {k: _walk(x) for k, x in v.items()}
            if isinstance(v, list):
                return [_walk(x) for x in v]
            return v

        return _walk(value)

    def status(self) -> list[dict[str, Any]]:
        """Profile metadata only — **never** the secret values themselves."""
        out: list[dict[str, Any]] = []
        for profile, data in self._read().items():
            data = data if isinstance(data, dict) else {}
            expires = data.get("expires")
            expired = isinstance(expires, (int, float)) and expires < time.time()
            out.append(
                {
                    "profile": profile,
                    "type": data.get("type"),
                    "account": data.get("account_id"),
                    "expired": bool(expired),
                }
            )
        return out

    # -- writes -----------------------------------------------------------------
    def put(self, profile: str, data: dict[str, Any]) -> None:
        with self._lock:
            store = self._read()
            store[profile] = data
            self._write(store)

    def delete(self, profile: str) -> bool:
        with self._lock:
            store = self._read()
            if profile not in store:
                return False
            del store[profile]
            self._write(store)
            return True

    # -- internals --------------------------------------------------------------
    def _read(self) -> dict[str, Any]:
        if self.backend == "system":
            return self._read_system()
        if not self.path.is_file():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, store: dict[str, Any]) -> None:
        if self.backend == "system":
            self._write_system(store)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _restrict_to_user(self.path.parent, is_dir=True)
        except OSError:
            pass
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(store, indent=2), encoding="utf-8")
        _restrict_to_user(tmp, is_dir=False)
        os.replace(tmp, self.path)

    def _system_available(self) -> bool:
        try:
            import keyring

            return float(getattr(keyring.get_keyring(), "priority", 0)) > 0
        except Exception:
            return False

    def _read_index(self) -> dict[str, dict[str, Any]]:
        if not self.index_path.is_file():
            return {}
        try:
            value = json.loads(self.index_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_index(self, index: dict[str, dict[str, Any]]) -> None:
        write_private_text(
            self.index_path,
            json.dumps(index, indent=2, ensure_ascii=False),
        )

    def _read_system(self) -> dict[str, Any]:
        store: dict[str, Any] = {}
        for profile in self._read_index():
            value = self._credential_get(profile)
            if value is None:
                continue
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict):
                store[profile] = decoded
        return store

    def _write_system(self, store: dict[str, Any]) -> None:
        current = self._read_index()
        for profile, value in store.items():
            self._credential_put(
                profile,
                json.dumps(value, ensure_ascii=False, separators=(",", ":")),
            )
        for removed in set(current) - set(store):
            self._credential_delete(removed)
        index = {
            profile: {
                "type": value.get("type") if isinstance(value, dict) else None,
                "account_id": value.get("account_id") if isinstance(value, dict) else None,
                "expires": value.get("expires") if isinstance(value, dict) else None,
            }
            for profile, value in store.items()
        }
        self._write_index(index)

    def _credential_get(self, profile: str) -> Optional[str]:
        import keyring

        return keyring.get_password(_KEYCHAIN_SERVICE, profile)

    def _credential_put(self, profile: str, value: str) -> None:
        import keyring

        keyring.set_password(_KEYCHAIN_SERVICE, profile, value)

    def _credential_delete(self, profile: str) -> None:
        import keyring

        try:
            keyring.delete_password(_KEYCHAIN_SERVICE, profile)
        except keyring.errors.PasswordDeleteError:
            pass

    def _migrate_file_store(self) -> None:
        if not self.path.is_file() or self.index_path.is_file():
            return
        try:
            legacy = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(legacy, dict):
                return
            self._write_system(legacy)
            self.path.unlink(missing_ok=True)
        except Exception:
            self.backend = "file"
