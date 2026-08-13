"""Chat archive backed by JSON files — one file per session.

Drop-in replacement for the SQLite ChatArchive. Same public API.
Storage structure:
    data/chats/{user_id}/{session_id}.json

Each JSON file contains:
{
    "session_id": "...",
    "user_id": "...",
    "created_at": 1722816000.0,
    "messages": [
        {"message_id": "...", "role": "user", "content": "...", "created_at": 1722816000.0},
        {"message_id": "...", "role": "assistant", "content": "...", "created_at": 1722816001.0},
        ...
    ]
}

User isolation: each user has their own directory. Queries only access
files inside that user's directory.
"""

from __future__ import annotations

import json
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
    role: str
    content: str
    sequence_number: int
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)


class ChatArchiveJSON:
    """JSON file-backed conversation archive. One file per session."""

    def __init__(self, storage_dir: Path):
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _user_dir(self, user_id: str) -> Path:
        """Get/create the directory for a specific user."""
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in user_id)
        d = self._dir / safe_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _session_path(self, user_id: str, conversation_id: str) -> Path:
        """Get the JSON file path for a specific session."""
        safe_conv = "".join(c if c.isalnum() or c in "-_" else "_" for c in conversation_id)
        return self._user_dir(user_id) / f"{safe_conv}.json"

    def _load_session(self, user_id: str, conversation_id: str) -> dict:
        """Load a session file, or return a new empty session."""
        path = self._session_path(user_id, conversation_id)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "session_id": conversation_id,
            "user_id": user_id,
            "created_at": time.time(),
            "messages": [],
            "safety_state": {},
        }

    def _save_session(self, user_id: str, conversation_id: str, data: dict) -> None:
        """Persist a session to its JSON file."""
        path = self._session_path(user_id, conversation_id)
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass  # Never break chat over a persistence failure

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    def record(self, user_id: str, conversation_id: str, role: str, content: str,
               message_id: Optional[str] = None) -> ChatMessage:
        """Append a message to the session's JSON file."""
        with self._lock:
            data = self._load_session(user_id, conversation_id)
            seq = len(data["messages"]) + 1
            msg = ChatMessage(
                user_id=user_id,
                conversation_id=conversation_id,
                role=role,
                content=content,
                sequence_number=seq,
                message_id=message_id or uuid.uuid4().hex,
            )
            data["messages"].append({
                "message_id": msg.message_id,
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at,
                "sequence_number": seq,
            })
            self._save_session(user_id, conversation_id, data)
        return msg

    def flush(self, timeout: Optional[float] = None) -> None:
        """No-op (writes are synchronous)."""
        pass

    def close(self) -> None:
        """No-op."""
        pass

    def save_safety_state(self, user_id: str, conversation_id: str, state: dict) -> None:
        with self._lock:
            data = self._load_session(user_id, conversation_id)
            data["safety_state"] = dict(state or {})
            self._save_session(user_id, conversation_id, data)

    def load_safety_state(self, user_id: str, conversation_id: str) -> dict:
        with self._lock:
            data = self._load_session(user_id, conversation_id)
        return dict(data.get("safety_state") or {})

    # ------------------------------------------------------------------
    # Reads (always user-scoped)
    # ------------------------------------------------------------------
    def fetch_recent(self, user_id: str, conversation_id: str,
                     limit: int = 20) -> List[ChatMessage]:
        with self._lock:
            data = self._load_session(user_id, conversation_id)
        messages = data.get("messages", [])[-limit:]
        return [self._dict_to_msg(m, user_id, conversation_id) for m in messages]

    def fetch_page(self, user_id: str, conversation_id: str,
                   offset: int = 0, limit: int = 50) -> List[ChatMessage]:
        with self._lock:
            data = self._load_session(user_id, conversation_id)
        messages = data.get("messages", [])[offset:offset + limit]
        return [self._dict_to_msg(m, user_id, conversation_id) for m in messages]

    def count(self, user_id: str, conversation_id: Optional[str] = None) -> int:
        if conversation_id:
            with self._lock:
                data = self._load_session(user_id, conversation_id)
            return len(data.get("messages", []))
        # Count all messages across all sessions for this user
        total = 0
        user_dir = self._user_dir(user_id)
        for f in user_dir.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                total += len(d.get("messages", []))
            except Exception:
                pass
        return total

    def export_user(self, user_id: str) -> List[ChatMessage]:
        """Export all messages for a user across all sessions."""
        all_msgs = []
        user_dir = self._user_dir(user_id)
        for f in sorted(user_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                conv_id = data.get("session_id", f.stem)
                for m in data.get("messages", []):
                    all_msgs.append(self._dict_to_msg(m, user_id, conv_id))
            except Exception:
                pass
        return all_msgs

    # ------------------------------------------------------------------
    # Cross-session history (always scoped to one user)
    # ------------------------------------------------------------------
    def recent_sessions(self, user_id: str, *, exclude: Optional[str] = None,
                        limit: int = 3, per_session: int = 40) -> List[dict]:
        """Most recently updated other sessions, newest first, with messages."""
        out: List[dict] = []
        for meta in self.list_sessions(user_id):
            sid = meta.get("session_id", "")
            if not sid or sid == exclude:
                continue
            with self._lock:
                data = self._load_session(user_id, sid)
            msgs = data.get("messages", [])
            if not msgs:
                continue
            out.append({
                "session_id": sid,
                "updated_at": meta.get("updated_at", 0),
                "messages": [
                    {"role": m.get("role", ""), "content": m.get("content", "")}
                    for m in msgs[-per_session:]
                ],
            })
            if len(out) >= limit:
                break
        return out

    def session_digests(self, user_id: str, *, exclude: Optional[str] = None,
                        limit: int = 30, skip: int = 0) -> List[dict]:
        """Lightweight digests of older sessions for relevance selection.

        Returns only what is needed to score relevance, never whole transcripts,
        so scanning a long history stays cheap.
        """
        out: List[dict] = []
        metas = [m for m in self.list_sessions(user_id)
                 if m.get("session_id") and m.get("session_id") != exclude]
        for meta in metas[skip:skip + limit]:
            sid = meta["session_id"]
            with self._lock:
                data = self._load_session(user_id, sid)
            msgs = [m for m in data.get("messages", []) if m.get("role") == "user"]
            if not msgs:
                continue
            out.append({
                "session_id": sid,
                "updated_at": meta.get("updated_at", 0),
                "text": " ".join(m.get("content", "") for m in msgs)[:4000],
            })
        return out

    # ------------------------------------------------------------------
    # Session listing (for the multi-session UI)
    # ------------------------------------------------------------------
    def list_sessions(self, user_id: str) -> List[dict]:
        """List all sessions for a user, newest first."""
        sessions = []
        user_dir = self._user_dir(user_id)
        for f in user_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                messages = data.get("messages", [])
                last_msg = messages[-1]["content"][:60] if messages else ""
                sessions.append({
                    "session_id": data.get("session_id", f.stem),
                    "user_id": user_id,
                    "title": messages[0]["content"][:40] if messages else "New Chat",
                    "created_at": data.get("created_at", 0),
                    "updated_at": messages[-1].get("created_at", 0) if messages else data.get("created_at", 0),
                    "last_message": last_msg,
                    "message_count": len(messages),
                })
            except Exception:
                pass
        sessions.sort(key=lambda s: s["updated_at"], reverse=True)
        return sessions

    def create_session(self, user_id: str, session_id: Optional[str] = None) -> dict:
        """Create a new empty session file."""
        session_id = session_id or f"{user_id}-{uuid.uuid4().hex[:12]}"
        data = {
            "session_id": session_id,
            "user_id": user_id,
            "created_at": time.time(),
            "messages": [],
            "safety_state": {},
        }
        with self._lock:
            self._save_session(user_id, session_id, data)
        return {"session_id": session_id, "user_id": user_id,
                "title": "New Chat", "created_at": data["created_at"],
                "updated_at": data["created_at"], "last_message": ""}

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------
    def delete_conversation(self, user_id: str, conversation_id: str) -> None:
        path = self._session_path(user_id, conversation_id)
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass

    def delete_user(self, user_id: str) -> None:
        import shutil
        user_dir = self._user_dir(user_id)
        try:
            shutil.rmtree(user_dir, ignore_errors=True)
        except Exception:
            pass

    def _dict_to_msg(self, m: dict, user_id: str, conversation_id: str) -> ChatMessage:
        return ChatMessage(
            message_id=m.get("message_id", ""),
            user_id=user_id,
            conversation_id=conversation_id,
            role=m.get("role", ""),
            content=m.get("content", ""),
            created_at=m.get("created_at", 0.0),
            sequence_number=m.get("sequence_number", 0),
        )
