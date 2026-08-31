"""Compatibility archive with restart-safe migration of legacy JSON chats."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path

from app.storage.chat_archive import ChatArchive, ChatMessage


class ChatArchiveJSON(ChatArchive):
    """Deprecated name backed by SQLite; imports historical JSON exactly once.

    Source files are validated and never modified or deleted. Each file and its
    checksum are recorded in the SQLite transaction that imports its messages,
    making retries safe after interruption.
    """

    def __init__(self, storage_dir: Path):
        self._legacy_dir = Path(storage_dir)
        self._legacy_dir.mkdir(parents=True, exist_ok=True)
        super().__init__(self._legacy_dir / "chat_archive.sqlite3")
        self.migration_report = self.migrate_legacy_json()

    @staticmethod
    def _text(value, name: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"legacy {name} must be a non-empty string")
        return value

    def migrate_legacy_json(self) -> dict:
        files = sorted(self._legacy_dir.rglob("*.json"))
        report = {"discovered": len(files), "imported": 0, "skipped": 0,
                  "messages": 0}
        for path in files:
            imported, count = self._migrate_file(path)
            report["imported" if imported else "skipped"] += 1
            report["messages"] += count
        return report
    def _migrate_file(self, path: Path) -> tuple[bool, int]:
        raw = path.read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid legacy chat JSON: {path}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"legacy chat must be an object: {path}")

        user_id = self._text(payload.get("user_id"), "user_id")
        session_id = self._text(payload.get("session_id"), "session_id")
        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            raise ValueError(f"legacy messages must be an array: {path}")
        created_at = payload.get("created_at", time.time())
        if not isinstance(created_at, (int, float)):
            raise ValueError(f"legacy created_at must be numeric: {path}")
        state = payload.get("safety_state") or {}
        if not isinstance(state, dict):
            raise ValueError(f"legacy safety_state must be an object: {path}")

        normalized = []
        seen_ids = set()
        for index, item in enumerate(messages, start=1):
            if not isinstance(item, dict):
                raise ValueError(f"legacy message {index} must be an object: {path}")
            role = item.get("role")
            if role not in self._ROLES:
                raise ValueError(f"legacy message {index} has invalid role: {path}")
            content = item.get("content")
            if not isinstance(content, str):
                raise ValueError(f"legacy message {index} content must be text: {path}")
            timestamp = item.get("created_at", created_at)
            if not isinstance(timestamp, (int, float)):
                raise ValueError(f"legacy message {index} timestamp must be numeric: {path}")
            message_id = item.get("message_id") or uuid.uuid5(
                uuid.NAMESPACE_URL, f"legacy-chat:{checksum}:{index}"
            ).hex
            message_id = self._text(message_id, "message_id")
            if message_id in seen_ids:
                raise ValueError(f"duplicate legacy message_id in {path}")
            seen_ids.add(message_id)
            normalized.append((message_id, role, content, float(timestamp), index))
        relative_path = path.relative_to(self._legacy_dir).as_posix()
        with self._transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS legacy_json_migrations ("
                "source_path TEXT PRIMARY KEY, source_sha256 TEXT NOT NULL, "
                "user_id TEXT NOT NULL, session_id TEXT NOT NULL, "
                "message_count INTEGER NOT NULL, migrated_at REAL NOT NULL)"
            )
            prior = conn.execute(
                "SELECT source_sha256, message_count FROM legacy_json_migrations "
                "WHERE source_path = ?", (relative_path,)
            ).fetchone()
            if prior is not None:
                if prior["source_sha256"] != checksum:
                    raise ValueError(
                        f"legacy source changed after migration: {relative_path}"
                    )
                return False, int(prior["message_count"])

            owner = conn.execute(
                "SELECT user_id FROM chat_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if owner is not None:
                if owner["user_id"] != user_id:
                    raise ValueError(f"legacy session owner collision: {session_id}")
                existing_count = conn.execute(
                    "SELECT COUNT(*) AS value FROM chat_messages "
                    "WHERE user_id = ? AND conversation_id = ?",
                    (user_id, session_id),
                ).fetchone()["value"]
                if existing_count:
                    raise ValueError(f"legacy session collides with existing data: {session_id}")
            else:
                updated_at = max([created_at] + [row[3] for row in normalized])
                conn.execute(
                    "INSERT INTO chat_sessions (session_id, user_id, created_at, "
                    "updated_at, next_sequence, safety_state) VALUES (?, ?, ?, ?, ?, ?)",
                    (session_id, user_id, float(created_at), float(updated_at),
                     len(normalized) + 1,
                     json.dumps(state, ensure_ascii=False, separators=(",", ":"))),
                )

            for message_id, role, content, timestamp, sequence in normalized:
                collision = conn.execute(
                    "SELECT 1 FROM chat_messages WHERE message_id = ?", (message_id,)
                ).fetchone()
                if collision is not None:
                    raise ValueError(f"legacy message_id collision: {message_id}")
                conn.execute(
                    "INSERT INTO chat_messages (message_id, user_id, conversation_id, "
                    "role, content, created_at, sequence_number) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (message_id, user_id, session_id, role, content,
                     timestamp, sequence),
                )
            conn.execute(
                "UPDATE chat_sessions SET next_sequence = ?, metadata_json = ? "
                "WHERE session_id = ? AND user_id = ?",
                (len(normalized) + 1, json.dumps(
                    {"legacy_json_source": relative_path}, separators=(",", ":")
                ), session_id, user_id),
            )
            conn.execute(
                "INSERT INTO legacy_json_migrations (source_path, source_sha256, "
                "user_id, session_id, message_count, migrated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (relative_path, checksum, user_id, session_id,
                 len(normalized), time.time()),
            )
        return True, len(normalized)


__all__ = ["ChatArchiveJSON", "ChatMessage"]
