"""Layer 3 - Feedback database (STRICTLY ISOLATED from chat).

Stores bug reports, feature requests, UI suggestions and improvement ideas in a
SEPARATE SQLite database from the chat archive.

Isolation guarantee: this module exposes no read API that the chat pipeline uses,
and the ChatbotService never imports or holds a reference to it. Feedback can
therefore never influence a generated response.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

VALID_CATEGORIES = {"bug", "feature", "ui", "improvement", "other"}


@dataclass
class FeedbackItem:
    user_id: str
    category: str
    message: str
    feedback_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    status: str = "new"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    category    TEXT NOT NULL,
    message     TEXT NOT NULL,
    created_at  REAL NOT NULL,
    status      TEXT NOT NULL DEFAULT 'new'
);
CREATE INDEX IF NOT EXISTS idx_fb_user     ON feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_fb_category ON feedback(category);
CREATE INDEX IF NOT EXISTS idx_fb_created  ON feedback(created_at);
"""


class FeedbackStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.commit()

    def submit(self, user_id: str, message: str, category: str = "other") -> FeedbackItem:
        category = (category or "other").lower().strip()
        if category not in VALID_CATEGORIES:
            category = "other"
        item = FeedbackItem(user_id=user_id, category=category, message=message.strip())
        with self._lock:
            self._conn.execute(
                "INSERT INTO feedback (feedback_id, user_id, category, message, created_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (item.feedback_id, item.user_id, item.category, item.message,
                 item.created_at, item.status),
            )
            self._conn.commit()
        return item

    # --- admin-only reads (never used by the chat pipeline) ---
    def list_feedback(self, category: Optional[str] = None, limit: int = 100) -> List[FeedbackItem]:
        with self._lock:
            if category:
                cur = self._conn.execute(
                    "SELECT feedback_id, user_id, category, message, created_at, status "
                    "FROM feedback WHERE category = ? ORDER BY created_at DESC LIMIT ?",
                    (category, limit))
            else:
                cur = self._conn.execute(
                    "SELECT feedback_id, user_id, category, message, created_at, status "
                    "FROM feedback ORDER BY created_at DESC LIMIT ?", (limit,))
            return [
                FeedbackItem(feedback_id=r[0], user_id=r[1], category=r[2],
                             message=r[3], created_at=r[4], status=r[5])
                for r in cur.fetchall()
            ]

    def count(self, user_id: Optional[str] = None) -> int:
        with self._lock:
            if user_id:
                cur = self._conn.execute(
                    "SELECT COUNT(*) FROM feedback WHERE user_id = ?", (user_id,))
            else:
                cur = self._conn.execute("SELECT COUNT(*) FROM feedback")
            return int(cur.fetchone()[0])

    def delete_user(self, user_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM feedback WHERE user_id = ?", (user_id,))
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
