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
        self.assertIn("services.md", docs)

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
