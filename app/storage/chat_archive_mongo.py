"""Durable, owner-scoped MongoDB chat archive.

Turn writes and destructive operations use MongoDB transactions.  The MongoDB
server must therefore be a replica set (including a single-node replica set) or
MongoDB Atlas; standalone servers do not support this contract.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, TypeVar

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.read_concern import ReadConcern
from pymongo.read_preferences import ReadPreference
from pymongo.write_concern import WriteConcern


_T = TypeVar("_T")


@dataclass
class ChatMessage:
    user_id: str
    conversation_id: str
    role: str
    content: str
    sequence_number: int
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)


class ChatArchiveMongo:
    """MongoDB-backed archive with immutable, globally unique session owners."""

    def __init__(self, db):
        self._db = db
        self._messages = db["messages"]
        self._sessions = db["chat_sessions"]
        self._requests = db["chat_requests"]
        self._deleted_users = db["deleted_users"]
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        # Do not catch these failures: uniqueness cannot be guaranteed if any
        # required index is absent, so startup must fail loudly.
        self._messages.create_index(
            [("message_id", ASCENDING)], unique=True, name="uq_message_id"
        )
        self._sessions.create_index(
            [("session_id", ASCENDING)], unique=True, name="uq_session_owner"
        )
        self._messages.create_index(
            [("conversation_id", ASCENDING), ("sequence_number", ASCENDING)],
            unique=True,
            name="uq_conversation_sequence",
        )
        self._requests.create_index(
            [
                ("user_id", ASCENDING),
                ("conversation_id", ASCENDING),
                ("request_id", ASCENDING),
            ],
            unique=True,
            name="uq_chat_request",
        )
        self._messages.create_index(
            [("user_id", ASCENDING), ("conversation_id", ASCENDING),
             ("sequence_number", ASCENDING)],
            name="ix_owner_conversation_sequence",
        )
        self._messages.create_index(
            [("user_id", ASCENDING), ("created_at", DESCENDING)],
            name="ix_owner_created",
        )
        self._sessions.create_index(
            [("user_id", ASCENDING), ("updated_at", DESCENDING)],
            name="ix_owner_sessions",
        )
        self._deleted_users.create_index(
            [("user_id", ASCENDING)], unique=True, name="uq_deleted_user"
        )

    # ------------------------------------------------------------------
    # Transaction and ownership helpers
    # ------------------------------------------------------------------
    def _transaction(self, callback: Callable[[object], _T]) -> _T:
        with self._db.client.start_session() as mongo_session:
            return mongo_session.with_transaction(
                callback,
                read_concern=ReadConcern("snapshot"),
                write_concern=WriteConcern("majority"),
                read_preference=ReadPreference.PRIMARY,
            )

    @staticmethod
    def _new_session_document(user_id: str, conversation_id: str, now: float) -> dict:
        return {
            "session_id": conversation_id,
            "user_id": user_id,
            "title": "New Chat",
            "created_at": now,
            "updated_at": now,
            "last_message": "",
            "safety_state": {},
            "sequence_counter": 0,
        }

    def _ensure_session_document(
        self, user_id: str, conversation_id: str, *, mongo_session=None
    ) -> dict:
        now = time.time()
        if self._deleted_users.find_one(
            {"user_id": user_id}, projection={"_id": 1}, session=mongo_session
        ) is not None:
            raise PermissionError("user identity has been deleted")
        doc = self._sessions.find_one_and_update(
            {"user_id": user_id, "session_id": conversation_id},
            {"$setOnInsert": self._new_session_document(user_id, conversation_id, now)},
            upsert=True,
            return_document=ReturnDocument.AFTER,
            session=mongo_session,
        )
        if doc is None:
            raise RuntimeError("failed to ensure chat session")
        return doc

    def _initialize_legacy_counter(
        self, user_id: str, conversation_id: str, *, mongo_session
    ) -> None:
        doc = self._sessions.find_one(
            {
                "user_id": user_id,
                "session_id": conversation_id,
                "sequence_counter": {"$exists": False},
            },
            projection={"_id": 1},
            session=mongo_session,
        )
        if doc is None:
            return
        last = self._messages.find_one(
            {"user_id": user_id, "conversation_id": conversation_id},
            projection={"sequence_number": 1},
            sort=[("sequence_number", DESCENDING)],
            session=mongo_session,
        )
        maximum = int((last or {}).get("sequence_number", 0))
        self._sessions.update_one(
            {
                "user_id": user_id,
                "session_id": conversation_id,
                "sequence_counter": {"$exists": False},
            },
            {"$set": {"sequence_counter": maximum}},
            session=mongo_session,
        )

    def _allocate_sequences(
        self, user_id: str, conversation_id: str, amount: int, *, mongo_session
    ) -> tuple[int, int]:
        self._initialize_legacy_counter(
            user_id, conversation_id, mongo_session=mongo_session
        )
        doc = self._sessions.find_one_and_update(
            {"user_id": user_id, "session_id": conversation_id},
            {"$inc": {"sequence_counter": amount}},
            return_document=ReturnDocument.AFTER,
            projection={"sequence_counter": 1},
            session=mongo_session,
        )
        if doc is None:
            raise PermissionError("session is not owned by this user")
        end = int(doc["sequence_counter"])
        return end - amount + 1, end

    @staticmethod
    def _session_view(doc: dict) -> dict:
        return {
            "session_id": doc.get("session_id", ""),
            "user_id": doc.get("user_id", ""),
            "title": doc.get("title", "New Chat"),
            "created_at": doc.get("created_at", 0),
            "updated_at": doc.get("updated_at", 0),
            "last_message": doc.get("last_message", ""),
        }

    def owns_session(self, user_id: str, conversation_id: str) -> bool:
        return self._sessions.find_one(
            {"user_id": user_id, "session_id": conversation_id},
            projection={"_id": 1},
        ) is not None

    def ensure_session(self, user_id: str, conversation_id: str) -> dict:
        try:
            return self._session_view(
                self._ensure_session_document(user_id, conversation_id)
            )
        except DuplicateKeyError as exc:
            # The globally unique session_id already belongs to someone else.
            if not self.owns_session(user_id, conversation_id):
                raise PermissionError("session is owned by another user") from exc
            doc = self._sessions.find_one(
                {"user_id": user_id, "session_id": conversation_id},
                projection={"_id": 0},
            )
            if doc is None:
                raise
            return self._session_view(doc)

    # ------------------------------------------------------------------
    # Durable, idempotent turn writes
    # ------------------------------------------------------------------
    def get_request(
        self, user_id: str, conversation_id: str, request_id: str
    ) -> Optional[dict]:
        return self._requests.find_one(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "request_id": request_id,
            },
            projection={"_id": 0, "claim_id": 0},
        )

    def pending_secondary(
        self, user_id: str, conversation_id: str, limit: int = 50
    ) -> List[dict]:
        cursor = self._requests.find(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "$or": [
                    {"memory_status": {"$ne": "completed"}},
                    {"summary_status": {"$ne": "completed"}},
                ],
            },
            projection={"_id": 0, "claim_id": 0},
        ).sort("created_at", ASCENDING).limit(limit)
        return [self._request_result(row, duplicate=True) for row in cursor]

    def mark_secondary(
        self, user_id: str, conversation_id: str, request_id: str,
        component: str, *, error: Optional[str] = None,
    ) -> None:
        if component not in {"memory", "summary"}:
            raise ValueError("component must be 'memory' or 'summary'")

        def update(mongo_session) -> None:
            changes = {
                f"{component}_status": "failed" if error else "completed",
                "secondary_error": error or None,
                "secondary_updated_at": time.time(),
            }
            operation = {"$set": changes}
            if error:
                operation["$inc"] = {"secondary_attempts": 1}
            result = self._requests.update_one(
                {"user_id": user_id, "conversation_id": conversation_id,
                 "request_id": request_id},
                operation, session=mongo_session,
            )
            if result.matched_count != 1:
                raise LookupError("secondary work item not found")

        self._transaction(update)

    def secondary_pending_count(self) -> int:
        return self._requests.count_documents({
            "$or": [
                {"memory_status": {"$ne": "completed"}},
                {"summary_status": {"$ne": "completed"}},
            ]
        })

    @staticmethod
    def _request_result(request: dict, *, duplicate: bool) -> dict:
        reply = request.get("reply", request.get("assistant_content", ""))
        return {
            "user_id": request.get("user_id", ""),
            "conversation_id": request.get("conversation_id", ""),
            "request_id": request.get("request_id", ""),
            "reply": reply,
            "assistant_content": reply,
            "route": request.get("route", "support"),
            "user_message_id": request.get("user_message_id", ""),
            "assistant_message_id": request.get("assistant_message_id", ""),
            "user_content": request.get("user_content", ""),
            "state": request.get("state"),
            "memory_status": request.get("memory_status", "pending"),
            "summary_status": request.get("summary_status", "pending"),
            "secondary_attempts": int(request.get("secondary_attempts", 0)),
            "secondary_error": request.get("secondary_error"),
            "duplicate": duplicate,
        }

    def record_turn(
        self,
        user_id: str,
        conversation_id: str,
        user_content: str,
        assistant_content: str,
        request_id: str,
        state: Optional[dict] = None,
        route: str = "support",
    ) -> dict:
        if not request_id:
            raise ValueError("request_id is required")

        def write_turn(mongo_session) -> dict:
            self._ensure_session_document(
                user_id, conversation_id, mongo_session=mongo_session
            )
            existing = self._requests.find_one(
                {
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                },
                session=mongo_session,
            )
            if existing is not None:
                if existing.get("user_content") != user_content:
                    raise ValueError(
                        "idempotency key was already used for a different message"
                    )
                if existing.get("status") != "completed":
                    raise RuntimeError("request is already being processed")
                return self._request_result(existing, duplicate=True)

            now = time.time()
            claim_id = str(uuid.uuid4())
            self._requests.insert_one(
                {
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "user_content": user_content,
                    "claim_id": claim_id,
                    "status": "pending",
                    "memory_status": "pending",
                    "summary_status": "pending",
                    "secondary_attempts": 0,
                    "secondary_error": None,
                    "state": dict(state) if state is not None else None,
                    "created_at": now,
                    "updated_at": now,
                },
                session=mongo_session,
            )

            first_sequence, second_sequence = self._allocate_sequences(
                user_id, conversation_id, 2, mongo_session=mongo_session
            )
            user_message_id = str(uuid.uuid4())
            assistant_message_id = str(uuid.uuid4())
            self._messages.insert_many(
                [
                    {
                        "message_id": user_message_id,
                        "user_id": user_id,
                        "conversation_id": conversation_id,
                        "role": "user",
                        "content": user_content,
                        "created_at": now,
                        "sequence_number": first_sequence,
                    },
                    {
                        "message_id": assistant_message_id,
                        "user_id": user_id,
                        "conversation_id": conversation_id,
                        "role": "assistant",
                        "content": assistant_content,
                        "created_at": now,
                        "sequence_number": second_sequence,
                    },
                ],
                ordered=True,
                session=mongo_session,
            )

            metadata = {
                "updated_at": now,
                "last_message": assistant_content[:60],
            }
            if second_sequence == 2:
                metadata["title"] = user_content[:40] or "New Chat"
            if state is not None:
                metadata["safety_state"] = dict(state)
            session_update = self._sessions.update_one(
                {"user_id": user_id, "session_id": conversation_id},
                {"$set": metadata},
                session=mongo_session,
            )
            if session_update.matched_count != 1:
                raise PermissionError("session is not owned by this user")

            completed = {
                "status": "completed",
                "reply": assistant_content,
                "assistant_content": assistant_content,
                "route": route,
                "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id,
                "updated_at": now,
                "completed_at": now,
            }
            request_update = self._requests.update_one(
                {
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "claim_id": claim_id,
                    "status": "pending",
                },
                {"$set": completed, "$unset": {"claim_id": ""}},
                session=mongo_session,
            )
            if request_update.matched_count != 1:
                raise RuntimeError("lost idempotency claim")
            completed.update(
                {
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                }
            )
            return self._request_result(completed, duplicate=False)

        for attempt in range(2):
            try:
                return self._transaction(write_turn)
            except DuplicateKeyError as exc:
                # A concurrent transaction may have committed this request first.
                existing = self.get_request(user_id, conversation_id, request_id)
                if existing is not None and existing.get("status") == "completed":
                    if existing.get("user_content") != user_content:
                        raise ValueError(
                            "idempotency key was already used for a different message"
                        ) from exc
                    return self._request_result(existing, duplicate=True)
                if not self.owns_session(user_id, conversation_id):
                    raise PermissionError("session is owned by another user") from exc
                # A same-owner transaction may have created the session first.
                if attempt == 0:
                    continue
                raise
        raise RuntimeError("turn transaction did not complete")

    # ------------------------------------------------------------------
    # Backend-compatible writes and state
    # ------------------------------------------------------------------
    def record(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
        message_id: Optional[str] = None,
    ) -> ChatMessage:
        chosen_id = message_id or str(uuid.uuid4())

        def write_message(mongo_session) -> ChatMessage:
            self._ensure_session_document(
                user_id, conversation_id, mongo_session=mongo_session
            )
            existing = self._messages.find_one(
                {
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "message_id": chosen_id,
                },
                session=mongo_session,
            )
            if existing is not None:
                return self._to_msg(existing)

            sequence, _ = self._allocate_sequences(
                user_id, conversation_id, 1, mongo_session=mongo_session
            )
            msg = ChatMessage(
                user_id=user_id,
                conversation_id=conversation_id,
                role=role,
                content=content,
                sequence_number=sequence,
                message_id=chosen_id,
            )
            self._messages.insert_one(
                {
                    "message_id": msg.message_id,
                    "user_id": msg.user_id,
                    "conversation_id": msg.conversation_id,
                    "role": msg.role,
                    "content": msg.content,
                    "created_at": msg.created_at,
                    "sequence_number": msg.sequence_number,
                },
                session=mongo_session,
            )
            metadata = {
                "updated_at": msg.created_at,
                "last_message": content[:60],
            }
            if sequence == 1 and role == "user":
                metadata["title"] = content[:40] or "New Chat"
            update = self._sessions.update_one(
                {"user_id": user_id, "session_id": conversation_id},
                {"$set": metadata},
                session=mongo_session,
            )
            if update.matched_count != 1:
                raise PermissionError("session is not owned by this user")
            return msg

        for attempt in range(2):
            try:
                return self._transaction(write_message)
            except DuplicateKeyError as exc:
                existing = self._messages.find_one(
                    {
                        "user_id": user_id,
                        "conversation_id": conversation_id,
                        "message_id": chosen_id,
                    }
                )
                if existing is not None:
                    return self._to_msg(existing)
                if not self.owns_session(user_id, conversation_id):
                    raise PermissionError("session is owned by another user") from exc
                if attempt == 0:
                    continue
                raise
        raise RuntimeError("message transaction did not complete")

    def healthcheck(self) -> None:
        self._db.client.admin.command("ping")

    def flush(self, timeout=None) -> None:
        """Writes are synchronous; retained for backend compatibility."""

    def close(self) -> None:
        """The shared MongoClient is owned by mongo_client, not this archive."""

    def save_safety_state(
        self, user_id: str, conversation_id: str, state: dict, *,
        completed_request_id: Optional[str] = None,
        memory_completed: bool = False,
    ) -> None:
        def save(mongo_session) -> None:
            self._ensure_session_document(
                user_id, conversation_id, mongo_session=mongo_session
            )
            result = self._sessions.update_one(
                {"user_id": user_id, "session_id": conversation_id},
                {"$set": {"safety_state": dict(state or {}),
                           "updated_at": time.time()}},
                session=mongo_session,
            )
            if result.matched_count != 1:
                raise PermissionError("session is not owned by this user")
            if completed_request_id:
                changes = {
                    "summary_status": "completed",
                    "secondary_error": None,
                    "secondary_updated_at": time.time(),
                }
                if memory_completed:
                    changes["memory_status"] = "completed"
                request_update = self._requests.update_one(
                    {"user_id": user_id, "conversation_id": conversation_id,
                     "request_id": completed_request_id},
                    {"$set": changes}, session=mongo_session,
                )
                if request_update.matched_count != 1:
                    raise LookupError("secondary work item not found")

        self._transaction(save)

    def load_safety_state(self, user_id: str, conversation_id: str) -> dict:
        row = self._sessions.find_one(
            {"user_id": user_id, "session_id": conversation_id},
            projection={"_id": 0, "safety_state": 1},
        )
        return dict((row or {}).get("safety_state") or {})

    # ------------------------------------------------------------------
    # Reads (always owner-scoped)
    # ------------------------------------------------------------------
    def fetch_recent(
        self, user_id: str, conversation_id: str, limit: int = 20
    ) -> List[ChatMessage]:
        cursor = (
            self._messages.find(
                {"user_id": user_id, "conversation_id": conversation_id}
            )
            .sort("sequence_number", DESCENDING)
            .limit(limit)
        )
        rows = list(cursor)
        rows.reverse()
        return [self._to_msg(row) for row in rows]

    def fetch_page(
        self,
        user_id: str,
        conversation_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> List[ChatMessage]:
        cursor = (
            self._messages.find(
                {"user_id": user_id, "conversation_id": conversation_id}
            )
            .sort("sequence_number", ASCENDING)
            .skip(offset)
            .limit(limit)
        )
        return [self._to_msg(row) for row in cursor]

    def count(self, user_id: str, conversation_id: Optional[str] = None) -> int:
        query = {"user_id": user_id}
        if conversation_id is not None:
            query["conversation_id"] = conversation_id
        return self._messages.count_documents(query)

    def export_user(self, user_id: str) -> List[ChatMessage]:
        cursor = self._messages.find({"user_id": user_id}).sort(
            [("conversation_id", ASCENDING), ("sequence_number", ASCENDING)]
        )
        return [self._to_msg(row) for row in cursor]

    # ------------------------------------------------------------------
    # Cross-session history
    # ------------------------------------------------------------------
    def recent_sessions(
        self,
        user_id: str,
        *,
        exclude: Optional[str] = None,
        limit: int = 3,
        per_session: int = 40,
    ) -> List[dict]:
        query = {"user_id": user_id}
        if exclude is not None:
            query["session_id"] = {"$ne": exclude}
        cursor = self._sessions.find(
            query,
            projection={"_id": 0, "session_id": 1, "updated_at": 1},
        ).sort("updated_at", DESCENDING)

        output: List[dict] = []
        for session_doc in cursor:
            session_id = session_doc.get("session_id")
            if not session_id:
                continue
            messages = list(
                self._messages.find(
                    {"user_id": user_id, "conversation_id": session_id},
                    projection={
                        "_id": 0,
                        "role": 1,
                        "content": 1,
                        "sequence_number": 1,
                    },
                )
                .sort("sequence_number", DESCENDING)
                .limit(per_session)
            )
            if not messages:
                continue
            messages.reverse()
            output.append(
                {
                    "session_id": session_id,
                    "updated_at": session_doc.get("updated_at", 0),
                    "messages": [
                        {
                            "role": message.get("role", ""),
                            "content": message.get("content", ""),
                        }
                        for message in messages
                    ],
                }
            )
            if len(output) >= limit:
                break
        return output

    def session_digests(
        self,
        user_id: str,
        *,
        exclude: Optional[str] = None,
        limit: int = 30,
        skip: int = 0,
    ) -> List[dict]:
        query = {"user_id": user_id}
        if exclude is not None:
            query["session_id"] = {"$ne": exclude}
        cursor = (
            self._sessions.find(
                query,
                projection={"_id": 0, "session_id": 1, "updated_at": 1},
            )
            .sort("updated_at", DESCENDING)
            .skip(skip)
            .limit(limit)
        )

        output: List[dict] = []
        for session_doc in cursor:
            session_id = session_doc.get("session_id")
            if not session_id:
                continue
            message_query = {
                "user_id": user_id,
                "conversation_id": session_id,
                "role": "user",
            }
            projection = {"_id": 0, "content": 1, "sequence_number": 1}
            first = list(self._messages.find(
                message_query, projection=projection
            ).sort("sequence_number", ASCENDING).limit(40))
            last = list(self._messages.find(
                message_query, projection=projection
            ).sort("sequence_number", DESCENDING).limit(40))
            by_sequence = {
                int(message.get("sequence_number", 0)): message
                for message in first + last
            }
            ordered = [by_sequence[key] for key in sorted(by_sequence)]
            text = " ".join(message.get("content", "") for message in ordered)
            if len(text) > 4000:
                text = text[:1980] + " … [later in session] … " + text[-1980:]
            if not text:
                continue
            output.append(
                {
                    "session_id": session_id,
                    "updated_at": session_doc.get("updated_at", 0),
                    "text": text[:4000],
                }
            )
        return output

    # ------------------------------------------------------------------
    # Session listing and creation
    # ------------------------------------------------------------------
    def list_sessions(self, user_id: str) -> List[dict]:
        cursor = self._sessions.find(
            {"user_id": user_id}, projection={"_id": 0}
        ).sort("updated_at", DESCENDING)
        sessions: List[dict] = []
        for doc in cursor:
            view = self._session_view(doc)
            view["message_count"] = self._messages.count_documents(
                {
                    "user_id": user_id,
                    "conversation_id": doc.get("session_id", ""),
                }
            )
            sessions.append(view)
        return sessions

    def create_session(
        self, user_id: str, session_id: Optional[str] = None
    ) -> dict:
        return self.ensure_session(user_id, session_id or str(uuid.uuid4()))

    # ------------------------------------------------------------------
    # Transactional deletion, including idempotency records
    # ------------------------------------------------------------------
    def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        def delete(mongo_session) -> bool:
            owner = self._sessions.find_one(
                {"user_id": user_id, "session_id": conversation_id},
                projection={"_id": 1}, session=mongo_session,
            )
            if owner is None:
                return False
            self._messages.delete_many(
                {"user_id": user_id, "conversation_id": conversation_id},
                session=mongo_session,
            )
            self._requests.delete_many(
                {"user_id": user_id, "conversation_id": conversation_id},
                session=mongo_session,
            )
            result = self._sessions.delete_one(
                {"user_id": user_id, "session_id": conversation_id},
                session=mongo_session,
            )
            return result.deleted_count == 1

        return self._transaction(delete)

    def claim_retention_run(self, min_interval_seconds: float,
                            now: Optional[float] = None) -> bool:
        """Atomically claim the next retention sweep across all workers."""
        now = time.time() if now is None else now
        result = self._db["maintenance_runs"].update_one(
            {"name": "retention",
             "last_run_at": {"$lt": now - min_interval_seconds}},
            {"$set": {"last_run_at": now}},
        )
        if result.modified_count:
            return True
        # First ever run: insert wins only once thanks to the unique _id.
        try:
            self._db["maintenance_runs"].insert_one(
                {"_id": "retention", "name": "retention", "last_run_at": now})
            return True
        except DuplicateKeyError:
            return False

    def purge_expired(self, *, policy, now: float) -> Dict[str, int]:
        """Expire records per data class. Returns counts of removed records."""
        counts: Dict[str, int] = {}
        conversation_cutoff = policy.cutoff(policy.conversation_days, now)
        summary_cutoff = policy.cutoff(policy.summary_days, now)
        state_cutoff = policy.cutoff(policy.safety_state_days, now)

        if conversation_cutoff is not None:
            counts["requests"] = self._requests.delete_many(
                {"created_at": {"$lt": conversation_cutoff}}).deleted_count
            counts["messages"] = self._messages.delete_many(
                {"created_at": {"$lt": conversation_cutoff}}).deleted_count
            stale = [
                doc["session_id"] for doc in self._sessions.find(
                    {"updated_at": {"$lt": conversation_cutoff}},
                    projection={"_id": 0, "session_id": 1})
                if self._messages.count_documents(
                    {"conversation_id": doc["session_id"]}, limit=1) == 0
            ]
            if stale:
                counts["sessions"] = self._sessions.delete_many(
                    {"session_id": {"$in": stale}}).deleted_count
        if summary_cutoff is not None:
            counts["summaries"] = self._sessions.update_many(
                {"updated_at": {"$lt": summary_cutoff}},
                {"$unset": {"summary": "", "metadata": ""}}).modified_count
        if state_cutoff is not None:
            counts["safety_states"] = self._sessions.update_many(
                {"updated_at": {"$lt": state_cutoff}},
                {"$set": {"safety_state": {}}}).modified_count
        return {k: int(v) for k, v in counts.items() if v}

    # ------------------------------------------------------------------
    # Account deletion job state (mirrors the SQLite contract).
    # ------------------------------------------------------------------
    def start_deletion_job(self, user_id: str, steps, now=None) -> Dict[str, str]:
        now = time.time() if now is None else now
        existing = self._db["deletion_jobs"].find_one({"user_id": user_id})
        state = dict((existing or {}).get("steps") or {})
        for step in steps:
            state.setdefault(step, "pending")
        self._db["deletion_jobs"].update_one(
            {"user_id": user_id},
            {"$set": {"steps": state},
             "$setOnInsert": {"requested_at": now, "completed_at": 0}},
            upsert=True,
        )
        return state

    def record_deletion_step(self, user_id: str, step: str, status: str,
                             error: Optional[str] = None) -> None:
        value = status if not error else f"{status}:{error}"
        self._db["deletion_jobs"].update_one(
            {"user_id": user_id}, {"$set": {f"steps.{step}": value}}, upsert=True)

    def finish_deletion_job(self, user_id: str, now=None) -> None:
        now = time.time() if now is None else now
        self._db["deletion_jobs"].update_one(
            {"user_id": user_id}, {"$set": {"completed_at": now}}, upsert=True)

    def deletion_job(self, user_id: str) -> Optional[dict]:
        doc = self._db["deletion_jobs"].find_one(
            {"user_id": user_id}, projection={"_id": 0})
        if doc is None:
            return None
        return {
            "requested_at": float(doc.get("requested_at") or 0.0),
            "steps": dict(doc.get("steps") or {}),
            "completed_at": float(doc.get("completed_at") or 0.0),
        }

    def is_user_deleted(self, user_id: str) -> bool:
        return self._deleted_users.find_one(
            {"user_id": user_id}, projection={"_id": 1}
        ) is not None

    def delete_user(self, user_id: str) -> None:
        def delete(mongo_session) -> None:
            self._messages.delete_many({"user_id": user_id}, session=mongo_session)
            self._requests.delete_many({"user_id": user_id}, session=mongo_session)
            self._sessions.delete_many({"user_id": user_id}, session=mongo_session)
            self._db["memory"].delete_many(
                {"user_id": user_id}, session=mongo_session)
            self._db["memory_owner_locks"].delete_many(
                {"user_id": user_id}, session=mongo_session)
            self._db["feedback"].delete_many(
                {"user_id": user_id}, session=mongo_session)
            self._deleted_users.update_one(
                {"user_id": user_id},
                {"$set": {"deleted_at": time.time()}},
                upsert=True, session=mongo_session,
            )

        self._transaction(delete)

    @staticmethod
    def _to_msg(doc: dict) -> ChatMessage:
        return ChatMessage(
            message_id=doc.get("message_id", ""),
            user_id=doc.get("user_id", ""),
            conversation_id=doc.get("conversation_id", ""),
            role=doc.get("role", ""),
            content=doc.get("content", ""),
            created_at=doc.get("created_at", 0.0),
            sequence_number=doc.get("sequence_number", 0),
        )
