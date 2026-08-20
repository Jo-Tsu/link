"""Read-only knowledge retrieval tools exposed to project-scoped agents."""

from __future__ import annotations

from typing import Optional

import aisuite as ai

from .store import SQLiteKnowledgeStore


def knowledge_tools(
    store: SQLiteKnowledgeStore, *, project_id: Optional[str]
) -> list:
    """Build explainable, project-scoped retrieval tools for an agent session."""

    def knowledge_search(query: str, limit: int = 8) -> dict:
        """Search the current project's indexed knowledge and return cited results.

        Use this before answering questions that may depend on project documents or
        connected application materials. Results include the matching passage, score
        explanation, and immutable source record id when one is available.

        Args:
            query (str): Natural-language words or phrases to find.
            limit (int): Maximum number of results, from 1 to 20.
        """
        if project_id is None:
            return {
                "query": query,
                "project_id": None,
                "results": [],
                "strategy": "hybrid_lexical_v1",
                "message": "This conversation is not attached to a project.",
            }
        result = store.search(
            query,
            project_id=project_id,
            limit=max(1, min(int(limit), 20)),
        )
        return {"project_id": project_id, **result}

    return [
        ai.tool(
            knowledge_search,
            metadata=ai.ToolMetadata(
                category="knowledge",
                risk_level="low",
                capabilities=["retrieve", "cite_source"],
            ),
        )
    ]
