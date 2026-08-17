"""Budgeted, scope-aware retrieval for formal memories."""

from __future__ import annotations

import re
from typing import Iterable

from ..attachments import content_to_text
from .base import MemoryItem


_TOKEN = re.compile(r"[A-Za-z0-9_./:-]{2,}|[\u4e00-\u9fff]{2,}")


def query_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return content_to_text(message.get("content"), image_placeholder="")
    return ""


def select_memories(
    items: Iterable[MemoryItem],
    query: str,
    *,
    limit: int = 12,
    char_budget: int = 4_000,
) -> list[MemoryItem]:
    candidates = list(items)
    if not candidates:
        return []
    terms = {token.lower() for token in _TOKEN.findall(query)}

    def score(item: MemoryItem) -> tuple[int, int, int]:
        content_terms = {token.lower() for token in _TOKEN.findall(item.content)}
        overlap = len(terms & content_terms)
        phrase = int(bool(query.strip()) and query.strip().lower() in item.content.lower())
        return phrase, overlap, item.id

    ranked = sorted(candidates, key=score, reverse=True)
    if terms:
        matched = [item for item in ranked if score(item)[:2] != (0, 0)]
        ranked = matched or ranked[:3]
    else:
        ranked = ranked[:3]

    selected: list[MemoryItem] = []
    used = 0
    for item in ranked:
        cost = len(item.content) + 16
        if selected and used + cost > char_budget:
            continue
        if cost > char_budget:
            continue
        selected.append(item)
        used += cost
        if len(selected) >= limit:
            break
    return selected
