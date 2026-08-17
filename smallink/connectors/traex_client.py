"""TraeX / TRAE CLI local session reader.

TRAE CLI stores append-only rollout JSONL files under
``~/.trae/cli/sessions/YYYY/MM/DD``. The wire format is compatible with the
Codex rollout reader, but the source identity and session-selection rules are
different: only user-owned top-level threads are imported. Subagent rollouts
are implementation detail and must not become personal memory source data.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterator, Optional

from .codex_client import CodexSession, iter_session_files, parse_session


def default_sessions_root() -> Path:
    base = os.environ.get("TRAE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".trae"
    return root / "cli" / "sessions"


def resolve_sessions_root(picked: Optional[str]) -> Optional[Path]:
    """Normalize ``~/.trae``, ``~/.trae/cli`` or the sessions directory."""
    if not picked:
        return None
    root = Path(picked).expanduser()
    if root.name == "sessions":
        return root
    for relative in (Path("cli") / "sessions", Path("sessions")):
        candidate = root / relative
        if candidate.is_dir():
            return candidate
    return root


def is_user_session(session: CodexSession) -> bool:
    """Keep main user threads and legacy files that predate thread_source."""
    return session.thread_source in (None, "user")


def completed_session(session: CodexSession) -> Optional[CodexSession]:
    """Trim a live rollout to its last completed task boundary."""
    count = session.completed_message_count
    if count is None:
        return session
    session.messages = session.messages[:count]
    return session if session.messages else None


def probe_sessions_root(root: Optional[Path]) -> dict[str, Any]:
    resolved = Path(root).expanduser() if root is not None else default_sessions_root()
    exists = resolved.exists()
    readable = exists and resolved.is_dir() and os.access(resolved, os.R_OK)
    files = iter_session_files(resolved) if readable else []
    valid = 0
    user_sessions = 0
    subagent_sessions = 0
    for path in files[:50]:
        session = parse_session(path)
        if session is None:
            continue
        valid += 1
        if is_user_session(session):
            user_sessions += 1
        else:
            subagent_sessions += 1
    return {
        "root_path": str(resolved),
        "path_exists": exists,
        "path_readable": readable,
        "rollout_files_found": len(files),
        "valid_sessions_found": valid,
        "user_sessions_found": user_sessions,
        "subagent_sessions_excluded": subagent_sessions,
        "ok": bool(readable and files and user_sessions),
    }


def read_sessions(
    *, limit: Optional[int] = None, root: Optional[Path] = None
) -> Iterator[CodexSession]:
    """Yield newest user-owned TraeX sessions, excluding subagent rollouts."""
    cap = None if limit is None else max(0, int(limit))
    if cap == 0:
        return
    matched = 0
    for path in iter_session_files(root or default_sessions_root()):
        session = parse_session(path)
        if session is None or not is_user_session(session):
            continue
        session = completed_session(session)
        if session is None:
            continue
        yield session
        matched += 1
        if cap is not None and matched >= cap:
            return
