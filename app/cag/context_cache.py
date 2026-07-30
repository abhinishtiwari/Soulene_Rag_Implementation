"""Conversation context cache - the working set for the current conversation.

Holds the most recent 50-100 messages per conversation in memory for instant
access (no DB round-trip on the hot path). This is a CACHE, not the archive:
the complete transcript lives in the chat archive (Layer 1).

What gets sent to the model is a smaller slice (`prompt_window`, default 20),
plus an optional rolling summary of what fell out of that window.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

from app.types import Turn


@dataclass
class ConversationState:
    turns: Deque[Turn] = field(default_factory=deque)
    summary: str = ""
    counters: Dict[str, int] = field(default_factory=dict)
    dropped: int = 0


class ContextCache:
    def __init__(self, cache_size: int = 100, prompt_window: int = 20):
        self.cache_size = max(10, cache_size)
        self.prompt_window = max(4, prompt_window)
        self._conversations: Dict[str, ConversationState] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    def _state(self, conversation_id: str) -> ConversationState:
        st = self._conversations.get(conversation_id)
        if st is None:
            st = ConversationState(turns=deque(maxlen=self.cache_size))
            self._conversations[conversation_id] = st
        return st

    def append(self, conversation_id: str, role: str, content: str) -> None:
        if not content:
            return
        with self._lock:
            st = self._state(conversation_id)
            if len(st.turns) == st.turns.maxlen:
                st.dropped += 1
            st.turns.append(Turn(role=role, content=content))

    def prime(self, conversation_id: str, turns: List[Turn]) -> None:
        """Warm the cache from the archive (e.g. after a restart)."""
        with self._lock:
            st = self._state(conversation_id)
            if st.turns:
                return
            for t in turns[-self.cache_size:]:
                st.turns.append(t)

    def recent(self, conversation_id: str, limit: Optional[int] = None) -> List[Turn]:
        with self._lock:
            st = self._state(conversation_id)
            turns = list(st.turns)
        n = limit or self.prompt_window
        return turns[-n:]

    def all_cached(self, conversation_id: str) -> List[Turn]:
        with self._lock:
            return list(self._state(conversation_id).turns)

    def formatted_window(self, conversation_id: str, limit: Optional[int] = None) -> str:
        turns = self.recent(conversation_id, limit)
        if not turns:
            return "No earlier conversation."
        lines = []
        for t in turns:
            speaker = "User" if t.role == "user" else "Soulene"
            lines.append(f"{speaker}: {t.content}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Rolling summary (for context that scrolled out of the prompt window)
    # ------------------------------------------------------------------
    def summary(self, conversation_id: str) -> str:
        with self._lock:
            return self._state(conversation_id).summary

    def set_summary(self, conversation_id: str, summary: str) -> None:
        with self._lock:
            self._state(conversation_id).summary = (summary or "").strip()

    def needs_summary(self, conversation_id: str) -> bool:
        """True when messages have scrolled past the prompt window."""
        with self._lock:
            st = self._state(conversation_id)
            return len(st.turns) > self.prompt_window or st.dropped > 0

    def overflow_turns(self, conversation_id: str) -> List[Turn]:
        """Cached turns that sit outside the prompt window."""
        with self._lock:
            turns = list(self._state(conversation_id).turns)
        if len(turns) <= self.prompt_window:
            return []
        return turns[:-self.prompt_window]

    # ------------------------------------------------------------------
    # Behaviour counters (repeated injection / off-topic escalation)
    # ------------------------------------------------------------------
    def bump(self, conversation_id: str, key: str) -> int:
        with self._lock:
            st = self._state(conversation_id)
            st.counters[key] = st.counters.get(key, 0) + 1
            return st.counters[key]

    def counter(self, conversation_id: str, key: str) -> int:
        with self._lock:
            return self._state(conversation_id).counters.get(key, 0)

    def clear(self, conversation_id: str) -> None:
        with self._lock:
            self._conversations.pop(conversation_id, None)

    def stats(self) -> dict:
        with self._lock:
            return {
                "conversations_cached": len(self._conversations),
                "cache_size": self.cache_size,
                "prompt_window": self.prompt_window,
                "total_cached_turns": sum(len(s.turns) for s in self._conversations.values()),
            }
