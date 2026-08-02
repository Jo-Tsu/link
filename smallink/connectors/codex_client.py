"""Codex session reader — a local-source connector's data layer.

Codex Desktop/CLI stores every session as a JSONL rollout file under
``~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl``. Each line is
``{"timestamp", "type", "payload"}``:

- ``type="session_meta"``     — first line; payload has session_id, cwd, timestamp, model_provider.
- ``type="response_item"`` with ``payload.type="message"`` — a conversation turn; payload has
  ``role`` (user/assistant/developer/…) and ``content`` = a list of parts
  ``{"type": "input_text"|"output_text"|…, "text": …}``.
- other types (event_msg, turn_context, reasoning, function_call, …) are runtime scaffolding.

This module only READS and NORMALIZES; it never writes. The connector's sync step (in the
manager) turns each normalized message into one sensory_record via the existing ingest path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

# Roles that carry real conversation content worth remembering. `developer`/`system`/`tool`
# turns are prompt scaffolding, not the user's own thinking, so they're dropped.
_KEEP_ROLES = {"user", "assistant"}

# Text parts that hold human/assistant prose (as opposed to tool payloads).
_TEXT_PART_TYPES = {"input_text", "output_text", "text"}

# Skip pathologically large rollouts. A runaway session (e.g. a long-running agent that logged
# gigabytes of tool output) would take many seconds to scan for little conversational value and
# can stall a whole sync. 64 MiB comfortably covers real human sessions.
_MAX_ROLLOUT_BYTES = 64 * 1024 * 1024


def default_sessions_root() -> Path:
    """The Codex sessions directory, honoring $CODEX_HOME (Codex's own override)."""
    import os

    base = os.environ.get("CODEX_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".codex"
    return root / "sessions"


def resolve_sessions_root(picked: Optional[str]) -> Optional[Path]:
    """Turn a user-picked folder into the actual sessions directory.

    The native folder dialog may hand us either the Codex home (``~/.codex``) or the sessions
    dir itself (``~/.codex/sessions``). Normalize both:
    - if the picked dir already contains ``rollout-*.jsonl`` or is named ``sessions``, use it;
    - else if it has a ``sessions`` subdir, use that;
    - else use the picked dir as-is (let the caller find nothing rather than guess wrong).

    Returns None when `picked` is falsy, so callers fall back to `default_sessions_root()`.
    """
    if not picked:
        return None
    root = Path(picked).expanduser()
    if root.name == "sessions":
        return root
    sub = root / "sessions"
    if sub.is_dir():
        return sub
    return root



@dataclass
class CodexMessage:
    index: int  # 0-based position within its session (stable external_id component)
    role: str
    text: str
    timestamp: Optional[str] = None


@dataclass
class CodexSession:
    session_id: str
    path: Path
    cwd: Optional[str] = None
    started_at: Optional[str] = None
    model_provider: Optional[str] = None
    originator: Optional[str] = None
    thread_source: Any = None
    completed_message_count: Optional[int] = None
    messages: list[CodexMessage] = field(default_factory=list)

    def turns(self) -> list["CodexTurn"]:
        """Group messages into conversational turns for higher-context ingestion.

        Real rollouts aren't strict U-A-U-A: a single user prompt is often followed by several
        assistant messages (e.g. `UAAUAUAA…`). A turn = one user message plus every assistant
        message that follows it, until the next user message. Leading assistant messages with no
        preceding user (rare — an assistant-opened session) form their own turn. This gives the
        memory pipeline a full question→answer unit instead of isolated fragments.
        """
        turns: list[CodexTurn] = []
        current: Optional[CodexTurn] = None
        for msg in self.messages:
            if msg.role == "user":
                if current is not None:
                    turns.append(current)
                current = CodexTurn(index=len(turns), messages=[msg])
            else:  # assistant (only user/assistant survive parsing)
                if current is None:
                    current = CodexTurn(index=len(turns), messages=[msg])
                else:
                    current.messages.append(msg)
        if current is not None:
            turns.append(current)
        return turns


@dataclass
class CodexTurn:
    index: int  # 0-based position within its session (stable external_id component)
    messages: list[CodexMessage]

    @property
    def timestamp(self) -> Optional[str]:
        return self.messages[0].timestamp if self.messages else None

    def as_text(self) -> str:
        """Render the turn as a readable ``User:``/``Assistant:`` transcript."""
        lines = []
        for m in self.messages:
            label = "User" if m.role == "user" else "Assistant"
            lines.append(f"{label}: {m.text}")
        return "\n\n".join(lines)


def _extract_text(content: Any) -> str:
    """Flatten a message's `content` into plain text, keeping only prose parts.

    `content` is normally a list of ``{"type", "text"}`` parts; tolerate a bare string too.
    """
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") in _TEXT_PART_TYPES:
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
    return "\n".join(chunks).strip()


def _is_noise(text: str) -> bool:
    """Drop Codex's injected scaffolding turns that aren't real user/assistant content.

    Codex embeds a lot of protocol machinery into the message stream. Measured against real
    rollouts, ~57% of message turns are scaffolding, in four families:

    1. Structured protocol payloads — the safety-approval verdicts the model emits as pure
       JSON (``{"outcome":"allow"}``, ``{"risk_level":…,"outcome":…}``). Never prose.
    2. The approval-request preamble Codex prepends when asking the model to assess an action
       ("The following is the Codex agent history whose request action you are assessing…").
    3. Instruction scaffolding: AGENTS.md dumps and ``<INSTRUCTIONS>`` blocks.
    4. Injected XML context blocks (``<environment_context>``, ``<recommended_plugins>``, …).

    We deliberately KEEP real user turns that happen to start with a heading like
    ``# Files mentioned by the user:`` — those are genuine content, not scaffolding.
    """
    if not text or not text.strip():
        return True
    stripped = text.strip()

    # (1) Pure JSON payloads = protocol machinery, not conversation.
    if (stripped.startswith("{") and stripped.endswith("}")) or (
        stripped.startswith("[") and stripped.endswith("]")
    ):
        try:
            json.loads(stripped)
            return True
        except (ValueError, TypeError):
            pass  # not valid JSON → treat as prose

    # (2) Approval-assessment preamble.
    if stripped.startswith("The following is the Codex agent history"):
        return True

    # Compatibility wrappers injected by older TRAE CLI builds.
    if stripped.startswith("Today's date is ") and "Timezone:" in stripped:
        return True

    # (3) Instruction scaffolding.
    if stripped.startswith("# AGENTS.md") or "<INSTRUCTIONS>" in stripped[:200]:
        return True

    # (4) Injected XML context blocks. Only when the WHOLE message is a tag block — a real
    # message that merely mentions "<tag>" mid-sentence won't start with one.
    if stripped.startswith((
        "<environment_context>",
        "<permissions instructions>",
        "<collaboration_mode>",
        "<skills_instructions>",
        "<system-reminder>",
        "<user_instructions>",
        "<recommended_plugins>",
        "<available_plugins>",
    )):
        return True

    return False


def parse_session(path: Path) -> Optional[CodexSession]:
    """Parse one rollout JSONL file into a CodexSession, or None if it has no usable messages.

    Malformed lines are skipped, not fatal — a rollout can be truncated if Codex was killed.
    """
    session: Optional[CodexSession] = None
    messages: list[CodexMessage] = []
    idx = 0
    try:
        if path.stat().st_size > _MAX_ROLLOUT_BYTES:
            return None  # runaway rollout — skip rather than stall the sync
    except OSError:
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = obj.get("type")
                payload = obj.get("payload") or {}
                if kind == "session_meta":
                    session = CodexSession(
                        session_id=str(payload.get("session_id") or payload.get("id") or path.stem),
                        path=path,
                        cwd=payload.get("cwd"),
                        started_at=payload.get("timestamp") or obj.get("timestamp"),
                        model_provider=payload.get("model_provider"),
                        originator=payload.get("originator"),
                        thread_source=payload.get("thread_source"),
                    )
                elif kind == "response_item" and payload.get("type") == "message":
                    role = payload.get("role")
                    if role not in _KEEP_ROLES:
                        continue
                    text = _extract_text(payload.get("content"))
                    if _is_noise(text):
                        continue
                    messages.append(
                        CodexMessage(
                            index=idx,
                            role=role,
                            text=text,
                            timestamp=obj.get("timestamp"),
                        )
                    )
                    idx += 1
                elif kind == "event_msg" and payload.get("type") == "task_complete":
                    # TRAE CLI may keep appending to a live rollout while a connector sync runs.
                    # Remember the last durable turn boundary; the TraeX reader trims to it.
                    # Codex keeps its existing behavior and ignores this marker.
                    if session is not None:
                        session.completed_message_count = len(messages)
    except OSError:
        return None
    if session is None:
        # A rollout with no session_meta (rare/corrupt): fall back to the filename uuid.
        session = CodexSession(session_id=path.stem, path=path)
    session.messages = messages
    return session if messages else None


def iter_session_files(root: Optional[Path] = None) -> list[Path]:
    """All rollout files, newest first (by filename, which is timestamp-prefixed)."""
    root = root or default_sessions_root()
    if not root.exists():
        return []
    files = list(root.rglob("rollout-*.jsonl"))
    # Filenames are `rollout-<ISO-ish timestamp>-<uuid>.jsonl`, so lexical sort == chronological.
    files.sort(key=lambda p: p.name, reverse=True)
    return files


def read_sessions(
    *, limit: Optional[int] = None, root: Optional[Path] = None
) -> Iterator[CodexSession]:
    """Yield parsed sessions newest-first. `limit` caps how many session FILES are read
    (not messages), so a small N stays cheap even with thousands of rollouts."""
    files = iter_session_files(root)
    if limit is not None:
        files = files[: max(0, int(limit))]
    for path in files:
        session = parse_session(path)
        if session is not None:
            yield session
