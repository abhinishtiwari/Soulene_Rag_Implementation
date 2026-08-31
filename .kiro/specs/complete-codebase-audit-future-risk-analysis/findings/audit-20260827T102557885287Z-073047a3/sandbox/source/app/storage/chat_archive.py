"""Production-grade synchronous SQLite conversation archive.

Every operation uses a fresh configured connection. Writes that coordinate
sessions, sequence numbers, messages, or idempotency keys use ``BEGIN
IMMEDIATE`` so correctness holds across threads and processes.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


@dataclass
class ChatMessage:
    user_id: str
    conversation_id: str
    role: str
    content: str
    sequence_number: int
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_messages (
    message_id       TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    conversation_id  TEXT NOT NULL,
    role             TEXT NOT NULL,
    content          TEXT NOT NULL,
    created_at       REAL NOT NULL,
    sequence_number  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id       TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    created_at       REAL NOT NULL,
    updated_at       REAL NOT NULL,
    next_sequence    INTEGER NOT NULL DEFAULT 1 CHECK (next_sequence >= 1),
    safety_state     TEXT NOT NULL DEFAULT '{}',
    metadata_json    TEXT NOT NULL DEFAULT '{}',
    UNIQUE (session_id, user_id)
);
"""
_SCHEMA += """
CREATE TABLE IF NOT EXISTS deleted_users (
    user_id          TEXT PRIMARY KEY,
    deleted_at       REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_requests (
    user_id              TEXT NOT NULL,
    conversation_id      TEXT NOT NULL,
    request_id            TEXT NOT NULL,
    user_message_id       TEXT NOT NULL UNIQUE,
    assistant_message_id  TEXT NOT NULL UNIQUE,
    user_content          TEXT NOT NULL,
    assistant_content     TEXT NOT NULL,
    route                 TEXT NOT NULL,
    state_json            TEXT,
    created_at            REAL NOT NULL,
    memory_status         TEXT NOT NULL DEFAULT 'pending',
    summary_status        TEXT NOT NULL DEFAULT 'pending',
    secondary_attempts    INTEGER NOT NULL DEFAULT 0,
    secondary_error       TEXT,
    PRIMARY KEY (user_id, conversation_id, request_id),
    FOREIGN KEY (conversation_id, user_id)
        REFERENCES chat_sessions(session_id, user_id) ON DELETE CASCADE,
    FOREIGN KEY (user_message_id)
        REFERENCES chat_messages(message_id) ON DELETE CASCADE,
    FOREIGN KEY (assistant_message_id)
        REFERENCES chat_messages(message_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_user
    ON chat_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_owner_session
    ON chat_messages(user_id, conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_created
    ON chat_messages(created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_user_updated
    ON chat_sessions(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_requests_owner_session
    ON chat_requests(user_id, conversation_id, created_at);
"""


