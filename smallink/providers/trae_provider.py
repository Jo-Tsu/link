"""TRAE CLI subprocess provider — uses `traecli exec --json` as a model backend.

Runs TRAE CLI in non-interactive mode with all tools disabled, so it acts as a
pure inference relay. The TRAE token/auth is managed by the CLI itself; Smallink
does not need any API key.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Any, Iterator, Optional

from .base import (
    AssistantTurn,
    ModelCapabilities,
    ProviderClient,
    StreamChunk,
    ToolCall,
)


_TRAEX_BIN = os.environ.get("TRAEX_BIN", os.path.expanduser("~/.local/bin/traex"))

_DISABLED_TOOLS = [
    "Bash", "Read", "Write", "Edit", "Glob", "Grep", "Agent",
    "TodoWrite", "WebSearch", "WebFetch", "AskUserQuestion",
]

_DEFAULT_MODEL = "Seed-2.1-Turbo"


def _trae_home() -> Path:
    base = os.environ.get("TRAE_HOME")
    return Path(base).expanduser() if base else Path.home() / ".trae"


def _find_traex_bin() -> Optional[str]:
    """Find the traex binary. Returns path if found and executable."""
    for candidate in (
        _TRAEX_BIN,
        os.path.expanduser("~/.local/bin/traex"),
        "/usr/local/bin/traex",
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def probe_trae_status() -> dict[str, Any]:
    """Check if TRAE CLI is available and authenticated. Used for the provider
    status indicator in the GUI (replaces HTTP key verification)."""
    result: dict[str, Any] = {"ok": False}

    binary = _find_traex_bin()
    if not binary:
        result["error"] = "TRAE CLI binary not found. Install it or set TRAEX_BIN."
        return result
    result["binary"] = binary

    auth_file = _trae_home() / "cli" / "auth.json"
    if not auth_file.is_file():
        result["error"] = "Not logged in. Run `traex login` first."
        return result

    try:
        auth = json.loads(auth_file.read_text())
    except (OSError, json.JSONDecodeError):
        result["error"] = "Could not read auth.json."
        return result

    trae_auth = auth.get("trae", {})
    if not trae_auth.get("access_token"):
        result["error"] = "No access token. Run `traex login` to authenticate."
        return result

    from datetime import datetime, timezone
    expires_str = trae_auth.get("expires_at", "")
    if expires_str:
        try:
            expires = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
            if expires < datetime.now(timezone.utc):
                result["error"] = "Session expired. Run `traex login` to refresh."
                return result
        except (ValueError, TypeError):
            pass

    result["ok"] = True
    result["user_id"] = trae_auth.get("user_id", "unknown")
    result["expires_at"] = expires_str
    return result


def discover_trae_models() -> list[dict[str, Any]]:
    """Read available models from TRAE CLI's models_cache.json."""
    cache_file = _trae_home() / "cli" / "models_cache.json"
    if not cache_file.is_file():
        return []
    try:
        data = json.loads(cache_file.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    raw_models = data.get("models", [])
    results = []
    for m in raw_models:
        slug = m.get("slug", "")
        if not slug:
            continue
        visibility = m.get("visibility", "")
        if visibility == "hidden":
            continue
        config_name = m.get("config_name", slug)
        family = m.get("model_family", "")
        context_window = m.get("context_window", 0)
        description = m.get("description", "")
        results.append({
            "slug": slug,
            "label": f"{config_name} · TRAE",
            "family": family,
            "context_window": context_window,
            "description": description,
        })
    return results


def trae_model_ids() -> list[str]:
    """Return bare model slug list for the GUI picker."""
    return [m["slug"] for m in discover_trae_models()]


# ---------------------------------------------------------------------------
# Provider implementation
# ---------------------------------------------------------------------------

def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    """Flatten OpenAI-format messages into a single prompt string for exec."""
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = [
                block.get("text", "") for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            content = "\n".join(text_parts)
        if not content:
            continue
        if role == "system":
            parts.append(f"<system>\n{content}\n</system>")
        elif role == "user":
            parts.append(f"<user>\n{content}\n</user>")
        elif role == "assistant":
            parts.append(f"<assistant>\n{content}\n</assistant>")
        elif role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            parts.append(f"<tool_result tool_call_id=\"{tool_call_id}\">\n{content}\n</tool_result>")
    return "\n\n".join(parts)


def _build_tools_instruction(tools: Optional[list[dict[str, Any]]]) -> str:
    """Convert OpenAI function-calling tool schemas to a text instruction."""
    if not tools:
        return ""
    lines = [
        "You have access to the following tools. To call a tool, respond with a JSON block:",
        '```json\n{"tool_calls": [{"name": "<tool_name>", "arguments": {...}}]}\n```',
        "",
        "Available tools:",
    ]
    for tool in tools:
        func = tool.get("function", tool)
        name = func.get("name", "unknown")
        desc = func.get("description", "")
        params = func.get("parameters", {})
        lines.append(f"\n## {name}")
        if desc:
            lines.append(desc)
        if params:
            lines.append(f"Parameters: {json.dumps(params, ensure_ascii=False)}")
    return "\n".join(lines)


def _parse_tool_calls_from_text(
    text: str, tools: Optional[list[dict[str, Any]]] = None
) -> tuple[list[ToolCall], Optional[str]]:
    """Extract a balanced tool_calls JSON object and keep only narration.

    TRAE is prompted to return tool calls as text. A regex cannot safely parse that JSON because
    arguments regularly contain nested lists and objects. Decode from every opening brace instead,
    then validate names against the tools offered for this turn.
    """
    known_names = {
        str((tool.get("function") or tool).get("name"))
        for tool in tools or []
        if (tool.get("function") or tool).get("name")
    }
    decoder = json.JSONDecoder()
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            data, length = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or not isinstance(data.get("tool_calls"), list):
            continue

        parsed: list[ToolCall] = []
        for call in data["tool_calls"]:
            if not isinstance(call, dict):
                continue
            name = call.get("name")
            arguments = call.get("arguments", {})
            if not isinstance(name, str) or not name:
                continue
            if known_names and name not in known_names:
                continue
            if not isinstance(arguments, dict):
                continue
            parsed.append(
                ToolCall(
                    id=f"trae_call_{len(parsed)}",
                    name=name,
                    arguments=arguments,
                )
            )
        if not parsed:
            continue

        before = text[:start]
        after = text[start + length :]
        # Remove an optional JSON code fence without swallowing prose surrounding the call.
        before = re.sub(r"```(?:json)?\s*$", "", before, flags=re.IGNORECASE).rstrip()
        after = re.sub(r"^\s*```", "", after, count=1).strip()
        narration = "\n\n".join(part for part in (before, after) if part).strip()
        return parsed, narration or None
    return [], text or None


class TraeProvider(ProviderClient):
    """Calls TRAE CLI exec as a subprocess for model inference."""

    def __init__(self, *, model: Optional[str] = None) -> None:
        self._default_model = model or _DEFAULT_MODEL
        self._lock = threading.Lock()

    def _exec(self, prompt: str, model: str) -> Iterator[dict[str, Any]]:
        """Run traecli exec --json and yield parsed JSONL events."""
        binary = _find_traex_bin()
        if not binary:
            return

        cmd = [
            binary, "exec",
            "--json", "--ephemeral", "--skip-git-repo-check",
            "-s", "danger-full-access",
            "-m", model,
        ]
        for tool in _DISABLED_TOOLS:
            cmd.extend(["--disallowed-tool", tool])
        cmd.append(prompt)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
        finally:
            proc.wait()

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **settings: Any,
    ) -> AssistantTurn:
        prompt = _messages_to_prompt(messages)
        if tools:
            prompt = _build_tools_instruction(tools) + "\n\n" + prompt

        text_parts: list[str] = []
        reasoning_parts: list[str] = []

        for event in self._exec(prompt, model or self._default_model):
            event_type = event.get("type", "")
            if event_type == "item.completed":
                item = event.get("item", {})
                item_type = item.get("type", "")
                if item_type == "agent_message":
                    text_parts.append(item.get("text", ""))
                elif item_type == "reasoning":
                    reasoning_parts.append(item.get("text", ""))

        text = "\n".join(text_parts) if text_parts else None
        reasoning = "\n".join(reasoning_parts) if reasoning_parts else None

        tool_calls: list[ToolCall] = []
        if tools and text:
            tool_calls, text = _parse_tool_calls_from_text(text, tools)

        return AssistantTurn(
            text=text,
            tool_calls=tool_calls,
            reasoning=reasoning,
            finish_reason="tool_calls" if tool_calls else "stop",
        )

    @staticmethod
    def _simulate_stream(text: str) -> Iterator[str]:
        """Yield text in small word-level chunks to simulate streaming.

        traecli exec --json only emits item.completed (whole blocks), so we
        break completed text into word-boundary pieces for a typewriter effect.
        """
        import re
        tokens = re.split(r'(\s+)', text)
        buf = ""
        for token in tokens:
            buf += token
            if len(buf) >= 4 or token.endswith("\n"):
                yield buf
                buf = ""
        if buf:
            yield buf

    def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **settings: Any,
    ) -> Iterator[StreamChunk]:
        prompt = _messages_to_prompt(messages)
        if tools:
            prompt = _build_tools_instruction(tools) + "\n\n" + prompt

        text_parts: list[str] = []
        reasoning_parts: list[str] = []

        for event in self._exec(prompt, model or self._default_model):
            event_type = event.get("type", "")
            if event_type == "item.completed":
                item = event.get("item", {})
                item_type = item.get("type", "")
                if item_type == "agent_message":
                    text_parts.append(item.get("text", ""))
                elif item_type == "reasoning":
                    chunk_reasoning = item.get("text", "")
                    reasoning_parts.append(chunk_reasoning)
                    for piece in self._simulate_stream(chunk_reasoning):
                        yield StreamChunk(reasoning_delta=piece)

        text = "\n".join(text_parts) if text_parts else None
        reasoning = "\n".join(reasoning_parts) if reasoning_parts else None

        tool_calls: list[ToolCall] = []
        if tools and text:
            tool_calls, text = _parse_tool_calls_from_text(text, tools)

        # TRAE emits a completed message rather than genuine deltas. Parse first so the JSON tool
        # envelope is never displayed as assistant prose, then stream only the clean narration.
        if text:
            for piece in self._simulate_stream(text):
                yield StreamChunk(text_delta=piece)

        yield StreamChunk(turn=AssistantTurn(
            text=text,
            tool_calls=tool_calls,
            reasoning=reasoning,
            finish_reason="tool_calls" if tool_calls else "stop",
        ))

    def capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(
            tools=True,
            vision=True,
            pdf=False,
            parallel_tool_calls=False,
            streaming=True,
        )
