"""Memory processing pipeline — clean → tag → layer.

Turns immutable raw `sensory_records` into structured memories. Three steps, borrowed from
mem0's fact-extraction idea but with NO vector store and NO auto-confirmation:

1. clean  — one LLM call distills a raw record into 1..N self-contained facts.
2. tag    — each fact gets a `memory_type` (the 10 MemoryView types) via the same call.
3. layer  — each fact is routed to a scope (global / workspace / session).

Every produced memory is written with status="pending": it is NOT injected into any prompt
and NOT visible in the confirmed-memory view until a future confirmation phase promotes it.
The pipeline never mutates raw records (they stay immutable); "already processed" is derived
from `memories.source_record_id`, so re-running is idempotent.

This module is intentionally decoupled from the agent runtime: nothing here registers a tool
or touches a live conversation. It is driven only by an explicit manager call / POST route.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional

from .base import MemoryStore, Scope

if TYPE_CHECKING:  # avoid a runtime import cycle with the sensory package
    from ..sensory import SQLiteSensoryStore
    from ..sensory.models import SensoryRecord

# The single source of truth for memory types — must stay in sync with MemoryView.tsx's
# MEMORY_TYPES. Stored in the memory row's `key` column.
MEMORY_TYPES = (
    "user_preference",
    "project_context",
    "product_decision",
    "reasoning_process",
    "open_question",
    "reusable_pattern",
    "work_habit",
    "artifact_summary",
    "document_insight",
    "life_memory",
)

_SCOPE_VALUES = {s.value for s in Scope}

# Adapted from mem0's FACT_RETRIEVAL_PROMPT, but the output contract is typed + scoped so the
# clean/tag/layer steps happen in one structured call.
EXTRACTION_PROMPT = """You extract durable personal memories from a piece of raw captured data.

Return distinct, self-contained facts worth remembering long-term — preferences, decisions,
project context, open questions, reusable methods, habits, or durable personal context. Ignore
transient chatter, greetings, and ephemeral task state. If nothing is worth remembering, return
an empty list.

For each fact, choose:
- memory_type — one of:
  user_preference   : stable choices about tools, style, interaction
  project_context   : goals, scope, constraints, current stage of a project
  product_decision  : confirmed product/technical choices and their reasoning
  reasoning_process : how the person evaluates options and reaches conclusions
  open_question     : an important question that still needs an answer
  reusable_pattern  : a method or approach worth reusing
  work_habit        : a recurring way the person plans, reviews, or executes
  artifact_summary  : a durable summary of a report, code, or deliverable
  document_insight  : an important conclusion extracted from a document
  life_memory       : long-term personal context outside project work
- scope — one of:
  global    : true everywhere, about the person themselves
  workspace : specific to the current project/workspace
  session   : only relevant to the current task (rarely worth persisting)

Return ONLY valid JSON, no prose, no code fences:
{"facts": [{"content": "<self-contained fact>", "memory_type": "<type>", "scope": "<scope>"}]}
If there is nothing to remember, return {"facts": []}."""


def _parse_facts(text: Optional[str]) -> list[dict[str, Any]]:
    """Parse the model's JSON, tolerating ```json fences. Raises on anything unusable so the
    caller can fall back."""
    if not text or not text.strip():
        raise ValueError("empty model response")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # strip a leading ```json / ``` fence and the trailing ```
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    data = json.loads(cleaned)
    facts = data.get("facts") if isinstance(data, dict) else None
    if not isinstance(facts, list):
        raise ValueError("response has no 'facts' list")
    return facts


class MemoryPipeline:
    def __init__(
        self,
        sensory_store: "SQLiteSensoryStore",
        memory_store: MemoryStore,
        provider: Any,
        *,
        model: str,
    ) -> None:
        self.sensory_store = sensory_store
        self.memory_store = memory_store
        self.provider = provider
        self.model = model

    def _processed_record_ids(self) -> set[str]:
        """record_ids already turned into memories — status=None to include pending output."""
        return {
            m.source_record_id
            for m in self.memory_store.list(status=None)
            if m.source_record_id
        }

    def select_unprocessed(
        self, record_ids: Optional[list[str]] = None, limit: int = 50
    ) -> list["SensoryRecord"]:
        done = self._processed_record_ids()
        if record_ids:
            records = [self.sensory_store.get(rid) for rid in record_ids]
            candidates = [r for r in records if r is not None]
        else:
            candidates = self.sensory_store.list(
                governance_status="pending", limit=max(1, min(int(limit), 500))
            )
        return [r for r in candidates if r.record_id not in done]

    def process(
        self, record_ids: Optional[list[str]] = None, limit: int = 50
    ) -> dict[str, Any]:
        records = self.select_unprocessed(record_ids, limit)
        memories_created = 0
        fallbacks = 0
        for record in records:
            try:
                facts = self._extract(record)
            except Exception:
                # LLM/parse failure must never lose the capture: store the raw text as one
                # untyped pending memory so a human can still see and later confirm it.
                self._write_fallback(record)
                fallbacks += 1
                continue
            if not facts:
                # Nothing worth remembering. We create no memory; the record is cheap to
                # re-scan later and simply yields nothing again.
                continue
            memories_created += self._write_facts(record, facts)
        return {
            "processed_records": len(records),
            "memories_created": memories_created,
            "fallbacks": fallbacks,
        }

    def _extract(self, record: "SensoryRecord") -> list[dict[str, Any]]:
        messages = [
            {"role": "system", "content": EXTRACTION_PROMPT},
            {"role": "user", "content": record.normalized_content},
        ]
        turn = self.provider.complete(model=self.model, messages=messages, tools=None)
        return _parse_facts(getattr(turn, "text", None))

    def _write_facts(
        self, record: "SensoryRecord", facts: list[dict[str, Any]]
    ) -> int:
        written = 0
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            content = str(fact.get("content", "")).strip()
            if not content:
                continue
            raw_type = fact.get("memory_type")
            memory_type = raw_type if raw_type in MEMORY_TYPES else None
            scope, workspace = self._resolve_scope(fact.get("scope"), record)
            self.memory_store.add(
                content,
                scope=scope,
                key=memory_type,
                workspace=workspace,
                status="pending",
                source_record_id=record.record_id,
            )
            written += 1
        return written

    def _write_fallback(self, record: "SensoryRecord") -> None:
        scope, workspace = self._resolve_scope(None, record)
        self.memory_store.add(
            record.normalized_content,
            scope=scope,
            key=None,
            workspace=workspace,
            status="pending",
            source_record_id=record.record_id,
        )

    @staticmethod
    def _resolve_scope(
        raw_scope: Any, record: "SensoryRecord"
    ) -> tuple[Scope, Optional[str]]:
        """Map the model's scope hint to a Scope. Fallback: workspace when the record carries a
        project_path, else global. workspace is only set for WORKSPACE scope."""
        value = raw_scope if raw_scope in _SCOPE_VALUES else None
        if value is None:
            value = Scope.WORKSPACE.value if record.project_path else Scope.GLOBAL.value
        scope = Scope(value)
        if scope is Scope.WORKSPACE:
            return scope, record.project_path
        return scope, None
