"""Response cache - reuse prior answers to avoid redundant LLM calls.

IMPORTANT SCOPING: only FACTUAL / knowledge answers are cached. Emotional-support
replies are never cached, because the assistant must never repeat itself in an
emotional conversation (response-variety requirement).

Lookup is exact-key first, then a fast token-set (Jaccard) near-match. No
embeddings, so lookup is sub-millisecond.
"""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

_FILLER = {
    "please", "hey", "hi", "hello", "can", "you", "tell", "me", "what", "whats",
    "is", "the", "a", "an", "of", "for", "to", "do", "does", "about", "i", "want",
    "know", "would", "like", "could", "give", "us", "your", "there", "any", "and",
}


def _normalize(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9\s₹]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _keyset(text: str) -> Set[str]:
    return {t for t in _normalize(text).split() if t not in _FILLER and len(t) > 1}


@dataclass
class CacheEntry:
    answer: str
    keyset: Set[str]
    created_at: float
    hits: int = 0
    sources: Optional[List[str]] = None


class ResponseCache:
    def __init__(self, max_entries: int = 500, ttl_seconds: float = 6 * 3600,
                 similarity_threshold: float = 0.82):
        self._max = max_entries
        self._ttl = ttl_seconds
        self._threshold = similarity_threshold
        self._entries: "OrderedDict[str, CacheEntry]" = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    def _fresh(self, entry: CacheEntry) -> bool:
        return (time.time() - entry.created_at) <= self._ttl

    def get(self, question: str, *, scope: str = "knowledge") -> Optional[CacheEntry]:
        key = f"{scope}::{_normalize(question)}"
        qset = _keyset(question)
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None and self._fresh(entry):
                entry.hits += 1
                self._entries.move_to_end(key)
                self._hits += 1
                return entry
            if entry is not None:
                self._entries.pop(key, None)

            # Near-match within the same scope.
            if qset:
                best, best_score, best_key = None, 0.0, None
                for k, e in self._entries.items():
                    if not k.startswith(f"{scope}::") or not self._fresh(e) or not e.keyset:
                        continue
                    inter = len(qset & e.keyset)
                    if not inter:
                        continue
                    score = inter / len(qset | e.keyset)
                    if score > best_score:
                        best, best_score, best_key = e, score, k
                if best is not None and best_score >= self._threshold:
                    best.hits += 1
                    self._entries.move_to_end(best_key)
                    self._hits += 1
                    return best
            self._misses += 1
            return None

    def put(self, question: str, answer: str, *, scope: str = "knowledge",
            sources: Optional[List[str]] = None) -> None:
        if not question.strip() or not answer.strip():
            return
        key = f"{scope}::{_normalize(question)}"
        with self._lock:
            self._entries[key] = CacheEntry(
                answer=answer, keyset=_keyset(question),
                created_at=time.time(), sources=sources or [],
            )
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)

    def invalidate_scope(self, scope: str) -> int:
        """Drop all entries for a scope (e.g. after documents change)."""
        with self._lock:
            doomed = [k for k in self._entries if k.startswith(f"{scope}::")]
            for k in doomed:
                self._entries.pop(k, None)
            return len(doomed)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "entries": len(self._entries),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 3) if total else 0.0,
            }
