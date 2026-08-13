"""Conversation context cache - the working set for the current conversation.

Holds the most recent 50-100 messages per conversation in memory for instant
access (no DB round-trip on the hot path). This is a CACHE, not the archive:
the complete transcript lives in the chat archive (Layer 1).

What gets sent to the model is a smaller slice (`prompt_window`, default 20),
plus an optional rolling summary of what fell out of that window.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

from app.types import Turn


@dataclass
class ConversationState:
    turns: Deque[Turn] = field(default_factory=deque)
    summary: str = ""
    counters: Dict[str, int] = field(default_factory=dict)
    safety_state: Dict[str, object] = field(default_factory=dict)
    dropped: int = 0
    # Total turns appended when the rolling summary was last (re)generated.
    # Used to regenerate only after enough NEW turns have overflowed, instead
    # of on every turn (which cost one LLM call per turn in long chats).
    summarized_at: int = 0
    appended_total: int = 0


@dataclass
class CrossSessionState:
    """Cached view of a user's OTHER sessions.

    The last few complete sessions are kept verbatim for fast recall; older
    sessions are kept as digests only, so relevance can be scored without
    loading long transcripts on the hot path. MongoDB stays the source of truth.
    """

    recent: List[dict] = field(default_factory=list)   # newest-first, with messages
    digests: List[dict] = field(default_factory=list)  # {session_id, text}
    fetched_at: float = 0.0


class ContextCache:
    def __init__(self, cache_size: int = 100, prompt_window: int = 20,
                 cross_session_ttl: float = 300.0):
        self.cache_size = max(10, cache_size)
        self.prompt_window = max(4, prompt_window)
        self.cross_session_ttl = cross_session_ttl
        self._conversations: Dict[str, ConversationState] = {}
        self._cross: Dict[str, CrossSessionState] = {}
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
            st.appended_total += 1

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
            st = self._state(conversation_id)
            st.summary = (summary or "").strip()
            # Mark the point at which the summary reflects the transcript, so it
            # is not regenerated again until enough new turns have overflowed.
            st.summarized_at = st.appended_total

    def safety_state(self, conversation_id: str) -> Dict[str, object]:
        with self._lock:
            return dict(self._state(conversation_id).safety_state)

    def set_safety_state(self, conversation_id: str, state: Dict[str, object]) -> None:
        with self._lock:
            self._state(conversation_id).safety_state = dict(state or {})

    # Regenerate the rolling summary only after this many NEW turns have been
    # appended since the last summary. Keeps a long conversation from spending
    # one LLM call per turn while still refreshing often enough for continuity.
    _SUMMARY_REFRESH_STEP = 8

    def needs_summary(self, conversation_id: str) -> bool:
        """True when the window has overflowed AND enough new turns have arrived
        since the summary was last generated to justify regenerating it."""
        with self._lock:
            st = self._state(conversation_id)
            overflowed = len(st.turns) > self.prompt_window or st.dropped > 0
            if not overflowed:
                return False
            # Always allow the first summary; afterwards throttle by step.
            if not st.summary:
                return True
            return (st.appended_total - st.summarized_at) >= self._SUMMARY_REFRESH_STEP

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

    # ISS-13 FIX: Methods to persist/restore counters across worker restarts.
    def get_counters(self, conversation_id: str) -> Dict[str, int]:
        with self._lock:
            return dict(self._state(conversation_id).counters)

    def restore_counters(self, conversation_id: str, counters: Dict[str, int]) -> None:
        """Restore counters from persisted state (e.g. after restart)."""
        if not counters or not isinstance(counters, dict):
            return
        with self._lock:
            st = self._state(conversation_id)
            if not st.counters:  # Only restore if not already populated
                st.counters = {k: int(v) for k, v in counters.items()
                               if isinstance(v, (int, float))}

    # ------------------------------------------------------------------
    # Cross-session cache (per user, TTL-bounded)
    # ------------------------------------------------------------------
    def cross_session(self, user_key: str) -> Optional[CrossSessionState]:
        """Return the cached cross-session view, or None when stale/absent."""
        with self._lock:
            st = self._cross.get(user_key)
        if st is None:
            return None
        if (time.time() - st.fetched_at) > self.cross_session_ttl:
            return None
        return st

    def set_cross_session(self, user_key: str, recent: List[dict],
                          digests: List[dict]) -> None:
        with self._lock:
            self._cross[user_key] = CrossSessionState(
                recent=list(recent or []), digests=list(digests or []),
                fetched_at=time.time())

    def invalidate_cross_session(self, user_key: str) -> None:
        with self._lock:
            self._cross.pop(user_key, None)

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
