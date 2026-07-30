"""Complete conversation archive in SQLite.

STORAGE != LLM CONTEXT. This stores every accepted user message and every
generated assistant reply for record/history purposes. The LLM context is built
separately and small (see ChatbotService).

Design notes:
- Indexed by user_id, conversation_id, created_at for scalable reads.
- Writes are non-blocking: enqueued and flushed by a single background worker
  thread, so persistence never delays the visible response.
- Idempotent: message_id is the primary key with INSERT OR IGNORE, so duplicate
  submissions / retries don't create duplicates.
- User isolation: every read is filtered by user_id.
- Never loads a user's full history into RAM; reads are paginated/limited.
"""

from __future__ import annotations

import queue
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class ChatMessage:
    user_id: str
    conversation_id: str
    role: str                      # "user" | "assistant"
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
CREATE INDEX IF NOT EXISTS idx_user        ON chat_messages(user_id);
CREATE INDEX IF NOT EXISTS idx_conv        ON chat_messages(user_id, conversation_id);
CREATE INDEX IF NOT EXISTS idx_conv_seq    ON chat_messages(conversation_id, sequence_number);
CREATE INDEX IF NOT EXISTS idx_created     ON chat_messages(created_at);
"""


class ChatArchive:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # WAL + a short busy timeout make concurrent readers/writer safe.
        self._init_conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._init_conn.executescript(_SCHEMA)
        self._init_conn.execute("PRAGMA journal_mode=WAL;")
        self._init_conn.commit()

        self._seq_lock = threading.Lock()
        self._seq_cache: dict[str, int] = {}

        # Background writer.
        self._queue: "queue.Queue[Optional[ChatMessage]]" = queue.Queue()
        self._worker = threading.Thread(target=self._run_writer, daemon=True)
        self._worker.start()

    # ------------------------------------------------------------------
    # Writes (non-blocking)
    # ------------------------------------------------------------------
    def next_sequence(self, conversation_id: str) -> int:
        with self._seq_lock:
            if conversation_id not in self._seq_cache:
                cur = self._init_conn.execute(
                    "SELECT COALESCE(MAX(sequence_number), 0) FROM chat_messages WHERE conversation_id = ?",
                    (conversation_id,),
                )
                self._seq_cache[conversation_id] = int(cur.fetchone()[0])
            self._seq_cache[conversation_id] += 1
            return self._seq_cache[conversation_id]

    def record(self, user_id: str, conversation_id: str, role: str, content: str,
               message_id: Optional[str] = None) -> ChatMessage:
        """Enqueue a message for async persistence. Returns the message object."""
        msg = ChatMessage(
            user_id=user_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            sequence_number=self.next_sequence(conversation_id),
            message_id=message_id or uuid.uuid4().hex,
        )
        self._queue.put(msg)
        return msg

    def _run_writer(self) -> None:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.execute("PRAGMA busy_timeout=5000;")
        while True:
            msg = self._queue.get()
            if msg is None:  # shutdown sentinel
                self._queue.task_done()
                break
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO chat_messages "
                    "(message_id, user_id, conversation_id, role, content, created_at, sequence_number) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (msg.message_id, msg.user_id, msg.conversation_id, msg.role,
                     msg.content, msg.created_at, msg.sequence_number),
                )
                conn.commit()
            except Exception:
                # Never crash the worker; a dropped archival write must not break chat.
                pass
            finally:
                self._queue.task_done()
        conn.close()

    def flush(self, timeout: Optional[float] = None) -> None:
        """Block until queued writes are persisted (used by tests)."""
        self._queue.join()

    def close(self) -> None:
        self._queue.put(None)

    # ------------------------------------------------------------------
    # Reads (always user-scoped)
    # ------------------------------------------------------------------
    def fetch_recent(self, user_id: str, conversation_id: str, limit: int = 20) -> List[ChatMessage]:
        cur = self._init_conn.execute(
            "SELECT message_id, user_id, conversation_id, role, content, created_at, sequence_number "
            "FROM chat_messages WHERE user_id = ? AND conversation_id = ? "
            "ORDER BY sequence_number DESC LIMIT ?",
            (user_id, conversation_id, limit),
        )
        rows = cur.fetchall()
        rows.reverse()  # chronological
        return [self._row(r) for r in rows]

    def fetch_page(self, user_id: str, conversation_id: str, offset: int = 0,
                   limit: int = 50) -> List[ChatMessage]:
        cur = self._init_conn.execute(
            "SELECT message_id, user_id, conversation_id, role, content, created_at, sequence_number "
            "FROM chat_messages WHERE user_id = ? AND conversation_id = ? "
            "ORDER BY sequence_number ASC LIMIT ? OFFSET ?",
            (user_id, conversation_id, limit, offset),
        )
        return [self._row(r) for r in cur.fetchall()]

    def count(self, user_id: str, conversation_id: Optional[str] = None) -> int:
        if conversation_id is None:
            cur = self._init_conn.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE user_id = ?", (user_id,))
        else:
            cur = self._init_conn.execute(
                "SELECT COUNT(*) FROM chat_messages WHERE user_id = ? AND conversation_id = ?",
                (user_id, conversation_id))
        return int(cur.fetchone()[0])

    def export_user(self, user_id: str) -> List[ChatMessage]:
        cur = self._init_conn.execute(
            "SELECT message_id, user_id, conversation_id, role, content, created_at, sequence_number "
            "FROM chat_messages WHERE user_id = ? ORDER BY conversation_id, sequence_number",
            (user_id,),
        )
        return [self._row(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Deletion (retention / account deletion)
    # ------------------------------------------------------------------
    def delete_conversation(self, user_id: str, conversation_id: str) -> None:
        self.flush()
        self._init_conn.execute(
            "DELETE FROM chat_messages WHERE user_id = ? AND conversation_id = ?",
            (user_id, conversation_id))
        self._init_conn.commit()

    def delete_user(self, user_id: str) -> None:
        self.flush()
        self._init_conn.execute("DELETE FROM chat_messages WHERE user_id = ?", (user_id,))
        self._init_conn.commit()

    def _row(self, r) -> ChatMessage:
        return ChatMessage(
            message_id=r[0], user_id=r[1], conversation_id=r[2], role=r[3],
            content=r[4], created_at=r[5], sequence_number=r[6],
        )
