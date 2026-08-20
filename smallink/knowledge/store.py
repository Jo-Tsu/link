"""Lightweight SQLite knowledge repository with explainable hybrid retrieval."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..sqlite import connect_sqlite


_WORD = re.compile(r"[A-Za-z0-9_./:-]{2,}|[\u4e00-\u9fff]+")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _terms(text: str) -> list[str]:
    """Tokenize Latin text and add single-character/bigram terms for CJK search."""
    found: list[str] = []
    for token in _WORD.findall(text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            found.extend(token)
            found.extend(token[index : index + 2] for index in range(len(token) - 1))
        else:
            found.append(token)
    return list(dict.fromkeys(term for term in found if term.strip()))


def _chunks(content: str, *, target: int = 1_600, overlap: int = 180) -> list[str]:
    clean = content.replace("\r\n", "\n").strip()
    if not clean:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", clean) if part.strip()]
    output: list[str] = []
    current = ""
    for paragraph in paragraphs or [clean]:
        if len(paragraph) > target:
            if current:
                output.append(current)
                current = ""
            start = 0
            while start < len(paragraph):
                output.append(paragraph[start : start + target])
                if start + target >= len(paragraph):
                    break
                start += max(1, target - overlap)
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if current and len(candidate) > target:
            output.append(current)
            prefix = current[-overlap:] if overlap else ""
            current = f"{prefix}\n\n{paragraph}".strip()
        else:
            current = candidate
    if current:
        output.append(current)
    return output


class SQLiteKnowledgeStore:
    """Knowledge stays separate from personal memory while preserving source provenance."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = connect_sqlite(path)
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS knowledge_items (
                item_id TEXT PRIMARY KEY,
                project_id TEXT,
                source_record_id TEXT,
                source_type TEXT NOT NULL,
                external_id TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                current_version INTEGER NOT NULL DEFAULT 1,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(project_id, source_type, external_id)
            );
            CREATE INDEX IF NOT EXISTS idx_knowledge_items_project
                ON knowledge_items(project_id, updated_at DESC);
            CREATE TABLE IF NOT EXISTS knowledge_versions (
                version_id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL REFERENCES knowledge_items(item_id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                source_record_id TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(item_id, version)
            );
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                chunk_id TEXT PRIMARY KEY,
                item_id TEXT NOT NULL REFERENCES knowledge_items(item_id) ON DELETE CASCADE,
                project_id TEXT,
                version INTEGER NOT NULL,
                ordinal INTEGER NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                term_count INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(item_id, version, ordinal)
            );
            CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_item
                ON knowledge_chunks(item_id, version, ordinal);
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(
                chunk_id UNINDEXED,
                item_id UNINDEXED,
                project_id UNINDEXED,
                title_terms,
                content_terms,
                tokenize='unicode61 remove_diacritics 2'
            );
            """
        )
        self._conn.commit()

    def upsert(
        self,
        *,
        project_id: Optional[str],
        source_type: str,
        external_id: str,
        title: str,
        content: str,
        source_record_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        clean_title = " ".join(str(title or "Untitled").split())[:300] or "Untitled"
        clean_content = str(content or "").strip()
        if not clean_content:
            raise ValueError("knowledge content is required")
        digest = hashlib.sha256(clean_content.encode("utf-8")).hexdigest()
        now = _now()
        stable_external_id = str(external_id or digest)
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM knowledge_items
                WHERE COALESCE(project_id, '')=COALESCE(?, '')
                  AND source_type=? AND external_id=?
                """,
                (project_id, source_type, stable_external_id),
            ).fetchone()
            if row is not None and row["content_hash"] == digest:
                self._conn.execute(
                    """
                    UPDATE knowledge_items
                    SET title=?, source_record_id=COALESCE(?, source_record_id),
                        metadata_json=?, status='active', updated_at=?
                    WHERE item_id=?
                    """,
                    (
                        clean_title,
                        source_record_id,
                        json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                        now,
                        row["item_id"],
                    ),
                )
                self._conn.commit()
                return self.get(str(row["item_id"])) or {}

            item_id = str(row["item_id"]) if row is not None else _id("knowledge")
            version = int(row["current_version"]) + 1 if row is not None else 1
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                if row is None:
                    self._conn.execute(
                        """
                        INSERT INTO knowledge_items (
                            item_id, project_id, source_record_id, source_type, external_id,
                            title, content, content_hash, current_version, metadata_json,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item_id,
                            project_id,
                            source_record_id,
                            source_type,
                            stable_external_id,
                            clean_title,
                            clean_content,
                            digest,
                            version,
                            json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                            now,
                            now,
                        ),
                    )
                else:
                    self._conn.execute(
                        """
                        UPDATE knowledge_items SET source_record_id=?, title=?, content=?,
                            content_hash=?, current_version=?, metadata_json=?, status='active',
                            updated_at=? WHERE item_id=?
                        """,
                        (
                            source_record_id,
                            clean_title,
                            clean_content,
                            digest,
                            version,
                            json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                            now,
                            item_id,
                        ),
                    )
                self._conn.execute(
                    """
                    INSERT INTO knowledge_versions (
                        version_id, item_id, version, title, content, content_hash,
                        source_record_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (_id("knowledge-version"), item_id, version, clean_title, clean_content, digest, source_record_id, now),
                )
                old_chunk_ids = [
                    str(chunk["chunk_id"])
                    for chunk in self._conn.execute(
                        "SELECT chunk_id FROM knowledge_chunks WHERE item_id=?", (item_id,)
                    ).fetchall()
                ]
                if old_chunk_ids:
                    placeholders = ",".join("?" for _ in old_chunk_ids)
                    self._conn.execute(
                        f"DELETE FROM knowledge_chunks_fts WHERE chunk_id IN ({placeholders})",
                        old_chunk_ids,
                    )
                self._conn.execute("DELETE FROM knowledge_chunks WHERE item_id=?", (item_id,))
                title_terms = " ".join(_terms(clean_title))
                for ordinal, chunk_content in enumerate(_chunks(clean_content)):
                    chunk_id = _id("knowledge-chunk")
                    chunk_digest = hashlib.sha256(chunk_content.encode("utf-8")).hexdigest()
                    content_terms = _terms(chunk_content)
                    self._conn.execute(
                        """
                        INSERT INTO knowledge_chunks (
                            chunk_id, item_id, project_id, version, ordinal, content,
                            content_hash, term_count, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (chunk_id, item_id, project_id, version, ordinal, chunk_content, chunk_digest, len(content_terms), now),
                    )
                    self._conn.execute(
                        """
                        INSERT INTO knowledge_chunks_fts (
                            chunk_id, item_id, project_id, title_terms, content_terms
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (chunk_id, item_id, project_id, title_terms, " ".join(content_terms)),
                    )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return self.get(item_id) or {}

    def get(self, item_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT i.*, COUNT(c.chunk_id) AS chunk_count
                FROM knowledge_items i
                LEFT JOIN knowledge_chunks c ON c.item_id=i.item_id
                WHERE i.item_id=? GROUP BY i.item_id
                """,
                (item_id,),
            ).fetchone()
        return self._item(row) if row else None

    def list(
        self,
        *,
        project_id: Optional[str] = None,
        status: Optional[str] = "active",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if project_id is not None:
            clauses.append("i.project_id=?")
            params.append(project_id)
        if status is not None:
            clauses.append("i.status=?")
            params.append(status)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT i.*, COUNT(c.chunk_id) AS chunk_count
                FROM knowledge_items i
                LEFT JOIN knowledge_chunks c ON c.item_id=i.item_id
                {where} GROUP BY i.item_id
                ORDER BY i.updated_at DESC LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._item(row) for row in rows]

    def count(self, *, project_id: Optional[str] = None, status: str = "active") -> int:
        query = "SELECT COUNT(*) FROM knowledge_items WHERE status=?"
        params: list[Any] = [status]
        if project_id is not None:
            query += " AND project_id=?"
            params.append(project_id)
        with self._lock:
            row = self._conn.execute(query, params).fetchone()
        return int(row[0])

    def archive(self, item_id: str, archived: bool = True) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE knowledge_items SET status=?, updated_at=? WHERE item_id=?",
                ("archived" if archived else "active", _now(), item_id),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    def search(
        self,
        query: str,
        *,
        project_id: Optional[str] = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        clean_query = str(query or "").strip()
        query_terms = _terms(clean_query)
        if not clean_query or not query_terms:
            return {"query": clean_query, "results": [], "strategy": "hybrid_lexical_v1"}
        match = " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in query_terms[:40])
        params: list[Any] = [match]
        project_clause = ""
        if project_id is not None:
            project_clause = " AND i.project_id=?"
            params.append(project_id)
        params.append(max(20, min(int(limit) * 8, 300)))
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT c.*, i.title, i.source_type, i.external_id, i.source_record_id,
                       i.metadata_json, i.updated_at,
                       bm25(knowledge_chunks_fts, 0.0, 0.0, 0.0, 2.0, 1.0) AS fts_rank
                FROM knowledge_chunks_fts
                JOIN knowledge_chunks c ON c.chunk_id=knowledge_chunks_fts.chunk_id
                JOIN knowledge_items i ON i.item_id=c.item_id
                WHERE knowledge_chunks_fts MATCH ? AND i.status='active'{project_clause}
                ORDER BY fts_rank LIMIT ?
                """,
                params,
            ).fetchall()
        if not rows:
            like = f"%{clean_query.lower()}%"
            fallback_params: list[Any] = [like, like]
            fallback_clause = ""
            if project_id is not None:
                fallback_clause = " AND i.project_id=?"
                fallback_params.append(project_id)
            fallback_params.append(max(20, min(int(limit) * 8, 300)))
            with self._lock:
                rows = self._conn.execute(
                    f"""
                    SELECT c.*, i.title, i.source_type, i.external_id, i.source_record_id,
                           i.metadata_json, i.updated_at, 0.0 AS fts_rank
                    FROM knowledge_chunks c JOIN knowledge_items i ON i.item_id=c.item_id
                    WHERE i.status='active' AND (
                        LOWER(i.title) LIKE ? OR LOWER(c.content) LIKE ?
                    ){fallback_clause} ORDER BY i.updated_at DESC LIMIT ?
                    """,
                    fallback_params,
                ).fetchall()

        max_rank = max((abs(float(row["fts_rank"] or 0.0)) for row in rows), default=0.0)
        query_set = set(query_terms)
        ranked: list[dict[str, Any]] = []
        seen_items: set[str] = set()
        for row in rows:
            item_id = str(row["item_id"])
            chunk_terms = set(_terms(str(row["title"]) + " " + str(row["content"])))
            matched = sorted(query_set & chunk_terms)
            lexical = abs(float(row["fts_rank"] or 0.0)) / max_rank if max_rank else 0.0
            coverage = len(matched) / max(1, len(query_set))
            phrase = float(clean_query.lower() in (str(row["title"]) + " " + str(row["content"])).lower())
            score = round(0.55 * lexical + 0.30 * coverage + 0.15 * phrase, 6)
            if item_id in seen_items:
                continue
            seen_items.add(item_id)
            metadata = json.loads(row["metadata_json"] or "{}")
            signals = [f"matched {len(matched)}/{len(query_set)} query terms"]
            if phrase:
                signals.append("exact phrase")
            if lexical:
                signals.append("full-text rank")
            ranked.append(
                {
                    "item_id": item_id,
                    "chunk_id": row["chunk_id"],
                    "project_id": row["project_id"],
                    "title": row["title"],
                    "content": row["content"],
                    "score": score,
                    "score_components": {
                        "full_text": round(lexical, 6),
                        "term_coverage": round(coverage, 6),
                        "exact_phrase": phrase,
                    },
                    "matched_terms": matched[:20],
                    "explanation": signals,
                    "citation": {
                        "source_type": row["source_type"],
                        "external_id": row["external_id"],
                        "source_record_id": row["source_record_id"],
                        "source_locator": metadata.get("source_locator"),
                    },
                    "updated_at": row["updated_at"],
                }
            )
        ranked.sort(key=lambda result: (result["score"], result["updated_at"]), reverse=True)
        return {
            "query": clean_query,
            "results": ranked[: max(1, min(int(limit), 50))],
            "strategy": "hybrid_lexical_v1",
        }

    @staticmethod
    def _item(row: Any) -> dict[str, Any]:
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json", "{}") or "{}")
        return item

    def close(self) -> None:
        with self._lock:
            self._conn.close()
