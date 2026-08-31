"""CAG layer tests: document processing, knowledge cache, caches, feedback isolation."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from app.cag.cag_engine import CAGEngine
from app.cag.context_cache import ContextCache
from app.cag.document_processor import clean_text, process_document
from app.cag.knowledge_cache import KnowledgeCache
from app.cag.response_cache import ResponseCache
from app.storage.feedback_store import FeedbackStore


class DocumentIdentityTests(unittest.TestCase):
    """ISSUE-012: documents are identified by relative path, not basename."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.knowledge = self.root / "knowledge"
        self.cache = self.root / "cache"
        for folder in ("company", "wellness"):
            (self.knowledge / folder).mkdir(parents=True)
        (self.knowledge / "company" / "pricing.md").write_text(
            "# Pricing\nCompany plan costs 111 rupees.", encoding="utf-8")
        (self.knowledge / "wellness" / "pricing.md").write_text(
            "# Pricing\nWellness plan costs 222 rupees.", encoding="utf-8")
        self.kc = KnowledgeCache(self.knowledge, self.cache)
        self.kc.refresh(force=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_same_basename_documents_are_both_indexed(self):
        keys = sorted(d["document"] for d in self.kc.documents())
        self.assertEqual(keys, ["company/pricing.md", "wellness/pricing.md"])
        context, _ = self.kc.build_context("pricing plan cost")
        self.assertIn("111", context)
        self.assertIn("222", context)

    def test_ambiguous_basename_is_not_guessed(self):
        self.assertIsNone(self.kc.resolve_document("pricing.md"))
        self.assertIsNone(self.kc.document_path("pricing.md"))
        self.assertFalse(self.kc.remove_document("pricing.md"))
        # Both documents survive an ambiguous request.
        self.assertEqual(len(self.kc.documents()), 2)

    def test_exact_path_resolves_and_removes_one_document(self):
        self.assertEqual(self.kc.resolve_document("company/pricing.md"),
                         "company/pricing.md")
        self.assertTrue(self.kc.remove_document("company/pricing.md"))
        keys = [d["document"] for d in self.kc.documents()]
        self.assertEqual(keys, ["wellness/pricing.md"])
        # Once unique, the basename is unambiguous again.
        self.assertEqual(self.kc.resolve_document("pricing.md"), "wellness/pricing.md")

    def test_legacy_cache_is_migrated_and_collisions_dropped(self):
        import json
        # Simulate a v1 (basename-keyed) payload: unique names migrate, and the
        # colliding name is dropped so refresh can re-key both copies.
        (self.knowledge / "company" / "unique_guide.md").write_text(
            "# Guide\nUnique guide body text.", encoding="utf-8")
        self.kc.refresh(force=True)
        path = self.cache / KnowledgeCache.CACHE_FILENAME
        current = json.loads(path.read_text(encoding="utf-8"))

        legacy = {
            "built_at": current["built_at"],
            "doc_hashes": {Path(k).name: v for k, v in current["doc_hashes"].items()},
            "doc_meta": {Path(k).name: {**v, "document": Path(k).name}
                         for k, v in current["doc_meta"].items()},
            "sections": [{**s, "document": Path(s["document"]).name}
                         for s in current["sections"]],
        }
        path.write_text(json.dumps(legacy), encoding="utf-8")

        migrated = KnowledgeCache(self.knowledge, self.cache)
        self.assertTrue(migrated.load())
        keys = sorted(d["document"] for d in migrated.documents())
        # The unambiguous document keeps its preprocessed sections.
        self.assertIn("company/unique_guide.md", keys)
        self.assertTrue(migrated.section_count > 0)
        # The colliding basename is not guessed at.
        self.assertNotIn("pricing.md", keys)
        # A refresh restores both colliding documents under distinct keys.
        migrated.refresh()
        keys = sorted(d["document"] for d in migrated.documents())
        self.assertEqual(keys, ["company/pricing.md", "company/unique_guide.md",
                                "wellness/pricing.md"])

    def test_inconsistent_cache_self_heals(self):
        # Hashes claim documents exist but sections were lost: refresh must
        # rebuild instead of reporting "unchanged" forever.
        self.kc._sections = []
        report = self.kc.refresh()
        self.assertEqual(report["status"], "rebuilt")
        self.assertGreater(self.kc.section_count, 0)


class SourceProvenanceTests(unittest.TestCase):
    """ISSUE-016: grounded answers must carry document id and version."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        folder = self.root / "knowledge" / "company"
        folder.mkdir(parents=True)
        (folder / "pricing.md").write_text(
            "# Pricing\nThe Zephyr plan costs 321 rupees per month.",
            encoding="utf-8")
        self.kc = KnowledgeCache(self.root / "knowledge", self.root / "cache")
        self.kc.refresh(force=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_provenance_includes_id_display_name_and_version(self):
        _, sources = self.kc.build_context("zephyr plan price")
        provenance = self.kc.source_provenance(sources)
        self.assertTrue(provenance)
        entry = provenance[0]
        self.assertEqual(entry["document"], "company/pricing.md")
        self.assertEqual(entry["display_name"], "pricing.md")
        self.assertTrue(entry["version"])
        self.assertGreater(entry["updated_at"], 0)

    def test_version_changes_when_the_document_changes(self):
        first = self.kc.source_provenance(["company/pricing.md"])[0]["version"]
        (self.root / "knowledge" / "company" / "pricing.md").write_text(
            "# Pricing\nThe Zephyr plan costs 654 rupees per month.",
            encoding="utf-8")
        self.kc.refresh()
        second = self.kc.source_provenance(["company/pricing.md"])[0]["version"]
        self.assertNotEqual(first, second)

    def test_unknown_document_still_yields_a_stable_shape(self):
        entry = self.kc.source_provenance(["missing/thing.md"])[0]
        self.assertEqual(entry["document"], "missing/thing.md")
        self.assertEqual(entry["version"], "")


class NoResultRetrievalTests(unittest.TestCase):
    """ISSUE-013: a lexical miss must return no support, not arbitrary sections."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        folder = self.root / "knowledge" / "general"
        folder.mkdir(parents=True)
        for i in range(6):
            (folder / f"doc{i}.md").write_text(
                f"# Topic {i}\n"
                + f"Sunflower irrigation schedule number {i} for tractors. " * 40,
                encoding="utf-8")
        # Budget below the corpus size forces the narrowing path.
        self.kc = KnowledgeCache(self.root / "knowledge", self.root / "cache",
                                 token_budget=800)
        self.kc.refresh(force=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_disjoint_query_returns_no_context(self):
        self.assertFalse(self.kc.fits_in_budget)
        self.assertEqual(self.kc.search_sections("quantum chromodynamics ballet"), [])
        context, sources = self.kc.build_context("quantum chromodynamics ballet")
        self.assertEqual(context, "")
        self.assertEqual(sources, [])

    def test_matching_query_still_returns_context(self):
        context, sources = self.kc.build_context("sunflower irrigation tractors")
        self.assertIn("Sunflower", context)
        self.assertTrue(sources)

    def test_engine_reports_no_knowledge_hit_on_miss(self):
        engine = CAGEngine(knowledge_dir=self.root / "knowledge",
                           cache_dir=self.root / "cache", token_budget=800)
        engine.knowledge.refresh(force=True)
        lookup = engine.lookup("quantum chromodynamics ballet", needs_knowledge=True)
        self.assertFalse(lookup.knowledge_hit)
        self.assertEqual(lookup.knowledge_context, "")

    def test_knowledge_type_is_preserved_on_narrowing(self):
        other = self.root / "knowledge" / "wellness"
        other.mkdir(parents=True)
        (other / "breath.md").write_text(
            "# Breathing\n" + "Slow breathing practice for calm. " * 40,
            encoding="utf-8")
        self.kc.refresh(force=True)
        context, sources = self.kc.build_context("slow breathing practice",
                                                 knowledge_type="wellness")
        self.assertTrue(sources)
        self.assertTrue(all(s.startswith("wellness/") for s in sources))


class ConcurrentCachePersistenceTests(unittest.TestCase):
    """ISSUE-014: cache persistence must not use one shared staging filename."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        folder = self.root / "knowledge" / "general"
        folder.mkdir(parents=True)
        (folder / "a.md").write_text("# A\nalpha content here", encoding="utf-8")
        self.cache = self.root / "cache"

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _cache(self):
        kc = KnowledgeCache(self.root / "knowledge", self.cache)
        kc.refresh(force=True)
        return kc

    def test_concurrent_saves_do_not_corrupt_or_raise(self):
        import json
        import threading
        caches = [self._cache() for _ in range(6)]
        errors = []

        def writer(kc):
            try:
                for _ in range(40):
                    kc.save()
            except Exception as exc:  # pragma: no cover - failure detail only
                errors.append(repr(exc))

        threads = [threading.Thread(target=writer, args=(kc,)) for kc in caches]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        payload = json.loads(
            (self.cache / KnowledgeCache.CACHE_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(payload["cache_version"], KnowledgeCache.CACHE_VERSION)
        self.assertTrue(payload["sections"])

    def test_no_staging_files_are_left_behind(self):
        kc = self._cache()
        for _ in range(5):
            kc.save()
        leftovers = list(self.cache.glob(".knowledge_cache-*"))
        self.assertEqual(leftovers, [])
        self.assertFalse((self.cache / "knowledge_cache.tmp").exists())

    def test_older_build_does_not_clobber_a_newer_one(self):
        stale = self._cache()
        fresh = self._cache()
        fresh.save()
        # Force the stale writer to look older than what is already published.
        stale._built_at = fresh._built_at - 10
        stale._sections = []
        stale.save()
        import json
        payload = json.loads(
            (self.cache / KnowledgeCache.CACHE_FILENAME).read_text(encoding="utf-8"))
        self.assertTrue(payload["sections"], "newer build must survive")


class DocumentProcessingTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_clean_text_joins_hyphenated_wraps(self):
        self.assertIn("wellbeing", clean_text("well-\nbeing matters"))

    def test_markdown_sections(self):
        p = self.dir / "svc.md"
        p.write_text("# Our Services\nWe offer therapy.\n\n# Pricing\nBasic is free.",
                     encoding="utf-8")
        secs = process_document(p, "general")
        heads = [s.heading for s in secs]
        self.assertIn("Our Services", heads)
        self.assertIn("Pricing", heads)

    def test_txt_extraction(self):
        p = self.dir / "n.txt"
        p.write_text("PLAN DETAILS\nBasic plan costs nothing at all.", encoding="utf-8")
        secs = process_document(p, "general")
        self.assertTrue(any("Basic plan" in s.text for s in secs))

    def test_unsupported_returns_empty(self):
        p = self.dir / "x.exe"
        p.write_bytes(b"\x00\x01")
        self.assertEqual(process_document(p, "general"), [])

    def test_corrupt_file_does_not_raise(self):
        p = self.dir / "bad.pdf"
        p.write_bytes(b"not really a pdf")
        self.assertEqual(process_document(p, "general"), [])


class KnowledgeCacheTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.kdir = self.root / "knowledge" / "company"
        self.kdir.mkdir(parents=True)
        (self.kdir / "services.md").write_text(
            "# Services\nWe offer counselling, workshops and athlete support.\n"
            "# Pricing\nBasic is Free. Wellness is 449 per month.", encoding="utf-8")
        self.cache_dir = self.root / "cache"
        self.kc = KnowledgeCache(self.root / "knowledge", self.cache_dir)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_build_and_query(self):
        r = self.kc.refresh(force=True)
        self.assertEqual(r["status"], "rebuilt")
        self.assertGreater(self.kc.section_count, 0)
        ctx, docs = self.kc.build_context("what do you charge")
        self.assertIn("449", ctx)
        # ISSUE-012: documents are keyed by canonical relative path.
        self.assertIn("company/services.md", docs)

    def test_full_preload_when_small(self):
        self.kc.refresh(force=True)
        self.assertTrue(self.kc.fits_in_budget)

    def test_persistence_roundtrip(self):
        self.kc.refresh(force=True)
        other = KnowledgeCache(self.root / "knowledge", self.cache_dir)
        self.assertTrue(other.load())
        self.assertEqual(other.section_count, self.kc.section_count)

    def test_unchanged_is_skipped(self):
        self.kc.refresh(force=True)
        self.assertEqual(self.kc.refresh()["status"], "unchanged")

    def test_changed_document_is_reprocessed(self):
        self.kc.refresh(force=True)
        (self.kdir / "services.md").write_text(
            "# Pricing\nWellness is now 599 per month.", encoding="utf-8")
        r = self.kc.refresh()
        self.assertEqual(r["status"], "rebuilt")
        self.assertEqual(r["changed"], 1)
        ctx, _ = self.kc.build_context("price")
        self.assertIn("599", ctx)
        self.assertNotIn("449", ctx)

    def test_new_document_detected(self):
        self.kc.refresh(force=True)
        (self.kdir / "extra.md").write_text("# Athletes\nSport psychology support.",
                                            encoding="utf-8")
        r = self.kc.refresh()
        self.assertEqual(r["new"], 1)
        ctx, _ = self.kc.build_context("athletes")
        self.assertIn("Sport psychology", ctx)

    def test_removed_document_purges_vectors(self):
        self.kc.refresh(force=True)
        (self.kdir / "services.md").unlink()
        r = self.kc.refresh()
        self.assertEqual(r["removed"], 1)
        self.assertEqual(self.kc.section_count, 0)

    def test_remove_document_api(self):
        self.kc.refresh(force=True)
        self.assertTrue(self.kc.remove_document("services.md"))
        self.assertEqual(self.kc.section_count, 0)

    def test_budget_overflow_narrows(self):
        big = self.kdir / "big.md"
        big.write_text("\n\n".join(f"# Topic{i}\n" + ("filler text about wellbeing " * 40)
                                   for i in range(200)), encoding="utf-8")
        kc = KnowledgeCache(self.root / "knowledge", self.cache_dir, token_budget=1500)
        kc.refresh(force=True)
        self.assertFalse(kc.fits_in_budget)
        ctx, _ = kc.build_context("athlete support")
        self.assertLessEqual(len(ctx) // 4, 1600)
        self.assertTrue(ctx)


class ResponseCacheTests(unittest.TestCase):
    def setUp(self):
        self.rc = ResponseCache(max_entries=5, ttl_seconds=999)

    def test_exact_and_near_match(self):
        self.rc.put("What is the Wellness plan price?", "449")
        self.assertIsNotNone(self.rc.get("What is the Wellness plan price?"))
        self.assertIsNotNone(self.rc.get("what is wellness plan price"))

    def test_different_question_misses(self):
        self.rc.put("What is the Wellness plan price?", "449")
        self.assertIsNone(self.rc.get("do you support athletes"))

    def test_scope_isolation(self):
        self.rc.put("hello", "hi", scope="knowledge")
        self.assertIsNone(self.rc.get("hello", scope="emotional"))

    def test_ttl_expiry(self):
        rc = ResponseCache(ttl_seconds=-1)
        rc.put("q", "a")
        self.assertIsNone(rc.get("q"))

    def test_lru_eviction(self):
        for i in range(10):
            self.rc.put(f"unique question number {i}", f"a{i}")
        self.assertLessEqual(self.rc.stats()["entries"], 5)

    def test_invalidate_scope(self):
        self.rc.put("q one two", "a")
        self.assertEqual(self.rc.invalidate_scope("knowledge"), 1)
        self.assertIsNone(self.rc.get("q one two"))


class ContextCacheTests(unittest.TestCase):
    def test_window_and_overflow(self):
        cc = ContextCache(cache_size=50, prompt_window=5)
        for i in range(20):
            cc.append("c", "user", f"m{i}")
        self.assertEqual(len(cc.recent("c")), 5)
        self.assertEqual(len(cc.all_cached("c")), 20)
        self.assertTrue(cc.needs_summary("c"))
        self.assertEqual(len(cc.overflow_turns("c")), 15)

    def test_cache_size_cap(self):
        cc = ContextCache(cache_size=10, prompt_window=5)
        for i in range(40):
            cc.append("c", "user", f"m{i}")
        self.assertEqual(len(cc.all_cached("c")), 10)

    def test_conversation_isolation(self):
        cc = ContextCache()
        cc.append("a", "user", "secret-a")
        self.assertEqual(cc.all_cached("b"), [])
        self.assertNotIn("secret-a", cc.formatted_window("b"))

    def test_clear(self):
        cc = ContextCache()
        cc.append("a", "user", "x")
        cc.clear("a")
        self.assertEqual(cc.all_cached("a"), [])


class CAGEngineTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        kdir = self.root / "knowledge" / "company"
        kdir.mkdir(parents=True)
        (kdir / "svc.md").write_text("# Services\nWe offer athlete mental support.",
                                     encoding="utf-8")
        self.engine = CAGEngine(self.root / "knowledge", self.root / "cache")
        self.engine.warm()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_no_knowledge_when_not_needed(self):
        r = self.engine.lookup("hi", needs_knowledge=False)
        self.assertEqual(r.knowledge_context, "")
        self.assertFalse(r.knowledge_hit)

    def test_knowledge_injected_when_needed(self):
        r = self.engine.lookup("do you help athletes", needs_knowledge=True)
        self.assertTrue(r.knowledge_hit)
        self.assertIn("athlete", r.knowledge_context.lower())

    def test_response_cache_short_circuit(self):
        self.engine.store_answer("do you help athletes", "Yes we do.")
        r = self.engine.lookup("do you help athletes", needs_knowledge=True)
        self.assertTrue(r.cache_hit)
        self.assertEqual(r.cached_answer, "Yes we do.")

    def test_document_change_invalidates_response_cache(self):
        self.engine.store_answer("do you help athletes", "Yes we do.")
        (self.root / "knowledge" / "company" / "svc.md").write_text(
            "# Services\nWe now focus on students only.", encoding="utf-8")
        self.engine.refresh_documents()
        r = self.engine.lookup("do you help athletes", needs_knowledge=True)
        self.assertFalse(r.cache_hit, "stale factual answers must be invalidated")

    def test_stats_shape(self):
        s = self.engine.stats()
        for key in ("knowledge_cache", "response_cache", "context_cache"):
            self.assertIn(key, s)


class FeedbackIsolationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.fb = FeedbackStore(self.root / "feedback.sqlite3")

    def tearDown(self):
        self.fb.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_submit_and_count(self):
        self.fb.submit("u1", "The button is broken", "bug")
        self.assertEqual(self.fb.count("u1"), 1)

    def test_category_normalised(self):
        item = self.fb.submit("u1", "idea", "NONSENSE")
        self.assertEqual(item.category, "other")

    def test_user_isolation(self):
        self.fb.submit("userA", "A only")
        self.fb.submit("userB", "B only")
        self.assertEqual(self.fb.count("userA"), 1)

    def test_separate_database_file(self):
        """Feedback must live in its own DB, not the chat archive."""
        from app.storage.chat_archive import ChatArchive
        archive = ChatArchive(self.root / "chat_archive.sqlite3")
        try:
            self.assertNotEqual(self.fb.db_path, archive.db_path)
            self.assertTrue(self.fb.db_path.exists())
        finally:
            archive.close()

    def test_service_holds_no_feedback_reference(self):
        """The chat service must not be able to read feedback."""
        from app.chatbot.chatbot_service import ChatbotService
        import inspect
        src = inspect.getsource(ChatbotService)
        self.assertNotIn("FeedbackStore", src)
        self.assertNotIn("feedback", src.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
