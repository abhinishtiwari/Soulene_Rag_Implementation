"""Long-term, per-user memory — SEPARATE from the raw chat archive.

- Stores at most ~50 useful memories per user (name, stable preferences, ongoing
  context, confirmed relevant info).
- Extraction is deterministic and conservative (no LLM); we only keep clearly
  stable, useful facts, not every message.
- Retrieval returns 3–8 relevant memories for the current message, or nothing
  when nothing is relevant. Never dumps all memories into the prompt.
- Everything is scoped by user_id (isolation).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional

from app.types import UserMemory

_MAX_MEMORIES = 50
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "about", "what",
    "when", "your", "you", "are", "was", "were", "im", "me", "my", "to", "of",
    "in", "is", "it", "a", "an", "i", "feel", "feeling", "today", "just",
}

# Conservative extraction patterns for STABLE, user-beneficial facts only.
_NAME = re.compile(r"\b(?:my name is|call me|i am|i'?m|mera naam|mujhe log bulate hain)\s+([a-z][a-z '\-]{1,30})", re.I)
_PREF = re.compile(r"\b(i (?:like|love|enjoy|prefer|hate|dislike|can'?t stand)\s+[a-z].{2,40})", re.I)
_CONTEXT = re.compile(
    r"\b(i (?:work as|study|am studying|have (?:exams?|an interview|a deadline)|live in|am a)\s+[a-z].{2,50})",
    re.I,
)
_RELATION = re.compile(
    r"\b((?:my )?(?:mother|father|mom|dad|sister|brother|wife|husband|partner|girlfriend|boyfriend|friend|boss)\b.{0,50})",
    re.I,
)
# --- wellness-specific, high-value memory categories ---
_TRIGGER = re.compile(
    r"\b((?:my )?(?:anxiety|stress|panic|overthinking)\s+(?:is )?(?:triggered by|starts when|gets worse when|comes from)\s+[a-z].{2,60}"
    r"|i (?:get|feel) (?:anxious|stressed|panicky|overwhelmed) (?:when|before|around|during)\s+[a-z].{2,60})",
    re.I,
)
_COPING = re.compile(
    r"\b((?:deep breathing|journaling|walking|running|music|meditation|yoga|praying|painting|talking to \w+)"
    r"\s+(?:really )?(?:helps?|helped|works?|worked|calms? me)[a-z ]{0,30}"
    r"|i feel better (?:when|after) i\s+[a-z].{2,50})",
    re.I,
)
_SLEEP = re.compile(
    r"\b(i (?:sleep|can'?t sleep|barely sleep|hardly sleep)\s*[a-z0-9].{2,50}"
    r"|i (?:go to bed|wake up)\s+(?:at|around)\s+[a-z0-9].{1,25}"
    r"|my sleep (?:is|has been)\s+[a-z].{2,40})",
    re.I,
)
_GOAL = re.compile(
    r"\b(i want to\s+(?:be|feel|get|start|stop|build|improve|become)\s+[a-z].{2,55}"
    r"|my goal is\s+[a-z].{2,55}"
    r"|i'?m (?:trying|working) to\s+[a-z].{2,55})",
    re.I,
)
_ACHIEVEMENT = re.compile(
    r"\b(i (?:finally|just)\s+(?:did|got|passed|finished|completed|achieved|won|started|managed|submitted|\w+ed)\b.{0,50}"
    r"|i (?:got|passed|finished|completed|achieved|won)\s+(?:my|the|a|an)\s+[a-z].{2,50})",
    re.I,
)
_STYLE = re.compile(
    r"\b((?:please )?(?:don'?t|do not) (?:give me advice|tell me what to do|ask too many questions)[a-z ]{0,30}"
    r"|i (?:just )?(?:want|prefer) (?:to vent|you to listen|short (?:replies|answers)|advice)[a-z ]{0,30})",
    re.I,
)
# Negations that may contradict a stored memory (trigger gentle clarify, not silent reuse).
_NEGATION = re.compile(r"\b(don'?t|do not|no longer|not anymore|isn'?t|used to but|stopped)\b", re.I)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9']+", text.lower()) if len(t) > 2 and t not in _STOPWORDS}


class LongTermMemory:
    def __init__(self, storage_dir: Optional[Path] = None):
        self._store: Dict[str, List[UserMemory]] = {}
        self._lock = Lock()
        self._dir = storage_dir
        if storage_dir is not None:
            storage_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def observe(self, user_id: str, message: str) -> None:
        """Extract and persist stable facts from a user message (conservative)."""
        candidates: List[UserMemory] = []
        now = time.time()

        m = _NAME.search(message)
        if m:
            # Take the first 1–2 words and drop trailing filler ("by the way", etc.).
            raw = m.group(1).strip().split()
            filler = {"by", "the", "way", "and", "but", "so", "just", "actually", "here", "now"}
            name_parts = []
            for w in raw[:2]:
                if w.lower() in filler:
                    break
                name_parts.append(w)
            name = " ".join(name_parts).strip(" '-")
            if name and name.lower() not in filler:
                candidates.append(UserMemory(text=f"User's name: {name}", kind="name",
                                             created_at=now, updated_at=now, weight=2.0))
        # Higher-weight wellness categories are checked with the general ones.
        for pat, kind, weight in (
            (_TRIGGER, "trigger", 2.0),
            (_COPING, "coping_strategy", 2.0),
            (_GOAL, "goal", 1.6),
            (_SLEEP, "sleep", 1.4),
            (_STYLE, "communication_style", 1.8),
            (_ACHIEVEMENT, "achievement", 1.2),
            (_PREF, "preference", 1.0),
            (_CONTEXT, "context", 1.0),
            (_RELATION, "relationship", 1.0),
        ):
            for match in pat.finditer(message):
                text = re.sub(r"\s+", " ", match.group(1)).strip()
                if 4 <= len(text) <= 90:
                    candidates.append(UserMemory(text=text, kind=kind, created_at=now,
                                                 updated_at=now, weight=weight))
        if not candidates:
            return

        with self._lock:
            mem = self._load(user_id)
            for cand in candidates:
                self._upsert(mem, cand)
            # Cap to the most recently updated / highest-weight memories.
            mem.sort(key=lambda x: (x.weight, x.updated_at), reverse=True)
            del mem[_MAX_MEMORIES:]
            self._store[user_id] = mem
            self._persist(user_id, mem)

    def retrieve(self, user_id: str, message: str, k_min: int = 3, k_max: int = 8) -> List[UserMemory]:
        with self._lock:
            mem = list(self._load(user_id))
        if not mem:
            return []
        q = _tokens(message)
        if not q:
            return []
        scored = []
        for item in mem:
            overlap = len(q & _tokens(item.text))
            if overlap > 0 or item.kind == "name":
                score = overlap + (0.5 if item.kind == "name" else 0) + 0.1 * item.weight
                scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        selected = [item for s, item in scored if s > 0]
        if not selected:
            return []
        return selected[:max(k_min, min(k_max, len(selected)))]

    def contradiction_topics(self, user_id: str, message: str) -> List[str]:
        """Return memory texts that the current message may be negating/correcting."""
        if not _NEGATION.search(message):
            return []
        with self._lock:
            mem = list(self._load(user_id))
        q = _tokens(message)
        hits = []
        for item in mem:
            if len(q & _tokens(item.text)) >= 1 and item.kind != "name":
                hits.append(item.text)
        return hits[:3]

    def forget_user(self, user_id: str) -> None:
        with self._lock:
            self._store.pop(user_id, None)
            if self._dir is not None:
                p = self._path(user_id)
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass

    # ------------------------------------------------------------------
    def _upsert(self, mem: List[UserMemory], cand: UserMemory) -> None:
        cand_tokens = _tokens(cand.text)
        for existing in mem:
            # Same kind + strong overlap => update in place (dedupe).
            if existing.kind == cand.kind and len(cand_tokens & _tokens(existing.text)) >= max(1, len(cand_tokens) // 2):
                existing.text = cand.text
                existing.updated_at = cand.updated_at
                existing.weight = min(3.0, existing.weight + 0.2)
                return
        mem.append(cand)

    def _path(self, user_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in user_id)
        return self._dir / f"{safe}.json"  # type: ignore[union-attr]

    def _load(self, user_id: str) -> List[UserMemory]:
        if user_id in self._store:
            return self._store[user_id]
        items: List[UserMemory] = []
        if self._dir is not None:
            p = self._path(user_id)
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    items = [UserMemory(**d) for d in data]
                except Exception:
                    items = []
        self._store[user_id] = items
        return items

    def _persist(self, user_id: str, mem: List[UserMemory]) -> None:
        if self._dir is None:
            return
        try:
            payload = [vars(m) for m in mem]
            self._path(user_id).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
