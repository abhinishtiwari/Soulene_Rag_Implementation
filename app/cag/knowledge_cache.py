"""Layer 4 - CAG Knowledge Cache.

The primary retrieval mechanism. Uploaded documents are preprocessed ONCE into
structured sections, persisted, and held in memory. At request time there is no
vector search and no embedding call:

  * If the whole corpus fits the token budget -> inject ALL of it (true CAG preload).
  * If it exceeds the budget -> narrow with a fast in-memory lexical index, then inject.

Change detection is per-document (content hash), so only edited/new documents are
reprocessed; unchanged documents are reused straight from cache.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.cag.document_processor import SUPPORTED_EXTENSIONS, Section, process_document

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "has", "are", "was",
    "were", "you", "your", "our", "its", "it's", "what", "which", "who", "how", "why",
    "when", "where", "does", "did", "can", "will", "would", "should", "there", "their",
    "they", "them", "then", "than", "into", "onto", "about", "also", "any", "all",
    "but", "not", "out", "own", "per", "via", "such", "some", "more", "most", "each",
    "i", "a", "an", "of", "to", "in", "is", "on", "at", "as", "be", "by", "or", "if",
    "do", "me", "my", "we", "us", "so", "no", "up",
}


def _tokens(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9']+", (text or "").lower())
            if len(t) > 1 and t not in _STOPWORDS]


def approx_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token) - avoids a tokenizer dependency."""
    return max(1, len(text or "") // 4)


@dataclass
class CachedSection:
    section_id: int
    heading: str
    text: str
    document: str
    knowledge_type: str
    metadata: Dict[str, object] = field(default_factory=dict)

    def rendered(self) -> str:
        head = self.heading.strip()
        label = f"[{self.document}]"
        if head:
            return f"{label} {head}\n{self.text}".strip()
        return f"{label}\n{self.text}".strip()


class KnowledgeCache:
    """In-memory, persisted knowledge cache with per-document change detection."""

    CACHE_FILENAME = "knowledge_cache.json"

    def __init__(self, knowledge_dir: Path, cache_dir: Path,
                 token_budget: int = 12000):
        self.knowledge_dir = Path(knowledge_dir)
        self.cache_dir = Path(cache_dir)
        self.token_budget = token_budget
        self._lock = threading.RLock()

        self._sections: List[CachedSection] = []
        self._index: Dict[str, List[int]] = {}
        self._doc_hashes: Dict[str, str] = {}
        self._doc_meta: Dict[str, dict] = {}
        self._total_tokens = 0
        self._built_at: float = 0.0
        # Rendered full-corpus context, computed once and reused.
        self._full_context: Optional[str] = None

    # ------------------------------------------------------------------
    # Properties / stats
    # ------------------------------------------------------------------
    @property
    def section_count(self) -> int:
        return len(self._sections)

    @property
    def total_tokens(self) -> int:
        return self._total_tokens

    @property
    def fits_in_budget(self) -> bool:
        return self._total_tokens <= self.token_budget

    def is_empty(self) -> bool:
        return not self._sections

    def documents(self) -> List[dict]:
        with self._lock:
            return [dict(v) for v in self._doc_meta.values()]

    def stats(self) -> dict:
        with self._lock:
            return {
                "documents": len(self._doc_hashes),
                "sections": len(self._sections),
                "approx_tokens": self._total_tokens,
                "token_budget": self.token_budget,
                "full_preload": self.fits_in_budget,
                "built_at": self._built_at,
                "index_terms": len(self._index),
            }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _cache_path(self) -> Path:
        return self.cache_dir / self.CACHE_FILENAME

    def load(self) -> bool:
        """Load the persisted cache. Returns True when a cache was loaded."""
        path = self._cache_path()
        if not path.exists():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return False
        with self._lock:
            self._sections = [
                CachedSection(
                    section_id=s["section_id"], heading=s.get("heading", ""),
                    text=s.get("text", ""), document=s.get("document", ""),
                    knowledge_type=s.get("knowledge_type", "general"),
                    metadata=s.get("metadata", {}),
                )
                for s in payload.get("sections", [])
            ]
            self._doc_hashes = payload.get("doc_hashes", {})
            self._doc_meta = payload.get("doc_meta", {})
            self._built_at = payload.get("built_at", 0.0)
            self._reindex()
        return True

    def save(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            payload = {
                "built_at": self._built_at,
                "doc_hashes": self._doc_hashes,
                "doc_meta": self._doc_meta,
                "sections": [
                    {
                        "section_id": s.section_id, "heading": s.heading, "text": s.text,
                        "document": s.document, "knowledge_type": s.knowledge_type,
                        "metadata": s.metadata,
                    }
                    for s in self._sections
                ],
            }
        tmp = self._cache_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._cache_path())

    # ------------------------------------------------------------------
    # Build / refresh
    # ------------------------------------------------------------------
    def _scan(self) -> Dict[str, Tuple[Path, str, str]]:
        """Return {document_name: (path, content_hash, knowledge_type)}."""
        found: Dict[str, Tuple[Path, str, str]] = {}
        if not self.knowledge_dir.exists():
            return found
        for path in sorted(self.knowledge_dir.rglob("*")):
            if not (path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS):
                continue
            h = hashlib.sha256()
            try:
                with path.open("rb") as f:
                    for block in iter(lambda: f.read(65536), b""):
                        h.update(block)
            except OSError:
                continue
            try:
                knowledge_type = path.relative_to(self.knowledge_dir).parts[0]
                if knowledge_type == path.name:
                    knowledge_type = "general"
            except Exception:
                knowledge_type = "general"
            found[path.name] = (path, h.hexdigest(), knowledge_type)
        return found

    def refresh(self, *, force: bool = False) -> dict:
        """Rebuild only what changed. Returns a report dict."""
        found = self._scan()
        with self._lock:
            previous = dict(self._doc_hashes)

        new_docs = [d for d in found if d not in previous]
        changed = [d for d in found if d in previous and previous[d] != found[d][1]]
        removed = [d for d in previous if d not in found]
        unchanged = [d for d in found if d in previous and previous[d] == found[d][1]]

        if not force and not (new_docs or changed or removed) and not self.is_empty():
            return {"status": "unchanged", "new": 0, "changed": 0, "removed": 0,
                    "unchanged": len(unchanged), **self.stats()}

        with self._lock:
            # Keep sections of unchanged documents (no reprocessing).
            keep = set(unchanged) if not force else set()
            retained = [s for s in self._sections if s.document in keep]
            reprocess = [d for d in found if d not in keep]

            new_sections: List[Section] = []
            doc_meta = {d: self._doc_meta[d] for d in keep if d in self._doc_meta}
            for doc in reprocess:
                path, content_hash, knowledge_type = found[doc]
                secs = process_document(path, knowledge_type)
                new_sections.extend(secs)
                doc_meta[doc] = {
                    "document": doc,
                    "knowledge_type": knowledge_type,
                    "content_hash": content_hash,
                    "version": content_hash[:8],
                    "sections": len(secs),
                    "format": path.suffix.lstrip(".").lower(),
                    "updated_at": time.time(),
                }

            combined = retained + [
                CachedSection(section_id=0, heading=s.heading, text=s.text,
                              document=str(s.metadata.get("document", "")),
                              knowledge_type=str(s.metadata.get("knowledge_type", "general")),
                              metadata=s.metadata)
                for s in new_sections
            ]
            # Reassign stable ids.
            for i, sec in enumerate(combined):
                sec.section_id = i
            self._sections = combined
            self._doc_hashes = {d: found[d][1] for d in found}
            self._doc_meta = doc_meta
            self._built_at = time.time()
            self._reindex()

        self.save()
        return {"status": "rebuilt", "new": len(new_docs), "changed": len(changed),
                "removed": len(removed), "unchanged": len(unchanged), **self.stats()}

    def remove_document(self, document_name: str) -> bool:
        """Drop a document's sections from the cache (and its file record)."""
        with self._lock:
            if document_name not in self._doc_hashes:
                return False
            self._sections = [s for s in self._sections if s.document != document_name]
            for i, sec in enumerate(self._sections):
                sec.section_id = i
            self._doc_hashes.pop(document_name, None)
            self._doc_meta.pop(document_name, None)
            self._reindex()
        self.save()
        return True

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------
    def _reindex(self) -> None:
        """Build the lexical index + cached full-corpus rendering."""
        index: Dict[str, List[int]] = {}
        total = 0
        for sec in self._sections:
            total += approx_tokens(sec.heading) + approx_tokens(sec.text)
            seen = set()
            # Heading terms count double (weighted at query time).
            for tok in _tokens(sec.heading) + _tokens(sec.text):
                if tok in seen:
                    continue
                seen.add(tok)
                index.setdefault(tok, []).append(sec.section_id)
        self._index = index
        self._total_tokens = total
        self._full_context = None  # invalidate

    # ------------------------------------------------------------------
    # Retrieval (cache lookup - NO embeddings, NO vector search)
    # ------------------------------------------------------------------
    def _render_full(self, knowledge_type: Optional[str] = None) -> str:
        if knowledge_type is None and self._full_context is not None:
            return self._full_context
        parts = [
            s.rendered() for s in self._sections
            if knowledge_type is None or s.knowledge_type == knowledge_type
        ]
        rendered = "\n\n".join(parts)
        if knowledge_type is None:
            self._full_context = rendered
        return rendered

    def search_sections(self, query: str, limit: int = 12,
                        knowledge_type: Optional[str] = None) -> List[CachedSection]:
        """Fast lexical narrowing over the in-memory index (BM25-lite)."""
        q = _tokens(query)
        if not q or not self._sections:
            return []
        with self._lock:
            n_docs = max(1, len(self._sections))
            scores: Dict[int, float] = {}
            for tok in set(q):
                postings = self._index.get(tok)
                if not postings:
                    continue
                idf = math.log(1 + n_docs / len(postings))
                for sid in postings:
                    scores[sid] = scores.get(sid, 0.0) + idf
            if not scores:
                return []
            # Heading matches get a boost.
            results = []
            for sid, score in scores.items():
                sec = self._sections[sid]
                if knowledge_type and sec.knowledge_type != knowledge_type:
                    continue
                head_tokens = set(_tokens(sec.heading))
                boost = 1.0 + 0.5 * len(head_tokens & set(q))
                results.append((score * boost, sec))
            results.sort(key=lambda x: x[0], reverse=True)
            return [sec for _, sec in results[:limit]]

    def build_context(self, query: str = "", *,
                      knowledge_type: Optional[str] = None,
                      token_budget: Optional[int] = None) -> Tuple[str, List[str]]:
        """Return (context_text, source_documents).

        Full preload when the corpus fits the budget; otherwise lexically narrowed.
        """
        budget = token_budget or self.token_budget
        with self._lock:
            if self.is_empty():
                return "", []
            if self._total_tokens <= budget:
                text = self._render_full(knowledge_type)
                docs = sorted({
                    s.document for s in self._sections
                    if knowledge_type is None or s.knowledge_type == knowledge_type
                })
                return text, docs

        # Corpus larger than budget -> narrow, still no vector search.
        picked = self.search_sections(query, limit=40, knowledge_type=knowledge_type)
        if not picked:
            picked = self._sections[:20]
        out, used, docs = [], 0, set()
        for sec in picked:
            block = sec.rendered()
            cost = approx_tokens(block)
            if used + cost > budget:
                continue
            out.append(block)
            used += cost
            docs.add(sec.document)
        return "\n\n".join(out), sorted(docs)
