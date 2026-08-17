"""Persistent memory — adapter interface + scopes.

Memory is the long-lived layer above transient conversation state: durable facts,
preferences, task notes, summaries. Scopes: global (user-wide), workspace (per project),
session. Backends are adapters (`SQLiteMemoryStore` now, `PostgresMemoryStore` later).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Scope(str, Enum):
    GLOBAL = "global"
    WORKSPACE = "workspace"
    SESSION = "session"


@dataclass
class MemoryItem:
    id: int
    scope: Scope
    content: str
    key: Optional[str] = None  # the memory_type tag (see MemoryView's 10 types); None = untyped
    workspace: Optional[str] = None
    session_id: Optional[str] = None
    created_at: Optional[str] = None
    # Lifecycle: "active" (confirmed, injectable) vs "pending" (pipeline output awaiting
    # confirmation — never injected into a prompt) vs "archived". Defaulted so existing rows
    # and older callers keep behaving exactly as before.
    status: str = "active"
    updated_at: Optional[str] = None
    # The sensory_records.record_id this memory was distilled from (pipeline provenance), or
    # None for hand-written memories.
    source_record_id: Optional[str] = None


class MemoryStore(ABC):
    @abstractmethod
    def add(
        self,
        content: str,
        *,
        scope: Scope = Scope.WORKSPACE,
        key: Optional[str] = None,
        workspace: Optional[str] = None,
        session_id: Optional[str] = None,
        status: str = "active",
        source_record_id: Optional[str] = None,
    ) -> MemoryItem: ...

    @abstractmethod
    def get(self, item_id: int) -> Optional[MemoryItem]: ...

    @abstractmethod
    def list(
        self,
        *,
        scope: Optional[Scope] = None,
        workspace: Optional[str] = None,
        session_id: Optional[str] = None,
        status: Optional[str] = "active",
    ) -> list[MemoryItem]: ...

    @abstractmethod
    def update(self, item_id: int, content: str) -> Optional[MemoryItem]: ...

    @abstractmethod
    def delete(self, item_id: int) -> bool: ...


def format_memories(items: list[MemoryItem]) -> str:
    """Render memories for injection into the system prompt. Ids are shown so the agent
    can revise a memory (`memory_update`) or retire it (`memory_forget`)."""
    if not items:
        return ""
    lines = [f"- [#{item.id}] {item.content}" for item in items]
    return "Known memories (from earlier sessions):\n" + "\n".join(lines)
