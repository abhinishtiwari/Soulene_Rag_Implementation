"""Durable, multi-process-safe SQLite backend for long-term user memory.

Extraction, deduplication, retrieval, and contradiction behavior intentionally
match :class:`app.memory.long_term_memory.LongTermMemory`; only storage differs.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

from app.memory.long_term_memory import (
    _ACHIEVEMENT,
    _CONTEXT,
    _COPING,
    _GOAL,
    _MAX_MEMORIES,
    _NAME,
    _NEGATION,
    _PREF,
    _RELATION,
    _SLEEP,
    _STYLE,
    _SYNONYMS,
    _TRIGGER,
    _tokens,
)
from app.types import UserMemory


@dataclass
class _StoredMemory:
    memory_id: str
    memory: UserMemory


class LongTermMemorySQLite:
    """SQLite-backed drop-in memory implementation with no local cache."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        *,
        storage_dir: Optional[Path] = None,
        busy_timeout_ms: int = 5_000,
    ) -> None:
        if db_path is not None and storage_dir is not None:
            raise ValueError("pass either db_path or storage_dir, not both")
        if busy_timeout_ms < 0:
            raise ValueError("busy_timeout_ms must be non-negative")

        if storage_dir is not None:
            path = Path(storage_dir) / "long_term_memory.sqlite3"
        elif db_path is not None:
            path = Path(db_path)
        else:
            path = Path("data") / "long_term_memory.sqlite3"

        self._db_path = path
        self._busy_timeout_ms = int(busy_timeout_ms)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self._db_path),
            timeout=self._busy_timeout_ms / 1_000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            if str(mode).lower() != "wal":
                raise sqlite3.OperationalError("SQLite WAL mode could not be enabled")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS long_term_memories (
                    user_id TEXT NOT NULL,
                    memory_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    weight REAL NOT NULL,
                    ordinal INTEGER NOT NULL,
                    sources_json TEXT NOT NULL DEFAULT '[]',
                    extraction_version TEXT NOT NULL DEFAULT 'legacy',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    PRIMARY KEY (user_id, memory_id)
                )
                """
            )
            columns = {
                row[1] for row in connection.execute(
                    "PRAGMA table_info(long_term_memories)"
                ).fetchall()
            }
            for name, definition in (
                ("sources_json", "TEXT NOT NULL DEFAULT '[]'"),
                ("extraction_version", "TEXT NOT NULL DEFAULT 'legacy'"),
                ("confidence", "REAL NOT NULL DEFAULT 1.0"),
            ):
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE long_term_memories ADD COLUMN {name} {definition}"
                    )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_long_term_memories_owner_order
                ON long_term_memories (user_id, ordinal)
                """
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @contextmanager
    def _transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def observe(
        self, user_id: str, message: str, *,
        source_session_id: Optional[str] = None,
        source_message_id: Optional[str] = None,
        extraction_version: str = "rules-v1",
        confidence: float = 1.0,
    ) -> None:
        """Extract facts with auditable committed-message provenance."""
        candidates: List[UserMemory] = []
        now = time.time()

        match = _NAME.search(message)
        if match:
            raw = match.group(1).strip().split()
            filler = {"by", "the", "way", "and", "but", "so", "just", "actually", "here", "now"}
            name_parts = []
            for word in raw[:2]:
                if word.lower() in filler:
                    break
                name_parts.append(word)
            name = " ".join(name_parts).strip(" '-")
            if name and name.lower() not in filler:
                candidates.append(
                    UserMemory(
                        text=f"User's name: {name}",
                        kind="name",
                        created_at=now,
                        updated_at=now,
                        weight=2.0,
                    )
                )

        for pattern, kind, weight in (
            (_TRIGGER, "trigger", 2.0),
            (_COPING, "coping_strategy", 2.0),
            (_GOAL, "goal", 1.6),
            (_SLEEP, "sleep", 1.4),
            (_STYLE, "communication_style", 1.8),
            (_ACHIEVEMENT, "achievement", 1.2),
            (_PREF, "preference", 1.0),
            (_CONTEXT, "context", 1.0),
            (_RELATION, "relationship", 1.0),
        ):
            for match in pattern.finditer(message):
                text = re.sub(r"\s+", " ", match.group(1)).strip()
                if 4 <= len(text) <= 90:
                    candidates.append(
                        UserMemory(
                            text=text,
                            kind=kind,
                            created_at=now,
                            updated_at=now,
                            weight=weight,
                        )
                    )

        if not candidates:
            return
        source = None
        if source_session_id and source_message_id:
            source = {"session_id": source_session_id, "message_id": source_message_id}
        for candidate in candidates:
            candidate.sources = [source] if source else []
            candidate.extraction_version = extraction_version
            candidate.confidence = max(0.0, min(1.0, float(confidence)))

        # The write lock is acquired before loading, so every observer merges
        # against the latest committed owner state rather than a stale snapshot.
        with self._transaction(immediate=True) as connection:
            has_tombstones = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'deleted_users'"
            ).fetchone()
            if (has_tombstones is not None and connection.execute(
                    "SELECT 1 FROM deleted_users WHERE user_id = ?", (user_id,)
            ).fetchone() is not None):
                raise PermissionError("user identity has been deleted")
            memories = self._load(connection, user_id)
            for candidate in candidates:
                self._upsert(memories, candidate)
            memories.sort(
                key=lambda record: (record.memory.weight, record.memory.updated_at),
                reverse=True,
            )
            del memories[_MAX_MEMORIES:]
            self._replace_owner(connection, user_id, memories)

    def retrieve(
        self,
        user_id: str,
        message: str,
        k_min: int = 3,
        k_max: int = 8,
    ) -> List[UserMemory]:
        with self._transaction() as connection:
            memories = [record.memory for record in self._load(connection, user_id)]
        if not memories:
            return []

        query = _tokens(message)
        if not query:
            always = [
                memory
                for memory in memories
                if memory.kind in ("name", "communication_style")
            ]
            return always[:k_min] if always else []

        expanded_query = set(query)
        for token in query:
            if token in _SYNONYMS:
                expanded_query.update(_SYNONYMS[token])

        scored = []
        for item in memories:
            item_tokens = _tokens(item.text)
            direct_overlap = len(query & item_tokens)
            synonym_overlap = len((expanded_query - query) & item_tokens)
            overlap = direct_overlap + (synonym_overlap * 0.6)

            if item.kind in ("name", "communication_style"):
                score = overlap + 1.0 + 0.1 * item.weight
            elif overlap > 0:
                recency_bonus = min(0.3, 0.1 * (item.updated_at / (time.time() or 1)))
                score = overlap + 0.1 * item.weight + recency_bonus
            else:
                continue
            scored.append((score, item))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        selected = [item for score, item in scored if score > 0]
        if not selected:
            return []
        return selected[:max(k_min, min(k_max, len(selected)))]

    def contradiction_topics(self, user_id: str, message: str) -> List[str]:
        """Return stored facts that the current message may be correcting."""
        if not _NEGATION.search(message):
            return []
        with self._transaction() as connection:
            memories = [record.memory for record in self._load(connection, user_id)]
        query = _tokens(message)
        hits = []
        for item in memories:
            if len(query & _tokens(item.text)) >= 1 and item.kind != "name":
                hits.append(item.text)
        return hits[:3]

    def forget_user(self, user_id: str) -> None:
        with self._transaction(immediate=True) as connection:
            connection.execute(
                "DELETE FROM long_term_memories WHERE user_id = ?",
                (user_id,),
            )

    def forget_session(self, user_id: str, session_id: str) -> None:
        """Drop one session's evidence; retain reinforced and legacy memories."""
        with self._transaction(immediate=True) as connection:
            memories = self._load(connection, user_id)
            retained = []
            for record in memories:
                if not record.memory.sources:
                    retained.append(record)
                    continue
                record.memory.sources = [
                    source for source in record.memory.sources
                    if source.get("session_id") != session_id
                ]
                if record.memory.sources:
                    retained.append(record)
            self._replace_owner(connection, user_id, retained)

    def _load(
        self,
        connection: sqlite3.Connection,
        user_id: str,
    ) -> List[_StoredMemory]:
        rows = connection.execute(
            """
            SELECT memory_id, text, kind, created_at, updated_at, weight,
                   sources_json, extraction_version, confidence
            FROM long_term_memories
            WHERE user_id = ?
            ORDER BY ordinal ASC
            LIMIT ?
            """,
            (user_id, _MAX_MEMORIES),
        ).fetchall()
        return [
            _StoredMemory(
                memory_id=row["memory_id"],
                memory=UserMemory(
                    text=row["text"],
                    kind=row["kind"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    weight=row["weight"],
                    sources=json.loads(row["sources_json"] or "[]"),
                    extraction_version=row["extraction_version"],
                    confidence=float(row["confidence"]),
                ),
            )
            for row in rows
        ]

    @staticmethod
    def _upsert(memories: List[_StoredMemory], candidate: UserMemory) -> None:
        candidate_tokens = _tokens(candidate.text)
        for record in memories:
            existing = record.memory
            if (
                existing.kind == candidate.kind
                and len(candidate_tokens & _tokens(existing.text))
                >= max(1, len(candidate_tokens) // 2)
            ):
                existing.text = candidate.text
                existing.updated_at = candidate.updated_at
                existing.weight = min(3.0, existing.weight + 0.2)
                for source in candidate.sources:
                    if source not in existing.sources:
                        existing.sources.append(source)
                existing.extraction_version = candidate.extraction_version
                existing.confidence = max(existing.confidence, candidate.confidence)
                return
        memories.append(_StoredMemory(uuid.uuid4().hex, candidate))

    @staticmethod
    def _replace_owner(
        connection: sqlite3.Connection,
        user_id: str,
        memories: List[_StoredMemory],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO long_term_memories (
                user_id, memory_id, text, kind, created_at, updated_at, weight,
                ordinal, sources_json, extraction_version, confidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, memory_id) DO UPDATE SET
                text = excluded.text,
                kind = excluded.kind,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                weight = excluded.weight,
                ordinal = excluded.ordinal,
                sources_json = excluded.sources_json,
                extraction_version = excluded.extraction_version,
                confidence = excluded.confidence
            """,
            [
                (
                    user_id,
                    record.memory_id,
                    record.memory.text,
                    record.memory.kind,
                    record.memory.created_at,
                    record.memory.updated_at,
                    record.memory.weight,
                    ordinal,
                    json.dumps(record.memory.sources, separators=(",", ":")),
                    record.memory.extraction_version,
                    record.memory.confidence,
                )
                for ordinal, record in enumerate(memories)
            ],
        )

        retained_ids = [record.memory_id for record in memories]
        if retained_ids:
            placeholders = ", ".join("?" for _ in retained_ids)
            connection.execute(
                f"""
                DELETE FROM long_term_memories
                WHERE user_id = ? AND memory_id NOT IN ({placeholders})
                """,
                (user_id, *retained_ids),
            )
        else:
            connection.execute(
                "DELETE FROM long_term_memories WHERE user_id = ?",
                (user_id,),
            )
