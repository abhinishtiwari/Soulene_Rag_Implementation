"""API endpoint tests via the Flask test client (fake LLM, no network)."""

from __future__ import annotations

import io
import json
import time
import unittest
import uuid

from app.config.settings import Settings
from tests.fake_llm import FakeLLMClient


def make_app():
    import main
    from app.chatbot import build_chatbot
    # Inject the fake LLM so no network calls happen.
    main._service = build_chatbot(Settings.from_env(), client=FakeLLMClient(),
                                  build_client=False)
    main.app.config.update(TESTING=True)
    return main, main.app.test_client()


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main, cls.client = make_app()

    def test_health(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "ok")

    def test_index_renders(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Soulene", r.get_data(as_text=True))

    def test_metrics_shape(self):
        r = self.client.get("/metrics")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        for k in ("knowledge_cache", "response_cache", "context_cache"):
            self.assertIn(k, body)

    def test_chat_ok(self):
        r = self.client.post("/chat", json={"message": "hello there",
                                            "session_id": "api-1", "user_id": "api-1"})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body["reply"])
        self.assertIn("route", body)
        self.assertIn("latency_ms", body)
        # ISS-17: internal classification (intent, safety_level) must NOT be
        # exposed on the public endpoint — it would let an attacker probe how
        # their messages are classified and tune evasion.
        self.assertNotIn("intent", body)
        self.assertNotIn("safety_level", body)

    def test_issue_016_grounded_replies_expose_their_sources(self):
        r = self.client.post("/chat", json={"message": "What services do you offer?",
                                            "session_id": "prov-1"})
        body = r.get_json()
        self.assertIn("grounded", body)
        self.assertIn("sources", body)
        if body["grounded"]:
            self.assertTrue(body["sources"])
            for entry in body["sources"]:
                for key in ("document", "display_name", "version"):
                    self.assertIn(key, entry)

    def test_issue_016_ungrounded_replies_claim_no_sources(self):
        r = self.client.post("/chat", json={"message": "hello there",
                                            "session_id": "prov-2"})
        body = r.get_json()
        self.assertFalse(body["grounded"])
        self.assertEqual(body["sources"], [])

    def test_chat_rejects_empty(self):
        self.assertEqual(self.client.post("/chat", json={"message": "  "}).status_code, 400)
        self.assertEqual(self.client.post("/chat", json={}).status_code, 400)

    def test_issue_001_chat_rejects_oversized_message(self):
        from app.utils import MAX_MESSAGE_CHARS
        oversized = "a" * (MAX_MESSAGE_CHARS + 1)
        for path in ("/chat", "/chat/stream"):
            with self.subTest(path=path):
                r = self.client.post(path, json={"message": oversized,
                                                 "session_id": "iss001",
                                                 "user_id": "iss001"})
                self.assertEqual(r.status_code, 413)
                self.assertEqual(r.get_json()["max_chars"], MAX_MESSAGE_CHARS)

    def test_chat_rejects_wrong_type(self):
        self.assertEqual(self.client.post("/chat", json={"message": 123}).status_code, 400)

    def test_stream_emits_sse_and_done(self):
        r = self.client.post("/chat/stream", json={"message": "hi",
                                                   "session_id": "api-s", "user_id": "api-s"})
        self.assertEqual(r.status_code, 200)
        text = r.get_data(as_text=True)
        self.assertIn("data:", text)
        self.assertIn("[DONE]", text)

    def test_documents_list(self):
        r = self.client.get("/documents")
        self.assertEqual(r.status_code, 200)
        self.assertIn("documents", r.get_json())

    def test_upload_and_query_document(self):
        name = f"test_services_{uuid.uuid4().hex[:6]}.md"
        content = ("# Special Programme\n"
                   "We run a Zebra Wellness Programme costing 777 rupees per month.\n")
        data = {"file": (io.BytesIO(content.encode()), name),
                "knowledge_type": "general"}
        r = self.client.post("/documents", data=data,
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        self.assertEqual(r.get_json()["status"], "indexed")

        # The new content must be retrievable from the knowledge cache.
        ctx, _ = self.main._service.cag.knowledge.build_context("Zebra Wellness Programme")
        self.assertIn("777", ctx)

        # Cleanup.
        self.client.delete(f"/documents/{name}")

    def test_issue_004_failed_ingest_rolls_back_the_saved_file(self):
        svc = self.main._service
        name = f"iss004_{uuid.uuid4().hex[:6]}.md"
        target = svc.cag.knowledge.knowledge_dir / "general" / name
        original = svc.cag.refresh_documents

        def boom(*a, **k):
            raise RuntimeError("indexing failed")

        svc.cag.refresh_documents = boom
        try:
            r = self.client.post(
                "/documents",
                data={"file": (io.BytesIO(b"# New\nbody"), name),
                      "knowledge_type": "general"},
                content_type="multipart/form-data")
        finally:
            svc.cag.refresh_documents = original
        self.assertEqual(r.status_code, 500)
        # Filesystem must not keep a document the index never accepted.
        self.assertFalse(target.exists())
        self.assertFalse(target.with_name(target.name + ".prev").exists())

    def test_issue_004_failed_ingest_restores_previous_version(self):
        svc = self.main._service
        name = f"iss004p_{uuid.uuid4().hex[:6]}.md"
        r = self.client.post(
            "/documents",
            data={"file": (io.BytesIO(b"# First\noriginal body"), name),
                  "knowledge_type": "general"},
            content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201)
        target = svc.cag.knowledge.knowledge_dir / "general" / name
        self.addCleanup(lambda: self.client.delete(f"/documents/{name}"))

        original = svc.cag.refresh_documents

        def boom(*a, **k):
            raise RuntimeError("indexing failed")

        svc.cag.refresh_documents = boom
        try:
            r2 = self.client.post(
                "/documents",
                data={"file": (io.BytesIO(b"# Second\nreplacement body"), name),
                      "knowledge_type": "general"},
                content_type="multipart/form-data")
        finally:
            svc.cag.refresh_documents = original
        self.assertEqual(r2.status_code, 500)
        self.assertIn("original body", target.read_text(encoding="utf-8"))

    def test_issue_004_delete_removes_only_the_exact_file(self):
        svc = self.main._service
        name = f"iss004d_{uuid.uuid4().hex[:6]}.md"
        kdir = svc.cag.knowledge.knowledge_dir
        twin = kdir / "company" / name
        twin.parent.mkdir(parents=True, exist_ok=True)
        twin.write_text("# Twin\nkeep me", encoding="utf-8")
        self.addCleanup(lambda: twin.unlink(missing_ok=True))

        r = self.client.post(
            "/documents",
            data={"file": (io.BytesIO(b"# General\ndelete me"), name),
                  "knowledge_type": "general"},
            content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201)
        general = kdir / "general" / name

        # ISSUE-012: both same-named documents are indexed, so the ambiguous
        # basename must be refused and the exact relative path used instead.
        ambiguous = self.client.delete(f"/documents/{name}")
        self.assertEqual(ambiguous.status_code, 404)
        self.assertTrue(general.exists())
        self.assertTrue(twin.exists())

        d = self.client.delete(f"/documents/general/{name}")
        self.assertEqual(d.status_code, 200)
        self.assertFalse(general.exists())
        # A same-named document in another folder must survive.
        self.assertTrue(twin.exists())

    def test_upload_rejects_unsupported_type(self):
        data = {"file": (io.BytesIO(b"MZ\x00"), "malware.exe")}
        r = self.client.post("/documents", data=data, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 415)

    def test_upload_requires_file(self):
        r = self.client.post("/documents", data={}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)

    def test_upload_path_traversal_sanitised(self):
        name = "../../evil_traversal.md"
        data = {"file": (io.BytesIO(b"# X\nhello"), name), "knowledge_type": "general"}
        r = self.client.post("/documents", data=data, content_type="multipart/form-data")
        self.assertIn(r.status_code, (201, 400))
        if r.status_code == 201:
            saved = r.get_json()["document"]
            self.assertNotIn("..", saved)
            self.assertNotIn("/", saved)
            self.client.delete(f"/documents/{saved}")

    def test_session_delete_discloses_that_quarantined_data_still_exists(self):
        created = self.client.post("/sessions")
        self.assertEqual(created.status_code, 201)
        session_id = created.get_json()["session"]["session_id"]
        self.client.post("/chat", json={"message": "I prefer quiet tea rooms",
                                        "session_id": session_id})
        r = self.client.delete(f"/sessions/{session_id}")
        self.assertEqual(r.status_code, 200)
        outcome = r.get_json()["derived_memory"]
        for key in ("removed", "quarantined", "retained"):
            self.assertIn(key, outcome)
        # A caller must be able to tell that quarantined data was not erased.
        self.assertIn("quarantined_still_stored", outcome)
        self.assertEqual(outcome["quarantined_still_stored"],
                         bool(outcome["quarantined"]))

    def test_feedback_stored_and_isolated(self):
        r = self.client.post("/feedback", json={"message": "The send button lags",
                                                "category": "bug", "user_id": "fb-1"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["category"], "bug")

    def test_feedback_requires_message(self):
        self.assertEqual(self.client.post("/feedback", json={}).status_code, 400)

    def test_feedback_does_not_leak_into_chat(self):
        secret = "ZZQQ-feedback-secret-token"
        self.client.post("/feedback", json={"message": secret, "user_id": "fb-2"})
        r = self.client.post("/chat", json={"message": "what did I just report?",
                                            "session_id": "fb-2", "user_id": "fb-2"})
        self.assertNotIn(secret, r.get_json()["reply"])

    def test_no_stack_trace_leaked_on_error(self):
        """A failing service must return a clean message, never internals."""
        original = self.main._service.handle

        def boom(*a, **k):
            raise RuntimeError("secret internal detail")
        self.main._service.handle = boom
        try:
            r = self.client.post("/chat", json={"message": "hi", "session_id": "e1"})
            self.assertEqual(r.status_code, 503)
            body = r.get_data(as_text=True)
            self.assertNotIn("secret internal detail", body)
            self.assertNotIn("Traceback", body)
        finally:
            self.main._service.handle = original


class PerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main, cls.client = make_app()
        cls.service = cls.main._service

    def test_simple_message_makes_no_knowledge_lookup(self):
        fake = self.service.client
        before = len(fake.generations)
        res = self.service.handle("perf-1", "hey there", user_id="perf-1")
        self.assertFalse(res.used_rag, "small talk must not touch the knowledge cache")
        # Exactly one reply-producing call, whatever the reviewer setting is.
        self.assertEqual(len(fake.generations) - before, 1)

    def test_repeat_factual_question_costs_zero_llm_calls(self):
        fake = self.service.client
        self.service.cag.responses.clear()
        self.service.handle("perf-2", "what services do you offer", user_id="perf-2")
        mid = len(fake.generations)
        self.service.handle("perf-2", "what services do you offer", user_id="perf-2")
        self.assertEqual(len(fake.generations), mid,
                         "cache hit must avoid reply generation entirely")

    def test_knowledge_context_build_is_fast(self):
        kc = self.service.cag.knowledge
        t0 = time.perf_counter()
        for _ in range(50):
            kc.build_context("what are your plans and pricing")
        elapsed = (time.perf_counter() - t0) / 50
        self.assertLess(elapsed, 0.02, f"context build too slow: {elapsed*1000:.1f}ms")

    def test_system_prompt_stays_small(self):
        from app.prompts.system_prompt import CORE_PROMPT, approx_prompt_tokens
        self.assertLess(approx_prompt_tokens(CORE_PROMPT), 500,
                        "core prompt must stay lightweight")

    def test_context_cache_bounded_under_load(self):
        for i in range(300):
            self.service.cag.context.append("perf-3", "user", f"message {i}")
        self.assertLessEqual(len(self.service.cag.context.all_cached("perf-3")),
                             self.service.cag.context.cache_size)

    def test_prompt_window_bounded(self):
        for i in range(200):
            self.service.cag.context.append("perf-4", "user", f"m{i}")
        window = self.service.cag.context.formatted_window("perf-4")
        self.assertLessEqual(len(window.split("\n")), self.service.cag.context.prompt_window)

    def test_concurrent_sessions_stay_isolated(self):
        import threading
        results = {}

        def worker(n):
            sid = f"conc-{n}"
            self.service.handle(sid, f"my secret is code{n}", user_id=sid)
            results[n] = self.service.cag.context.formatted_window(sid)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for n in results:
            for other in results:
                if other != n:
                    self.assertNotIn(f"code{other}", results[n],
                                     "conversation cache leaked across sessions")


if __name__ == "__main__":
    unittest.main(verbosity=2)