class ChatArchive:
    """Synchronous, owner-scoped SQLite chat archive."""

    _ROLES = frozenset({"user", "assistant"})
    _BUSY_TIMEOUT_MS = 10_000

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=self._BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,
        )
        try:
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout={self._BUSY_TIMEOUT_MS}")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            return conn
        except BaseException:
            conn.close()
            raise

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA)
        finally:
            conn.close()

        # Backfill durable sessions for databases created by the legacy archive.
        # A legacy database that assigned one global conversation ID to multiple
        # owners is ambiguous under the new ownership contract, so fail loudly.
        with self._transaction() as conn:
            request_columns = {
                row["name"] for row in conn.execute(
                    "PRAGMA table_info(chat_requests)"
                ).fetchall()
            }
            for name, definition in (
                ("memory_status", "TEXT NOT NULL DEFAULT 'pending'"),
                ("summary_status", "TEXT NOT NULL DEFAULT 'pending'"),
                ("secondary_attempts", "INTEGER NOT NULL DEFAULT 0"),
                ("secondary_error", "TEXT"),
            ):
                if name not in request_columns:
                    conn.execute(f"ALTER TABLE chat_requests ADD COLUMN {name} {definition}")
            conflicts = conn.execute(
                "SELECT conversation_id FROM chat_messages "
                "GROUP BY conversation_id HAVING COUNT(DISTINCT user_id) > 1 LIMIT 1"
            ).fetchone()
            if conflicts is not None:
                raise ValueError(
                    "conversation_id has multiple owners: "
                    f"{conflicts['conversation_id']!r}"
                )
            conn.execute(
                "INSERT OR IGNORE INTO chat_sessions "
                "(session_id, user_id, created_at, updated_at, next_sequence) "
                "SELECT conversation_id, MIN(user_id), MIN(created_at), "
                "MAX(created_at), MAX(sequence_number) + 1 "
                "FROM chat_messages GROUP BY conversation_id"
            )
            conn.execute(
                "UPDATE chat_sessions SET next_sequence = MAX(next_sequence, "
                "COALESCE((SELECT MAX(m.sequence_number) + 1 FROM chat_messages m "
                "WHERE m.conversation_id = chat_sessions.session_id), 1))"
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_session_sequence "
                "ON chat_messages(conversation_id, sequence_number)"
            )

    @staticmethod
    def _required(value: str, name: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} must be a non-empty string")
        return value

    @classmethod
    def _role(cls, role: str) -> str:
        if role not in cls._ROLES:
            raise ValueError("role must be 'user' or 'assistant'")
        return role

    @staticmethod
    def _content(value: str, name: str = "content") -> str:
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a string")
        return value

    @staticmethod
    def _page_value(value: int, name: str) -> int:
        if not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
        return value

    def _ensure_session_tx(
        self, conn: sqlite3.Connection, user_id: str, conversation_id: str,
        *, now: Optional[float] = None,
    ) -> None:
        now = time.time() if now is None else now
        deleted = conn.execute(
            "SELECT 1 FROM deleted_users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if deleted is not None:
            raise PermissionError("user identity has been deleted")
        conn.execute(
            "INSERT OR IGNORE INTO chat_sessions "
            "(session_id, user_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (conversation_id, user_id, now, now),
        )
        owner = conn.execute(
            "SELECT user_id FROM chat_sessions WHERE session_id = ?",
            (conversation_id,),
        ).fetchone()
        if owner is None or owner["user_id"] != user_id:
            raise PermissionError("conversation belongs to a different user")

    @staticmethod
    def _allocate_sequences(
        conn: sqlite3.Connection, conversation_id: str, count: int, now: float,
    ) -> List[int]:
        row = conn.execute(
            "SELECT next_sequence FROM chat_sessions WHERE session_id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("session disappeared during sequence allocation")
        first = int(row["next_sequence"])
        conn.execute(
            "UPDATE chat_sessions SET next_sequence = ?, updated_at = ? "
            "WHERE session_id = ?",
            (first + count, now, conversation_id),
        )
        return list(range(first, first + count))

    @staticmethod
    def _new_message_id(conn: sqlite3.Connection) -> str:
        while True:
            candidate = uuid.uuid4().hex
            exists = conn.execute(
                "SELECT 1 FROM chat_messages WHERE message_id = ?", (candidate,)
            ).fetchone()
            if exists is None:
                return candidate

    def next_sequence(self, conversation_id: str) -> int:
        """Return the next sequence value without reserving it.

        Sequence allocation used by ``record`` and ``record_turn`` is performed
        atomically inside their transactions; this legacy inspection method is
        intentionally not suitable for external allocation.
        """
        self._required(conversation_id, "conversation_id")
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT next_sequence FROM chat_sessions WHERE session_id = ?",
                (conversation_id,),
            ).fetchone()
            if row is not None:
                return int(row["next_sequence"])
            row = conn.execute(
                "SELECT COALESCE(MAX(sequence_number), 0) + 1 AS value "
                "FROM chat_messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            return int(row["value"])
        finally:
            conn.close()

    def record(
        self, user_id: str, conversation_id: str, role: str, content: str,
        message_id: Optional[str] = None,
    ) -> ChatMessage:
        """Synchronously persist one message and return the stored row."""
        user_id = self._required(user_id, "user_id")
        conversation_id = self._required(conversation_id, "conversation_id")
        role = self._role(role)
        content = self._content(content)
        if message_id is not None:
            message_id = self._required(message_id, "message_id")
        now = time.time()

        with self._transaction() as conn:
            if message_id is not None:
                existing = conn.execute(
                    "SELECT message_id, user_id, conversation_id, role, content, "
                    "created_at, sequence_number FROM chat_messages "
                    "WHERE message_id = ?",
                    (message_id,),
                ).fetchone()
                if existing is not None:
                    if (existing["user_id"], existing["conversation_id"]) != (
                        user_id, conversation_id
                    ):
                        raise ValueError("message_id is already in use")
                    return self._row(existing)

            self._ensure_session_tx(conn, user_id, conversation_id, now=now)
            sequence = self._allocate_sequences(conn, conversation_id, 1, now)[0]
            actual_id = message_id or self._new_message_id(conn)
            conn.execute(
                "INSERT INTO chat_messages "
                "(message_id, user_id, conversation_id, role, content, "
                "created_at, sequence_number) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (actual_id, user_id, conversation_id, role, content, now, sequence),
            )
            return ChatMessage(
                user_id=user_id,
                conversation_id=conversation_id,
                role=role,
                content=content,
                sequence_number=sequence,
                message_id=actual_id,
                created_at=now,
            )

    def record_turn(
        self, user_id: str, conversation_id: str, user_content: str,
        assistant_content: str, request_id: str, state: Optional[dict] = None,
        route: str = "support",
    ) -> Dict[str, Any]:
        """Atomically persist a complete turn, idempotent by request ID."""
        user_id = self._required(user_id, "user_id")
        conversation_id = self._required(conversation_id, "conversation_id")
        request_id = self._required(request_id, "request_id")
        user_content = self._content(user_content, "user_content")
        assistant_content = self._content(assistant_content, "assistant_content")
        route_value = getattr(route, "value", route)
        route_value = self._required(str(route_value), "route")
        state_json = None
        if state is not None:
            if not isinstance(state, dict):
                raise TypeError("state must be a dict or None")
            state_json = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        now = time.time()

        with self._transaction() as conn:
            self._ensure_session_tx(conn, user_id, conversation_id, now=now)
            existing = self._get_request_tx(
                conn, user_id, conversation_id, request_id
            )
            if existing is not None:
                if existing["user_content"] != user_content:
                    raise ValueError(
                        "idempotency key was already used for a different message"
                    )
                return self._request_dict(existing, duplicate=True)

            user_seq, assistant_seq = self._allocate_sequences(
                conn, conversation_id, 2, now
            )
            user_message_id = self._new_message_id(conn)
            assistant_message_id = self._new_message_id(conn)
            conn.executemany(
                "INSERT INTO chat_messages "
                "(message_id, user_id, conversation_id, role, content, "
                "created_at, sequence_number) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (user_message_id, user_id, conversation_id, "user",
                     user_content, now, user_seq),
                    (assistant_message_id, user_id, conversation_id, "assistant",
                     assistant_content, now, assistant_seq),
                ],
            )
            conn.execute(
                "INSERT INTO chat_requests "
                "(user_id, conversation_id, request_id, user_message_id, "
                "assistant_message_id, user_content, assistant_content, route, "
                "state_json, created_at, memory_status, summary_status, "
                "secondary_attempts, secondary_error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'pending', 0, NULL)",
                (user_id, conversation_id, request_id, user_message_id,
                 assistant_message_id, user_content, assistant_content,
                 route_value, state_json, now),
            )
            metadata = {
                "last_request_id": request_id,
                "last_route": route_value,
                "last_turn_at": now,
            }
            if state_json is None:
                conn.execute(
                    "UPDATE chat_sessions SET metadata_json = ?, updated_at = ? "
                    "WHERE session_id = ?",
                    (json.dumps(metadata, separators=(",", ":")), now,
                     conversation_id),
                )
            else:
                conn.execute(
                    "UPDATE chat_sessions SET metadata_json = ?, safety_state = ?, "
                    "updated_at = ? WHERE session_id = ?",
                    (json.dumps(metadata, separators=(",", ":")), state_json,
                     now, conversation_id),
                )
            row = self._get_request_tx(conn, user_id, conversation_id, request_id)
            if row is None:
                raise RuntimeError("request disappeared during transaction")
            return self._request_dict(row, duplicate=False)

    @staticmethod
    def _get_request_tx(
        conn: sqlite3.Connection, user_id: str, conversation_id: str,
        request_id: str,
    ) -> Optional[sqlite3.Row]:
        return conn.execute(
            "SELECT user_id, conversation_id, request_id, user_message_id, "
            "assistant_message_id, user_content, assistant_content, route, "
            "state_json, created_at, memory_status, summary_status, "
            "secondary_attempts, secondary_error FROM chat_requests "
            "WHERE user_id = ? AND conversation_id = ? AND request_id = ?",
            (user_id, conversation_id, request_id),
        ).fetchone()

    @staticmethod
    def _request_dict(row: sqlite3.Row, *, duplicate: bool) -> Dict[str, Any]:
        state = json.loads(row["state_json"]) if row["state_json"] is not None else None
        return {
            "user_id": row["user_id"],
            "conversation_id": row["conversation_id"],
            "request_id": row["request_id"],
            "user_message_id": row["user_message_id"],
            "assistant_message_id": row["assistant_message_id"],
            "user_content": row["user_content"],
            "assistant_content": row["assistant_content"],
            "reply": row["assistant_content"],
            "route": row["route"],
            "state": state,
            "created_at": float(row["created_at"]),
            "memory_status": row["memory_status"],
            "summary_status": row["summary_status"],
            "secondary_attempts": int(row["secondary_attempts"]),
            "secondary_error": row["secondary_error"],
            "duplicate": duplicate,
        }

    def get_request(
        self, user_id: str, conversation_id: str, request_id: str,
    ) -> Optional[Dict[str, Any]]:
        user_id = self._required(user_id, "user_id")
        conversation_id = self._required(conversation_id, "conversation_id")
        request_id = self._required(request_id, "request_id")
        conn = self._connect()
        try:
            row = self._get_request_tx(conn, user_id, conversation_id, request_id)
            return None if row is None else self._request_dict(row, duplicate=True)
        finally:
            conn.close()

    def pending_secondary(
        self, user_id: str, conversation_id: str, limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return durable derived-work items that still need convergence."""
        limit = self._page_value(limit, "limit")
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT user_id, conversation_id, request_id, user_message_id, "
                "assistant_message_id, user_content, assistant_content, route, "
                "state_json, created_at, memory_status, summary_status, "
                "secondary_attempts, secondary_error FROM chat_requests "
                "WHERE user_id = ? AND conversation_id = ? AND "
                "(memory_status != 'completed' OR summary_status != 'completed') "
                "ORDER BY created_at ASC LIMIT ?",
                (user_id, conversation_id, limit),
            ).fetchall()
            return [self._request_dict(row, duplicate=True) for row in rows]
        finally:
            conn.close()

    def mark_secondary(
        self, user_id: str, conversation_id: str, request_id: str,
        component: str, *, error: Optional[str] = None,
    ) -> None:
        if component not in {"memory", "summary"}:
            raise ValueError("component must be 'memory' or 'summary'")
        status_column = f"{component}_status"
        with self._transaction() as conn:
            result = conn.execute(
                f"UPDATE chat_requests SET {status_column} = ?, "
                "secondary_attempts = secondary_attempts + ?, secondary_error = ? "
                "WHERE user_id = ? AND conversation_id = ? AND request_id = ?",
                ("failed" if error else "completed", 1 if error else 0,
                 (error or None), user_id, conversation_id, request_id),
            )
            if result.rowcount != 1:
                raise LookupError("secondary work item not found")

    def secondary_pending_count(self) -> int:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS value FROM chat_requests WHERE "
                "memory_status != 'completed' OR summary_status != 'completed'"
            ).fetchone()
            return int(row["value"])
        finally:
            conn.close()

    def ensure_session(self, user_id: str, conversation_id: str) -> Dict[str, Any]:
        user_id = self._required(user_id, "user_id")
        conversation_id = self._required(conversation_id, "conversation_id")
        with self._transaction() as conn:
            self._ensure_session_tx(conn, user_id, conversation_id)
            return self._session_dict_tx(conn, user_id, conversation_id)

    def owns_session(self, user_id: str, conversation_id: str) -> bool:
        user_id = self._required(user_id, "user_id")
        conversation_id = self._required(conversation_id, "conversation_id")
        conn = self._connect()
        try:
            return conn.execute(
                "SELECT 1 FROM chat_sessions WHERE session_id = ? AND user_id = ?",
                (conversation_id, user_id),
            ).fetchone() is not None
        finally:
            conn.close()

    @staticmethod
    def _session_dict_tx(
        conn: sqlite3.Connection, user_id: str, conversation_id: str,
    ) -> Dict[str, Any]:
        row = conn.execute(
            "SELECT s.session_id, s.user_id, s.created_at, s.updated_at, "
            "COUNT(m.message_id) AS message_count, "
            "COALESCE((SELECT substr(first.content, 1, 40) FROM chat_messages first "
            "WHERE first.user_id = s.user_id AND first.conversation_id = s.session_id "
            "ORDER BY first.sequence_number ASC LIMIT 1), 'New Chat') AS title, "
            "COALESCE((SELECT substr(last.content, 1, 60) FROM chat_messages last "
            "WHERE last.user_id = s.user_id AND last.conversation_id = s.session_id "
            "ORDER BY last.sequence_number DESC LIMIT 1), '') AS last_message "
            "FROM chat_sessions s LEFT JOIN chat_messages m "
            "ON m.user_id = s.user_id AND m.conversation_id = s.session_id "
            "WHERE s.user_id = ? AND s.session_id = ? GROUP BY s.session_id",
            (user_id, conversation_id),
        ).fetchone()
        if row is None:
            raise LookupError("session not found")
        return {
            "session_id": row["session_id"],
            "user_id": row["user_id"],
            "title": row["title"],
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "last_message": row["last_message"],
            "message_count": int(row["message_count"]),
        }

    def create_session(
        self, user_id: str, session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        user_id = self._required(user_id, "user_id")
        supplied = session_id is not None
        if supplied:
            session_id = self._required(session_id, "session_id")
        with self._transaction() as conn:
            if conn.execute(
                "SELECT 1 FROM deleted_users WHERE user_id = ?", (user_id,)
            ).fetchone() is not None:
                raise PermissionError("user identity has been deleted")
            while True:
                candidate = session_id if supplied else uuid.uuid4().hex
                now = time.time()
                try:
                    conn.execute(
                        "INSERT INTO chat_sessions "
                        "(session_id, user_id, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?)",
                        (candidate, user_id, now, now),
                    )
                    return self._session_dict_tx(conn, user_id, candidate)
                except sqlite3.IntegrityError:
                    if supplied:
                        raise ValueError("session_id is already in use") from None
                    # A generated UUID collision is extraordinarily unlikely,
                    # but retrying makes collision prevention deterministic.

    def save_safety_state(
        self, user_id: str, conversation_id: str, state: dict, *,
        completed_request_id: Optional[str] = None,
        memory_completed: bool = False,
    ) -> None:
        user_id = self._required(user_id, "user_id")
        conversation_id = self._required(conversation_id, "conversation_id")
        if not isinstance(state, dict):
            raise TypeError("state must be a dict")
        payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        now = time.time()
        with self._transaction() as conn:
            self._ensure_session_tx(conn, user_id, conversation_id, now=now)
            conn.execute(
                "UPDATE chat_sessions SET safety_state = ?, updated_at = ? "
                "WHERE session_id = ? AND user_id = ?",
                (payload, now, conversation_id, user_id),
            )
            if completed_request_id:
                assignments = ["summary_status = 'completed'", "secondary_error = NULL"]
                if memory_completed:
                    assignments.append("memory_status = 'completed'")
                result = conn.execute(
                    "UPDATE chat_requests SET " + ", ".join(assignments) +
                    " WHERE user_id = ? AND conversation_id = ? AND request_id = ?",
                    (user_id, conversation_id, completed_request_id),
                )
                if result.rowcount != 1:
                    raise LookupError("secondary work item not found")

    def load_safety_state(self, user_id: str, conversation_id: str) -> dict:
        user_id = self._required(user_id, "user_id")
        conversation_id = self._required(conversation_id, "conversation_id")
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT safety_state FROM chat_sessions "
                "WHERE session_id = ? AND user_id = ?",
                (conversation_id, user_id),
            ).fetchone()
            if row is None:
                return {}
            state = json.loads(row["safety_state"])
            if not isinstance(state, dict):
                raise ValueError("stored safety state is not a JSON object")
            return state
        finally:
            conn.close()

    def healthcheck(self) -> None:
        conn = self._connect()
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()

    def flush(self, timeout: Optional[float] = None) -> None:
        """No-op: every write is committed before it returns."""

    def close(self) -> None:
        """No-op: operations do not retain database connections."""

    # Reads are always owner-scoped and use short-lived connections.
    def fetch_recent(
        self, user_id: str, conversation_id: str, limit: int = 20,
    ) -> List[ChatMessage]:
        user_id = self._required(user_id, "user_id")
        conversation_id = self._required(conversation_id, "conversation_id")
        limit = self._page_value(limit, "limit")
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT message_id, user_id, conversation_id, role, content, "
                "created_at, sequence_number FROM ("
                "SELECT message_id, user_id, conversation_id, role, content, "
                "created_at, sequence_number FROM chat_messages "
                "WHERE user_id = ? AND conversation_id = ? "
                "ORDER BY sequence_number DESC LIMIT ?) "
                "ORDER BY sequence_number ASC",
                (user_id, conversation_id, limit),
            ).fetchall()
            return [self._row(row) for row in rows]
        finally:
            conn.close()

    def fetch_page(
        self, user_id: str, conversation_id: str, offset: int = 0,
        limit: int = 50,
    ) -> List[ChatMessage]:
        user_id = self._required(user_id, "user_id")
        conversation_id = self._required(conversation_id, "conversation_id")
        offset = self._page_value(offset, "offset")
        limit = self._page_value(limit, "limit")
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT message_id, user_id, conversation_id, role, content, "
                "created_at, sequence_number FROM chat_messages "
                "WHERE user_id = ? AND conversation_id = ? "
                "ORDER BY sequence_number ASC LIMIT ? OFFSET ?",
                (user_id, conversation_id, limit, offset),
            ).fetchall()
            return [self._row(row) for row in rows]
        finally:
            conn.close()

    def count(self, user_id: str, conversation_id: Optional[str] = None) -> int:
        user_id = self._required(user_id, "user_id")
        conn = self._connect()
        try:
            if conversation_id is None:
                row = conn.execute(
                    "SELECT COUNT(*) AS value FROM chat_messages WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
            else:
                conversation_id = self._required(conversation_id, "conversation_id")
                row = conn.execute(
                    "SELECT COUNT(*) AS value FROM chat_messages "
                    "WHERE user_id = ? AND conversation_id = ?",
                    (user_id, conversation_id),
                ).fetchone()
            return int(row["value"])
        finally:
            conn.close()

    def export_user(self, user_id: str) -> List[ChatMessage]:
        user_id = self._required(user_id, "user_id")
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT message_id, user_id, conversation_id, role, content, "
                "created_at, sequence_number FROM chat_messages WHERE user_id = ? "
                "ORDER BY conversation_id, sequence_number",
                (user_id,),
            ).fetchall()
            return [self._row(row) for row in rows]
        finally:
            conn.close()

    def list_sessions(self, user_id: str) -> List[dict]:
        user_id = self._required(user_id, "user_id")
        conn = self._connect()
        try:
            ids = conn.execute(
                "SELECT session_id FROM chat_sessions WHERE user_id = ? "
                "ORDER BY updated_at DESC, session_id ASC",
                (user_id,),
            ).fetchall()
            return [self._session_dict_tx(conn, user_id, row["session_id"])
                    for row in ids]
        finally:
            conn.close()

    def recent_sessions(
        self, user_id: str, *, exclude: Optional[str] = None,
        limit: int = 3, per_session: int = 40,
    ) -> List[dict]:
        user_id = self._required(user_id, "user_id")
        limit = self._page_value(limit, "limit")
        per_session = self._page_value(per_session, "per_session")
        out: List[dict] = []
        for meta in self.list_sessions(user_id):
            session_id = meta["session_id"]
            if session_id == exclude:
                continue
            messages = self.fetch_recent(user_id, session_id, per_session)
            if not messages:
                continue
            out.append({
                "session_id": session_id,
                "updated_at": meta["updated_at"],
                "messages": [
                    {"role": message.role, "content": message.content}
                    for message in messages
                ],
            })
            if len(out) >= limit:
                break
        return out

    def session_digests(
        self, user_id: str, *, exclude: Optional[str] = None,
        limit: int = 30, skip: int = 0,
    ) -> List[dict]:
        user_id = self._required(user_id, "user_id")
        limit = self._page_value(limit, "limit")
        skip = self._page_value(skip, "skip")
        metas = [meta for meta in self.list_sessions(user_id)
                 if meta["session_id"] != exclude]
        conn = self._connect()
        try:
            out: List[dict] = []
            for meta in metas[skip:skip + limit]:
                rows = conn.execute(
                    "SELECT content FROM chat_messages WHERE user_id = ? "
                    "AND conversation_id = ? AND role = 'user' "
                    "ORDER BY sequence_number ASC",
                    (user_id, meta["session_id"]),
                ).fetchall()
                contents = [row["content"] for row in rows if row["content"]]
                if not contents:
                    continue
                text = " ".join(contents)
                if len(text) > 4000:
                    # Preserve both origin and latest disclosures. Oldest-only
                    # truncation made late facts permanently undiscoverable.
                    text = text[:1980] + " … [later in session] … " + text[-1980:]
                out.append({
                    "session_id": meta["session_id"],
                    "updated_at": meta["updated_at"],
                    "text": text,
                })
            return out
        finally:
            conn.close()

    def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        """Delete an owned session and return whether it existed."""
        user_id = self._required(user_id, "user_id")
        conversation_id = self._required(conversation_id, "conversation_id")
        with self._transaction() as conn:
            exists = conn.execute(
                "SELECT 1 FROM chat_sessions WHERE session_id = ? AND user_id = ?",
                (conversation_id, user_id),
            ).fetchone()
            if exists is None:
                return False
            conn.execute(
                "DELETE FROM chat_requests WHERE user_id = ? AND conversation_id = ?",
                (user_id, conversation_id),
            )
            conn.execute(
                "DELETE FROM chat_messages WHERE user_id = ? AND conversation_id = ?",
                (user_id, conversation_id),
            )
            deleted = conn.execute(
                "DELETE FROM chat_sessions WHERE session_id = ? AND user_id = ?",
                (conversation_id, user_id),
            ).rowcount
            return deleted == 1

    def is_user_deleted(self, user_id: str) -> bool:
        user_id = self._required(user_id, "user_id")
        conn = self._connect()
        try:
            return conn.execute(
                "SELECT 1 FROM deleted_users WHERE user_id = ?", (user_id,)
            ).fetchone() is not None
        finally:
            conn.close()

    def delete_user(self, user_id: str) -> int:
        """Delete all user data and return the exact number of messages removed."""
        user_id = self._required(user_id, "user_id")
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS value FROM chat_messages WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            message_count = int(row["value"])
            conn.execute("DELETE FROM chat_requests WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM chat_messages WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM chat_sessions WHERE user_id = ?", (user_id,))
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                "AND name = 'long_term_memories'"
            ).fetchone() is not None:
                conn.execute(
                    "DELETE FROM long_term_memories WHERE user_id = ?", (user_id,)
                )
            conn.execute(
                "INSERT OR REPLACE INTO deleted_users (user_id, deleted_at) VALUES (?, ?)",
                (user_id, time.time()),
            )
            return message_count

    @staticmethod
    def _row(row: sqlite3.Row) -> ChatMessage:
        return ChatMessage(
            message_id=row["message_id"],
            user_id=row["user_id"],
            conversation_id=row["conversation_id"],
            role=row["role"],
            content=row["content"],
            created_at=float(row["created_at"]),
            sequence_number=int(row["sequence_number"]),
        )
