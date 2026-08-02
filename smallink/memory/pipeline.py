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
import re
from typing import TYPE_CHECKING, Any, Optional

from .base import MemoryStore, Scope
from .governance import SQLiteGovernanceStore

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
PROMPT_VERSION = "memory-extraction-v2"
_SECRET_PATTERN = re.compile(
    r"(?i)(password|passwd|secret|api[_ -]?key|access[_ -]?token|refresh[_ -]?token)"
    r"\s*[:=]\s*[^\s,;]+"
)

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
        governance_store: Optional[SQLiteGovernanceStore] = None,
        allow_sensitive_cloud: bool = False,
    ) -> None:
        self.sensory_store = sensory_store
        self.memory_store = memory_store
        self.provider = provider
        self.model = model
        self.governance_store = governance_store or SQLiteGovernanceStore(
            getattr(memory_store, "path", ":memory:")
        )
        self.allow_sensitive_cloud = allow_sensitive_cloud

    def select_unprocessed(
        self,
        task_id: str,
        record_ids: Optional[list[str]] = None,
        limit: int = 50,
        *,
        retry_failed: bool = False,
    ) -> list["SensoryRecord"]:
        return self.sensory_store.claim_for_governance(
            task_id,
            record_ids=record_ids,
            limit=limit,
            retry_failed=retry_failed,
        )

    def process(
        self,
        record_ids: Optional[list[str]] = None,
        limit: int = 50,
        *,
        retry_failed: bool = False,
    ) -> dict[str, Any]:
        task_id = self.governance_store.create_task(
            [], model=self.model, prompt_version=PROMPT_VERSION
        )
        records = self.select_unprocessed(
            task_id,
            record_ids,
            limit,
            retry_failed=retry_failed,
        )
        self.governance_store.attach_records(
            task_id, [record.record_id for record in records]
        )
        candidates_created = 0
        try:
            for record in records:
                try:
                    self._ensure_allowed(record)
                    facts = self._extract(record)
                    if not facts:
                        self.sensory_store.finish_governance(
                            record.record_id, task_id, "skipped"
                        )
                        self.governance_store.mark_record(
                            task_id, record.record_id, "skipped"
                        )
                        continue
                    candidates_created += self._write_facts(task_id, record, facts)
                    self.sensory_store.finish_governance(
                        record.record_id, task_id, "processed"
                    )
                    self.governance_store.mark_record(
                        task_id, record.record_id, "processed"
                    )
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"[:1000]
                    self.sensory_store.finish_governance(
                        record.record_id, task_id, "failed", error=error
                    )
                    self.governance_store.mark_record(
                        task_id, record.record_id, "failed", error=error
                    )
        finally:
            self.sensory_store.release_governance_task(task_id)
        task = self.governance_store.finish_task(task_id)
        return {
            "task_id": task_id,
            "status": task["status"],
            "processed_records": task["processed_records"],
            "candidates_created": candidates_created,
            "skipped_records": task["skipped_records"],
            "failed_records": task["failed_records"],
        }

    def _ensure_allowed(self, record: "SensoryRecord") -> None:
        sensitivity = str(record.sensitivity or "unknown").lower()
        if sensitivity == "secret":
            raise PermissionError("secret records are excluded from AI governance")
        if sensitivity == "sensitive" and not (
            self.allow_sensitive_cloud or self._is_local_model()
        ):
            raise PermissionError(
                "sensitive records require a local model or explicit cloud permission"
            )

    def _is_local_model(self) -> bool:
        return self.model.startswith("ollama:")

    def _extract(self, record: "SensoryRecord") -> list[dict[str, Any]]:
        content = _SECRET_PATTERN.sub(r"\1=[REDACTED]", record.normalized_content)
        messages = [
            {"role": "system", "content": EXTRACTION_PROMPT},
            {"role": "user", "content": content},
        ]
        turn = self.provider.complete(model=self.model, messages=messages, tools=None)
        return _parse_facts(getattr(turn, "text", None))

    def _write_facts(
        self,
        task_id: str,
        record: "SensoryRecord",
        facts: list[dict[str, Any]],
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
            scope, workspace, session_id = self._resolve_scope(
                fact.get("scope"), record
            )
            confidence: Optional[float] = None
            try:
                if fact.get("confidence") is not None:
                    confidence = max(0.0, min(float(fact["confidence"]), 1.0))
            except (TypeError, ValueError):
                confidence = None
            self.governance_store.add_candidate(
                task_id=task_id,
                content=content,
                memory_type=memory_type,
                scope=scope,
                workspace=workspace,
                session_id=session_id,
                model=self.model,
                prompt_version=PROMPT_VERSION,
                source_ids=[record.record_id],
                confidence=confidence,
            )
            written += 1
        return written

    @staticmethod
    def _resolve_scope(
        raw_scope: Any, record: "SensoryRecord"
    ) -> tuple[Scope, Optional[str], Optional[str]]:
        """Map the model's scope hint to a Scope. Fallback: workspace when the record carries a
        project_path, else global. workspace is only set for WORKSPACE scope."""
        value = raw_scope if raw_scope in _SCOPE_VALUES else None
        if value is None:
            value = Scope.WORKSPACE.value if record.project_path else Scope.GLOBAL.value
        scope = Scope(value)
        if scope is Scope.WORKSPACE:
            return scope, record.project_path, None
        if scope is Scope.SESSION:
            return scope, None, record.conversation_id
        return scope, None, None
