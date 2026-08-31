"""MongoDB-backed long-term memory with canonical extraction semantics.

Writes use multi-document transactions and therefore require MongoDB to run as
a replica set (including a single-node replica set) or through a sharded cluster.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from typing import List, Optional

from pymongo.read_concern import ReadConcern
from pymongo.read_preferences import ReadPreference
from pymongo.write_concern import WriteConcern

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


class LongTermMemoryMongo:
    """MongoDB-backed drop-in replacement for ``LongTermMemory``."""

    COLLECTION = "memory"

    def __init__(self, db) -> None:
        self._db = db
        self._col = db[self.COLLECTION]
        self._owner_locks = db["memory_owner_locks"]
        self._deleted_users = db["deleted_users"]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        self._col.create_index(
            [("user_id", 1), ("memory_id", 1)],
            unique=True,
            name="uniq_memory_owner_id",
        )
        self._col.create_index(
            [("user_id", 1), ("ordinal", 1)],
            name="idx_memory_owner_order",
        )
        self._owner_locks.create_index(
            [("user_id", 1)], unique=True, name="uniq_memory_owner_lock"
        )

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
            filler = {
                "by", "the", "way", "and", "but", "so", "just",
                "actually", "here", "now",
            }
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

        def update_owner(session) -> None:
            if self._deleted_users.find_one(
                {"user_id": user_id}, projection={"_id": 1}, session=session
            ) is not None:
                raise PermissionError("user identity has been deleted")
            # All workers contend on one owner document. Mongo transaction write
            # conflicts are retried by with_transaction, preventing stale
            # read/replace cycles from dropping another worker's memories.
            self._owner_locks.update_one(
                {"user_id": user_id},
                {"$inc": {"version": 1}},
                upsert=True, session=session,
            )
            memories = self._load(user_id, session=session)
            for candidate in candidates:
                self._upsert(memories, candidate)
            memories.sort(
                key=lambda record: (
                    record.memory.weight,
                    record.memory.updated_at,
                ),
                reverse=True,
            )
            del memories[_MAX_MEMORIES:]
            self._replace_owner(user_id, memories, session=session)

        with self._db.client.start_session() as session:
            session.with_transaction(
                update_owner,
                read_concern=ReadConcern("snapshot"),
                write_concern=WriteConcern("majority"),
                read_preference=ReadPreference.PRIMARY,
            )

    def retrieve(
        self,
        user_id: str,
        message: str,
        k_min: int = 3,
        k_max: int = 8,
    ) -> List[UserMemory]:
        memories = [record.memory for record in self._load(user_id)]
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
                recency_bonus = min(
                    0.3,
                    0.1 * (item.updated_at / (time.time() or 1)),
                )
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
        memories = [record.memory for record in self._load(user_id)]
        query = _tokens(message)
        hits = []
        for item in memories:
            if len(query & _tokens(item.text)) >= 1 and item.kind != "name":
                hits.append(item.text)
        return hits[:3]

    def forget_user(self, user_id: str) -> None:
        self._col.with_options(write_concern=WriteConcern("majority")).delete_many(
            {"user_id": user_id}
        )

    def forget_session(self, user_id: str, session_id: str) -> None:
        """Drop one session's evidence; retain reinforced and legacy memories."""
        def update_owner(session) -> None:
            self._owner_locks.update_one(
                {"user_id": user_id}, {"$inc": {"version": 1}},
                upsert=True, session=session,
            )
            memories = self._load(user_id, session=session)
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
            self._replace_owner(user_id, retained, session=session)

        with self._db.client.start_session() as session:
            session.with_transaction(
                update_owner, read_concern=ReadConcern("snapshot"),
                write_concern=WriteConcern("majority"),
                read_preference=ReadPreference.PRIMARY,
            )

    def _load(self, user_id: str, *, session=None) -> List[_StoredMemory]:
        cursor = (
            self._col.find({"user_id": user_id}, session=session)
            .sort([("ordinal", 1), ("weight", -1), ("updated_at", -1)])
            .limit(_MAX_MEMORIES)
        )
        memories = []
        for row in cursor:
            memory_id = row.get("memory_id")
            if not memory_id:
                legacy_key = row.get("_id")
                if legacy_key is None:
                    legacy_key = "|".join(
                        str(row.get(field, ""))
                        for field in (
                            "kind", "text", "created_at", "updated_at", "weight"
                        )
                    )
                memory_id = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"long-term-memory:{user_id}:{legacy_key}",
                ).hex
            memories.append(
                _StoredMemory(
                    memory_id=str(memory_id),
                    memory=UserMemory(
                        text=row.get("text", ""),
                        kind=row.get("kind", "fact"),
                        created_at=row.get("created_at", 0),
                        updated_at=row.get("updated_at", 0),
                        weight=row.get("weight", 1.0),
                        sources=list(row.get("sources") or []),
                        extraction_version=str(row.get("extraction_version") or "legacy"),
                        confidence=float(row.get("confidence", 1.0)),
                    ),
                )
            )
        return memories

    @staticmethod
    def _upsert(
        memories: List[_StoredMemory],
        candidate: UserMemory,
    ) -> None:
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

    def _replace_owner(
        self,
        user_id: str,
        memories: List[_StoredMemory],
        *,
        session,
    ) -> None:
        retained_ids = []
        for ordinal, record in enumerate(memories):
            retained_ids.append(record.memory_id)
            memory = record.memory
            self._col.replace_one(
                {"user_id": user_id, "memory_id": record.memory_id},
                {
                    "user_id": user_id,
                    "memory_id": record.memory_id,
                    "text": memory.text,
                    "kind": memory.kind,
                    "created_at": memory.created_at,
                    "updated_at": memory.updated_at,
                    "weight": memory.weight,
                    "ordinal": ordinal,
                    "sources": list(memory.sources),
                    "extraction_version": memory.extraction_version,
                    "confidence": memory.confidence,
                },
                upsert=True,
                session=session,
            )

        if retained_ids:
            self._col.delete_many(
                {
                    "user_id": user_id,
                    "memory_id": {"$nin": retained_ids},
                },
                session=session,
            )
        else:
            self._col.delete_many({"user_id": user_id}, session=session)
