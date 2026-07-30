"""CAG engine - orchestrates the cache layers before any LLM call.

Lookup order for a knowledge question:

    1. Response cache   -> answer reused, ZERO LLM calls
    2. Knowledge cache  -> context injected, ONE LLM call
    3. (no knowledge)   -> honest "I don't have that" guidance, ONE LLM call

For emotional / conversational turns the response cache is intentionally skipped
so replies always stay fresh and varied.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from app.cag.context_cache import ContextCache
from app.cag.knowledge_cache import KnowledgeCache
from app.cag.response_cache import CacheEntry, ResponseCache


@dataclass
class CAGLookup:
    """Result of consulting the cache layers."""

    cached_answer: Optional[str] = None       # set -> skip the LLM entirely
    knowledge_context: str = ""               # set -> inject into the prompt
    sources: List[str] = field(default_factory=list)
    cache_hit: bool = False                   # response-cache hit
    knowledge_hit: bool = False               # knowledge-cache produced context
    full_preload: bool = False                # whole corpus injected


class CAGEngine:
    def __init__(self, knowledge_dir: Path, cache_dir: Path, *,
                 token_budget: int = 12000,
                 context_cache_size: int = 100,
                 prompt_window: int = 20,
                 response_cache_entries: int = 500):
        self.knowledge = KnowledgeCache(knowledge_dir, cache_dir, token_budget=token_budget)
        self.responses = ResponseCache(max_entries=response_cache_entries)
        self.context = ContextCache(cache_size=context_cache_size, prompt_window=prompt_window)
        self._lock = threading.RLock()
        self._refreshing = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def warm(self) -> dict:
        """Load the persisted cache, building it only if missing/stale."""
        loaded = self.knowledge.load()
        report = self.knowledge.refresh(force=not loaded and self.knowledge.is_empty())
        return report

    def refresh_documents(self, *, force: bool = False) -> dict:
        """Reprocess changed documents and invalidate stale cached answers."""
        report = self.knowledge.refresh(force=force)
        if report.get("status") != "unchanged":
            # Document knowledge changed -> previously cached factual answers are stale.
            self.responses.invalidate_scope("knowledge")
        return report

    def refresh_in_background(self, on_done=None) -> bool:
        with self._lock:
            if self._refreshing:
                return False
            self._refreshing = True

        def worker():
            try:
                report = self.refresh_documents()
                if on_done:
                    on_done(report)
            finally:
                with self._lock:
                    self._refreshing = False

        threading.Thread(target=worker, daemon=True).start()
        return True

    def remove_document(self, name: str) -> bool:
        removed = self.knowledge.remove_document(name)
        if removed:
            self.responses.invalidate_scope("knowledge")
        return removed

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
    def lookup(self, question: str, *, needs_knowledge: bool,
               knowledge_type: Optional[str] = None,
               allow_response_cache: bool = True) -> CAGLookup:
        result = CAGLookup(full_preload=self.knowledge.fits_in_budget)
        if not needs_knowledge:
            return result

        # 1) Response cache - avoids the LLM completely.
        if allow_response_cache:
            hit: Optional[CacheEntry] = self.responses.get(question, scope="knowledge")
            if hit is not None:
                result.cached_answer = hit.answer
                result.sources = list(hit.sources or [])
                result.cache_hit = True
                return result

        # 2) Knowledge cache -> context for a single LLM call.
        context, sources = self.knowledge.build_context(
            question, knowledge_type=knowledge_type)
        result.knowledge_context = context
        result.sources = sources
        result.knowledge_hit = bool(context)
        return result

    def store_answer(self, question: str, answer: str, sources: Optional[List[str]] = None) -> None:
        """Cache a FACTUAL answer for reuse. Never call this for emotional replies."""
        self.responses.put(question, answer, scope="knowledge", sources=sources)

    # ------------------------------------------------------------------
    def stats(self) -> dict:
        return {
            "knowledge_cache": self.knowledge.stats(),
            "response_cache": self.responses.stats(),
            "context_cache": self.context.stats(),
            "refreshing": self._refreshing,
        }
