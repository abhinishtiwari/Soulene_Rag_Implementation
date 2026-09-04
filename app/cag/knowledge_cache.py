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
import logging
import math
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from app.cag.document_processor import SUPPORTED_EXTENSIONS, Section, process_document
from app.safety.guardrails import Guardrails

log = logging.getLogger("soulene.cag")

# Stateless (compiled regexes only), so one shared instance is enough.
_GUARDRAILS = Guardrails()

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


# ISS-15 FIX: Domain-specific synonym map for bridging vocabulary gaps in knowledge retrieval.
_KNOWLEDGE_SYNONYMS: Dict[str, List[str]] = {
    "counselor": ["mentor", "therapist", "guide", "counseling", "mentorship"],
    "counseling": ["mentorship", "therapy", "guidance", "counselor"],
    "mentor": ["counselor", "guide", "coach", "mentorship"],
    "mentorship": ["counseling", "coaching", "guidance", "mentor"],
    "therapy": ["counseling", "treatment", "therapist"],
    "therapist": ["counselor", "mentor", "therapy"],
    "pricing": ["cost", "price", "plan", "subscription", "fee"],
    "cost": ["pricing", "price", "fee", "subscription"],
    "subscription": ["plan", "pricing", "membership", "tier"],
    "plan": ["subscription", "pricing", "tier", "membership"],
    "exercise": ["technique", "practice", "activity", "routine"],
    "technique": ["exercise", "method", "practice", "strategy"],
    "breathing": ["breath", "inhale", "exhale", "pranayama"],
    "meditation": ["mindfulness", "calm", "relaxation"],
    "mindfulness": ["meditation", "awareness", "calm"],
    "anxiety": ["anxious", "worry", "nervous", "panic", "stress"],
    "stress": ["anxiety", "pressure", "overwhelm", "tension"],
    "depression": ["depressed", "sadness", "low", "mood"],
    "sleep": ["insomnia", "rest", "bedtime"],
    "insomnia": ["sleep", "sleepless", "awake"],
}


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
    # v2 keys documents by canonical relative path instead of basename. An older
    # payload is rejected on load so it is rebuilt rather than silently mixing
    # two identity schemes (which is what allowed same-name documents to collide).
    CACHE_VERSION = 2

    def __init__(self, knowledge_dir: Path, cache_dir: Path,
                 token_budget: int = 12000,
                 include_types: Optional[Iterable[str]] = None):
        self.knowledge_dir = Path(knowledge_dir)
        self.cache_dir = Path(cache_dir)
        self.token_budget = token_budget
        # Retrieval is scoped to these top-level knowledge folders. Documents in
        # any other folder (e.g. a large clinical `books/` reference library) are
        # left on disk but never indexed or retrieved, so they cannot bloat the
        # corpus past the preload budget or leak diagnostic/clinical framing into
        # a companion reply. None means "index everything" (legacy behaviour).
        self.include_types: Optional[set] = (
            {t.strip() for t in include_types if t and t.strip()}
            if include_types is not None else None)
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
    # Scope helpers
    # ------------------------------------------------------------------
    def _type_of(self, path: Path) -> str:
        """The knowledge_type for a file: its top-level folder under the root.

        A file placed directly in the root (no subfolder) is "general".
        """
        try:
            ktype = path.relative_to(self.knowledge_dir).parts[0]
            return "general" if ktype == path.name else ktype
        except Exception:
            return "general"

    def _is_included(self, path: Path) -> bool:
        """Whether a file is in scope for indexing/retrieval.

        When `include_types` is set, only files whose top-level folder is in that
        set are indexed; everything else is ignored (left on disk, never read).
        """
        if self.include_types is None:
            return True
        return self._type_of(path) in self.include_types

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

    def _migrate_payload(self, payload: dict) -> Optional[dict]:
        """Upgrade a basename-keyed (v1) payload to relative-path identity.

        Preprocessed sections are expensive (and some formats need optional
        dependencies), so a legacy cache is migrated rather than discarded. A
        basename that now matches several files is dropped instead of guessed,
        which lets refresh reprocess those documents under distinct keys.
        """
        if payload.get("cache_version") is not None:
            return None  # unknown future version: rebuild rather than guess
        by_basename: Dict[str, List[str]] = {}
        for path in self.knowledge_dir.rglob("*"):
            if (path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
                    and self._is_included(path)):
                by_basename.setdefault(path.name, []).append(self._relative_path(path))

        remap = {name: paths[0] for name, paths in by_basename.items()
                 if len(paths) == 1}
        migrated_hashes = {remap[name]: value
                           for name, value in (payload.get("doc_hashes") or {}).items()
                           if name in remap}
        migrated_meta = {}
        for name, meta in (payload.get("doc_meta") or {}).items():
            if name not in remap:
                continue
            entry = dict(meta or {})
            entry["document"] = remap[name]
            entry.setdefault("display_name", name)
            entry["relative_path"] = remap[name]
            migrated_meta[remap[name]] = entry
        migrated_sections = []
        for section in payload.get("sections") or []:
            name = section.get("document", "")
            if name not in remap:
                continue
            entry = dict(section)
            entry["document"] = remap[name]
            metadata = dict(entry.get("metadata") or {})
            metadata["document"] = remap[name]
            metadata.setdefault("display_name", name)
            entry["metadata"] = metadata
            migrated_sections.append(entry)

        return {
            "cache_version": self.CACHE_VERSION,
            "built_at": payload.get("built_at", 0.0),
            "doc_hashes": migrated_hashes,
            "doc_meta": migrated_meta,
            "sections": migrated_sections,
        }

    def load(self) -> bool:
        """Load the persisted cache. Returns True when a cache was loaded."""
        path = self._cache_path()
        if not path.exists():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return False
        if payload.get("cache_version") != self.CACHE_VERSION:
            payload = self._migrate_payload(payload)
            if payload is None:
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

    def _on_disk_is_newer(self, built_at: float) -> bool:
        """True when another writer already persisted a fresher build."""
        try:
            existing = json.loads(self._cache_path().read_text(encoding="utf-8"))
        except Exception:
            return False
        return float(existing.get("built_at") or 0.0) > float(built_at or 0.0)

    def save(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            payload = {
                "cache_version": self.CACHE_VERSION,
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
        # Never clobber a build that another worker persisted more recently.
        if self._on_disk_is_newer(payload["built_at"]):
            return
        # Unique staging file per writer: a shared fixed .tmp name let concurrent
        # workers overwrite each other's partial bytes or fail the replace.
        handle, staged = tempfile.mkstemp(
            dir=str(self.cache_dir), prefix=".knowledge_cache-", suffix=".tmp")
        staged_path = Path(staged)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False)
        except BaseException:
            staged_path.unlink(missing_ok=True)
            raise
        # Atomic publish: readers only ever see a complete cache. On Windows the
        # replace can transiently fail while another worker publishes, so retry
        # briefly and then yield: the cache is a rebuildable artifact and the
        # in-memory index is already correct, so losing this race is not an error.
        for attempt in range(5):
            try:
                os.replace(staged_path, self._cache_path())
                return
            except PermissionError:
                time.sleep(0.02 * (attempt + 1))
        staged_path.unlink(missing_ok=True)
        log.warning("knowledge cache publish skipped: another writer holds the file")

    # ------------------------------------------------------------------
    # Build / refresh
    # ------------------------------------------------------------------
    def _scan(self) -> Dict[str, Tuple[Path, str, str]]:
        """Return {relative_path: (path, content_hash, knowledge_type)}.

        Keyed by canonical relative path, not basename: two documents with the
        same filename in different folders are distinct documents and both must
        be indexed.
        """
        found: Dict[str, Tuple[Path, str, str]] = {}
        if not self.knowledge_dir.exists():
            return found
        for path in sorted(self.knowledge_dir.rglob("*")):
            if not (path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS):
                continue
            # Out-of-scope folders (e.g. the clinical `books/` library) are
            # skipped: left on disk, never indexed or retrieved.
            if not self._is_included(path):
                continue
            h = hashlib.sha256()
            try:
                with path.open("rb") as f:
                    for block in iter(lambda: f.read(65536), b""):
                        h.update(block)
            except OSError:
                continue
            found[self._relative_path(path)] = (path, h.hexdigest(), self._type_of(path))
        return found

    def refresh(self, *, force: bool = False) -> dict:
        """Rebuild only what changed. Returns a report dict."""
        found = self._scan()
        with self._lock:
            previous = dict(self._doc_hashes)

        # A document is only reusable when its recorded section count matches the
        # sections actually held. Without this an inconsistent persisted cache
        # (hashes present, sections missing) would report "unchanged" forever and
        # never self-heal, silently serving an incomplete corpus.
        with self._lock:
            held: Dict[str, int] = {}
            for section in self._sections:
                held[section.document] = held.get(section.document, 0) + 1
            expected = {
                doc: int((meta or {}).get("sections", 0))
                for doc, meta in self._doc_meta.items()
            }

        def reusable(doc: str) -> bool:
            return (previous.get(doc) == found[doc][1]
                    and held.get(doc, 0) == expected.get(doc, -1))

        new_docs = [d for d in found if d not in previous]
        changed = [d for d in found if d in previous and previous[d] != found[d][1]]
        removed = [d for d in previous if d not in found]
        unchanged = [d for d in found if d in previous and reusable(d)]
        inconsistent = [d for d in found
                        if d in previous and previous[d] == found[d][1]
                        and not reusable(d)]

        if (not force and not (new_docs or changed or removed or inconsistent)
                and not self.is_empty()):
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
                secs = process_document(path, knowledge_type, document_id=doc)
                new_sections.extend(secs)
                doc_meta[doc] = {
                    "document": doc,
                    "display_name": path.name,
                    "knowledge_type": knowledge_type,
                    "content_hash": content_hash,
                    "version": content_hash[:8],
                    "sections": len(secs),
                    "format": path.suffix.lstrip(".").lower(),
                    "updated_at": time.time(),
                    # Recorded so deletion can target one exact file instead of
                    # every file that happens to share the basename.
                    "relative_path": self._relative_path(path),
                }

            # Ingestion safety policy: a document is untrusted input, so
            # instruction-like content is removed once here rather than being
            # re-scanned on every request.
            for section in new_sections:
                section.text = _GUARDRAILS.scrub_instruction_like(section.text)
                section.heading = _GUARDRAILS.scrub_instruction_like(section.heading)

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

    def _relative_path(self, path: Path) -> str:
        try:
            return Path(path).relative_to(self.knowledge_dir).as_posix()
        except ValueError:
            return Path(path).name

    def source_provenance(self, documents: List[str]) -> List[dict]:
        """Document id plus content version for user-visible attribution."""
        with self._lock:
            meta = {doc: dict(values) for doc, values in self._doc_meta.items()}
        provenance = []
        for name in documents:
            entry = meta.get(name, {})
            provenance.append({
                "document": name,
                "display_name": str(entry.get("display_name") or Path(name).name),
                "version": str(entry.get("version") or ""),
                "updated_at": float(entry.get("updated_at") or 0.0),
            })
        return provenance

    def resolve_document(self, name: str) -> Optional[str]:
        """Map a relative path or an unambiguous basename to a document key.

        A bare basename that matches several documents returns None rather than
        picking one, so callers must disambiguate instead of acting on a guess.
        """
        key = Path(name).as_posix()
        with self._lock:
            if key in self._doc_meta:
                return key
            matches = [
                doc for doc, meta in self._doc_meta.items()
                if str(meta.get("display_name") or Path(doc).name) == Path(name).name
            ]
        return matches[0] if len(matches) == 1 else None

    def document_path(self, document_name: str) -> Optional[Path]:
        """Resolve the exact file backing an indexed document, or None."""
        key = self.resolve_document(document_name)
        if key is None:
            return None
        with self._lock:
            meta = dict(self._doc_meta.get(key) or {})
        relative = str(meta.get("relative_path") or key)
        candidate = self.knowledge_dir / relative
        return candidate if candidate.is_file() else None

    def remove_document(self, document_name: str) -> bool:
        """Drop a document's sections from the cache (and its file record)."""
        resolved = self.resolve_document(document_name)
        if resolved is None:
            return False
        document_name = resolved
        with self._lock:
            if document_name not in self._doc_hashes:
                return False
            self._sections = [s for s in self._sections if s.document != document_name]
            for i, sec in enumerate(self._sections):
                sec.section_id = i
            self._doc_hashes.pop(document_name, None)
            self._doc_meta.pop(document_name, None)
            # Removal changes cache state, so this build must win the version
            # check against an older persisted copy.
            self._built_at = time.time()
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

        # ISS-15 FIX: Expand query tokens with domain-specific synonyms so
        # "counseling" can match "mentorship", etc.
        expanded_q = set(q)
        for tok in q:
            if tok in _KNOWLEDGE_SYNONYMS:
                expanded_q.update(_KNOWLEDGE_SYNONYMS[tok])

        with self._lock:
            n_docs = max(1, len(self._sections))
            scores: Dict[int, float] = {}
            for tok in expanded_q:
                postings = self._index.get(tok)
                if not postings:
                    continue
                idf = math.log(1 + n_docs / len(postings))
                # Direct query tokens get full IDF; synonym expansions get 0.6x
                weight = 1.0 if tok in set(q) else 0.6
                for sid in postings:
                    scores[sid] = scores.get(sid, 0.0) + idf * weight
            if not scores:
                return []
            # Heading matches get a boost.
            results = []
            for sid, score in scores.items():
                sec = self._sections[sid]
                if knowledge_type and sec.knowledge_type != knowledge_type:
                    continue
                head_tokens = set(_tokens(sec.heading))
                boost = 1.0 + 0.5 * len(head_tokens & expanded_q)
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
            # Explicit no-result. Injecting arbitrary leading sections would let
            # the model answer from unrelated material while appearing grounded;
            # an empty result makes the caller state that it does not know.
            return "", []
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
