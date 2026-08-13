"""Chat archive backed by MongoDB Atlas — drop-in replacement for ChatArchiveJSON.

Same public API. Returns same ChatMessage dataclass objects.
Every query filters by user_id for complete isolation.

JSON Compatibility: internally converts MongoDB documents to the same
format that the JSON archive uses, so all downstream code works unchanged.
"""

from __future__ import annotations

import time
import uuid
import threading
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ChatMessage:
    user_id: str
    conversation_id: str
    role: str
    content: str
    sequence_number: int
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)


class ChatArchiveMongo:
    """MongoDB-backed chat archive with session management."""

    def __init__(self, db):
        self._db = db
        self._messages = db["messages"]
        self._sessions = db["chat_sessions"]
        self._lock = threading.Lock()
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        try:
            self._messages.create_index([("user_id", 1), ("conversation_id", 1), ("sequence_number", 1)])
            self._messages.create_index([("user_id", 1)])
            self._messages.create_index("created_at")
            self._sessions.create_index([("user_id", 1), ("session_id", 1)], unique=True)
            self._sessions.create_index([("user_id", 1), ("updated_at", -1)])
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def record(self, user_id: str, conversation_id: str, role: str, content: str,
               message_id: Optional[str] = None) -> ChatMessage:
        with self._lock:
            last = self._messages.find_one(
                {"user_id": user_id, "conversation_id": conversation_id},
                sort=[("sequence_number", -1)],
                projection={"sequence_number": 1}
            )
            seq = (last["sequence_number"] + 1) if last else 1

        msg = ChatMessage(
            user_id=user_id, conversation_id=conversation_id,
            role=role, content=content, sequence_number=seq,
            message_id=message_id or uuid.uuid4().hex,
        )
        try:
            self._messages.insert_one({
                "message_id": msg.message_id,
                "user_id": user_id,
                "conversation_id": conversation_id,
                "role": role,
                "content": content,
                "created_at": msg.created_at,
                "sequence_number": seq,
            })
            # Update session metadata
            self._sessions.update_one(
                {"user_id": user_id, "session_id": conversation_id},
                {"$set": {"updated_at": msg.created_at,
                          "last_message": content[:60]}},
                upsert=True,
            )
        except Exception:
            pass
        return msg

    def flush(self, timeout=None):
        pass

    def save_safety_state(self, user_id: str, conversation_id: str, state: dict) -> None:
        try:
            self._sessions.update_one(
                {"user_id": user_id, "session_id": conversation_id},
                {"$set": {"safety_state": dict(state or {}), "updated_at": time.time()},
                 "$setOnInsert": {"created_at": time.time(), "title": "New Chat"}},
                upsert=True,
            )
        except Exception:
            pass

    def load_safety_state(self, user_id: str, conversation_id: str) -> dict:
        try:
            row = self._sessions.find_one(
                {"user_id": user_id, "session_id": conversation_id},
                projection={"_id": 0, "safety_state": 1},
            )
            return dict((row or {}).get("safety_state") or {})
        except Exception:
            return {}

    def close(self):
        pass

    # ------------------------------------------------------------------
    # Reads (ALWAYS filtered by user_id)
    # ------------------------------------------------------------------
    def fetch_recent(self, user_id: str, conversation_id: str, limit: int = 20) -> List[ChatMessage]:
        try:
            cursor = (
                self._messages.find({"user_id": user_id, "conversation_id": conversation_id})
                .sort("sequence_number", -1).limit(limit)
            )
            rows = list(cursor)
            rows.reverse()
            return [self._to_msg(r) for r in rows]
        except Exception:
            return []

    def fetch_page(self, user_id: str, conversation_id: str,
                   offset: int = 0, limit: int = 50) -> List[ChatMessage]:
        try:
            cursor = (
                self._messages.find({"user_id": user_id, "conversation_id": conversation_id})
                .sort("sequence_number", 1).skip(offset).limit(limit)
            )
            return [self._to_msg(r) for r in cursor]
        except Exception:
            return []

    def count(self, user_id: str, conversation_id: Optional[str] = None) -> int:
        try:
            q = {"user_id": user_id}
            if conversation_id:
                q["conversation_id"] = conversation_id
            return self._messages.count_documents(q)
        except Exception:
            return 0

    def export_user(self, user_id: str) -> List[ChatMessage]:
        try:
            cursor = (
                self._messages.find({"user_id": user_id})
                .sort([("conversation_id", 1), ("sequence_number", 1)])
            )
            return [self._to_msg(r) for r in cursor]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Cross-session history (every query filtered by user_id)
    # ------------------------------------------------------------------
    def recent_sessions(self, user_id: str, *, exclude: Optional[str] = None,
                        limit: int = 3, per_session: int = 40) -> List[dict]:
        """Most recently updated other sessions, newest first, with messages."""
        out: List[dict] = []
        try:
            cursor = (self._sessions.find({"user_id": user_id},
                                          projection={"_id": 0, "session_id": 1,
                                                      "updated_at": 1})
                      .sort("updated_at", -1).limit(limit + 5))
            for s in cursor:
                sid = s.get("session_id")
                if not sid or sid == exclude:
                    continue
                msgs = list(
                    self._messages.find(
                        {"user_id": user_id, "conversation_id": sid},
                        projection={"_id": 0, "role": 1, "content": 1,
                                    "sequence_number": 1})
                    .sort("sequence_number", -1).limit(per_session)
                )
                if not msgs:
                    continue
                msgs.reverse()
                out.append({
                    "session_id": sid,
                    "updated_at": s.get("updated_at", 0),
                    "messages": [{"role": m.get("role", ""),
                                  "content": m.get("content", "")} for m in msgs],
                })
                if len(out) >= limit:
                    break
        except Exception:
            return []
        return out

    def session_digests(self, user_id: str, *, exclude: Optional[str] = None,
                        limit: int = 30, skip: int = 0) -> List[dict]:
        """Lightweight per-session user-text digests for relevance selection."""
        out: List[dict] = []
        try:
            cursor = (self._sessions.find({"user_id": user_id},
                                          projection={"_id": 0, "session_id": 1,
                                                      "updated_at": 1})
                      .sort("updated_at", -1).skip(skip).limit(limit))
            for s in cursor:
                sid = s.get("session_id")
                if not sid or sid == exclude:
                    continue
                msgs = list(
                    self._messages.find(
                        {"user_id": user_id, "conversation_id": sid,
                         "role": "user"},
                        projection={"_id": 0, "content": 1,
                                    "sequence_number": 1})
                    .sort("sequence_number", 1).limit(80)
                )
                if not msgs:
                    continue
                out.append({
                    "session_id": sid,
                    "updated_at": s.get("updated_at", 0),
                    "text": " ".join(m.get("content", "") for m in msgs)[:4000],
                })
        except Exception:
            return []
        return out

    # ------------------------------------------------------------------
    # Sessions (same API as ChatArchiveJSON)
    # ------------------------------------------------------------------
    def list_sessions(self, user_id: str) -> List[dict]:
        try:
            cursor = (
                self._sessions.find({"user_id": user_id}, projection={"_id": 0})
                .sort("updated_at", -1)
            )
            sessions = []
            for s in cursor:
                sessions.append({
                    "session_id": s.get("session_id", ""),
                    "user_id": user_id,
                    "title": s.get("title", "New Chat"),
                    "created_at": s.get("created_at", 0),
                    "updated_at": s.get("updated_at", 0),
                    "last_message": s.get("last_message", ""),
                })
            return sessions
        except Exception:
            return []

    def create_session(self, user_id: str, session_id: Optional[str] = None) -> dict:
        session_id = session_id or f"{user_id}-{uuid.uuid4().hex[:12]}"
        now = time.time()
        doc = {
            "session_id": session_id,
            "user_id": user_id,
            "title": "New Chat",
            "created_at": now,
            "updated_at": now,
            "last_message": "",
        }
        try:
            self._sessions.insert_one(doc)
        except Exception:
            pass
        return {
            "session_id": session_id, "user_id": user_id,
            "title": "New Chat", "created_at": now,
            "updated_at": now, "last_message": "",
        }

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------
    def delete_conversation(self, user_id: str, conversation_id: str) -> None:
        try:
            self._messages.delete_many({"user_id": user_id, "conversation_id": conversation_id})
            self._sessions.delete_one({"user_id": user_id, "session_id": conversation_id})
        except Exception:
            pass

    def delete_user(self, user_id: str) -> None:
        try:
            self._messages.delete_many({"user_id": user_id})
            self._sessions.delete_many({"user_id": user_id})
        except Exception:
            pass

    def _to_msg(self, doc: dict) -> ChatMessage:
        return ChatMessage(
            message_id=doc.get("message_id", ""),
            user_id=doc.get("user_id", ""),
            conversation_id=doc.get("conversation_id", ""),
            role=doc.get("role", ""),
            content=doc.get("content", ""),
            created_at=doc.get("created_at", 0.0),
            sequence_number=doc.get("sequence_number", 0),
        )
