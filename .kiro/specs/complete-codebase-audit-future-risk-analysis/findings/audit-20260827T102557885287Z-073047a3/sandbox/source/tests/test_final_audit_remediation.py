"""Regression evidence for the final persistence/security audit."""

from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from app.chatbot import build_chatbot
from app.config.settings import Settings
from app.identity import IdentityManager
from app.memory.long_term_memory_sqlite import LongTermMemorySQLite
from app.storage.chat_archive import ChatArchive
from app.storage.chat_archive_json import ChatArchiveJSON
from app.storage.feedback_store import FeedbackStore
from tests.fake_llm import FakeLLMClient


def _service(db_path: Path):
    settings = replace(
        Settings.from_env(), storage_backend="sqlite", mongo_uri="",
        context_cache_size=10, prompt_window=4,
        enable_input_moderation=False, enable_semantic_safety=False,
    )
    service = build_chatbot(
        settings, client=FakeLLMClient(), build_client=False, warm_cache=False
    )
    service.archive = ChatArchive(db_path)
    service.profile = LongTermMemorySQLite(db_path)
    return service


class IdempotencyAndSecondaryWorkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "audit.sqlite3"
        self.service = _service(self.db_path)

    def tearDown(self):
        try:
            import main
            if main._feedback is not None:
                main._feedback.close()
                main._feedback = None
        finally:
            self.temp.cleanup()

    def test_identical_unkeyed_api_submissions_are_distinct(self):
        import main
        main._service = self.service
        main._feedback = FeedbackStore(Path(self.temp.name) / "feedback.sqlite3")
        main._identity = IdentityManager("audit-identity-secret-that-is-long-enough-123")
        main.app.config.update(TESTING=True)
        client = main.app.test_client()
        identity = client.get("/identity").get_json()
        for _ in range(2):
            response = client.post("/chat", json={"message": "same intentional message"})
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(
            self.service.archive.count(identity["user_id"], identity["session_id"]), 4
        )

    def test_explicit_key_replay_validates_payload(self):
        self.service.handle("session", "first", user_id="user", request_id="fixed")
        with self.assertRaisesRegex(ValueError, "different message"):
            self.service.handle(
                "session", "different", user_id="user", request_id="fixed"
            )
        self.assertEqual(self.service.archive.count("user", "session"), 2)

    def test_memory_failure_is_durable_and_retried_with_provenance(self):
        original = self.service.profile.observe
        calls = {"count": 0}

        def fail_once(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("memory unavailable")
            return original(*args, **kwargs)

        self.service.profile.observe = fail_once
        result = self.service.handle(
            "session", "My name is Priya", user_id="user", request_id="memory-1"
        )
        self.assertTrue(result.reply)
        self.assertEqual(self.service.archive.secondary_pending_count(), 1)
        self.service.profile.observe = original
        self.service.handle(
            "session", "hello again", user_id="user", request_id="memory-2"
        )
        memory = self.service.profile.retrieve("user", "name")[0]
        self.assertEqual(
            memory.sources,
            [{"session_id": "session", "message_id": self.service.archive.get_request(
                "user", "session", "memory-1"
            )["user_message_id"]}],
        )
        self.assertEqual(self.service.archive.secondary_pending_count(), 0)
    def test_summary_state_failure_recovers_after_fresh_service(self):
        self.service.handle("summary", "turn one", user_id="user", request_id="s1")
        self.service.handle("summary", "turn two", user_id="user", request_id="s2")
        original = self.service.archive.save_safety_state
        failed = {"done": False}

        def fail_once(*args, **kwargs):
            if not failed["done"]:
                failed["done"] = True
                raise RuntimeError("state unavailable")
            return original(*args, **kwargs)

        self.service.archive.save_safety_state = fail_once
        completed = self.service.handle(
            "summary", "turn three with a late detail",
            user_id="user", request_id="s3",
        )
        self.assertTrue(completed.reply)
        self.assertGreater(self.service.archive.secondary_pending_count(), 0)
        self.service.archive.save_safety_state = original

        fresh = _service(self.db_path)
        replay = fresh.handle(
            "summary", "turn three with a late detail",
            user_id="user", request_id="s3",
        )
        self.assertIn("idempotent_replay=True", replay.notes)
        state = fresh.archive.load_safety_state("user", "summary")
        self.assertTrue(state.get("summary"))
        self.assertIn("turn one", state["summary"].lower())
        self.assertEqual(fresh.archive.secondary_pending_count(), 0)


class ProvenanceAndHistoricalRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "data.sqlite3"

    def tearDown(self):
        self.temp.cleanup()

    def test_session_deletion_removes_only_exclusive_evidence(self):
        memory = LongTermMemorySQLite(self.path)
        memory.observe(
            "user", "My name is Alex", source_session_id="one",
            source_message_id="m1",
        )
        memory.observe(
            "user", "My name is Alex", source_session_id="two",
            source_message_id="m2",
        )
        memory.observe("user", "I prefer quiet tea rooms")  # legacy/unattributed
        memory.forget_session("user", "one")
        name = memory.retrieve("user", "name")[0]
        self.assertEqual(name.sources, [{"session_id": "two", "message_id": "m2"}])
        memory.forget_session("user", "two")
        self.assertFalse(any(item.kind == "name" for item in memory.retrieve("user", "name")))
        self.assertTrue(memory.retrieve("user", "quiet tea"))

    def test_digest_preserves_late_disclosure_beyond_old_limits(self):
        archive = ChatArchive(self.path)
        for index in range(100):
            text = f"ordinary historical filler {index} " + ("x" * 60)
            if index == 99:
                text += " unique-late-disclosure-quetzal"
            archive.record("user", "long-session", "user", text)
        digest = archive.session_digests("user", limit=1)[0]["text"]
        self.assertIn("ordinary historical filler 0", digest)
        self.assertIn("unique-late-disclosure-quetzal", digest)
        self.assertLessEqual(len(digest), 4000)


class LegacyJsonMigrationTests(unittest.TestCase):
    def test_migration_is_source_preserving_and_restart_idempotent(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "legacy-user" / "legacy-session.json"
            source.parent.mkdir(parents=True)
            payload = {
                "session_id": "legacy-session", "user_id": "legacy-user",
                "created_at": 100.0, "safety_state": {"summary": "kept"},
                "messages": [
                    {"message_id": "legacy-m1", "role": "user",
                     "content": "old question", "created_at": 101.0},
                    {"message_id": "legacy-m2", "role": "assistant",
                     "content": "old answer", "created_at": 102.0},
                ],
            }
            source.write_text(json.dumps(payload), encoding="utf-8")
            before = source.read_bytes()
            archive = ChatArchiveJSON(root)
            self.assertEqual(archive.migration_report["imported"], 1)
            messages = archive.fetch_page("legacy-user", "legacy-session", 0, 10)
            self.assertEqual([m.message_id for m in messages], ["legacy-m1", "legacy-m2"])
            self.assertEqual([m.sequence_number for m in messages], [1, 2])
            self.assertEqual(archive.load_safety_state(
                "legacy-user", "legacy-session"
            )["summary"], "kept")
            self.assertEqual(source.read_bytes(), before)
            restarted = ChatArchiveJSON(root)
            self.assertEqual(restarted.migration_report["skipped"], 1)
            self.assertEqual(restarted.count("legacy-user", "legacy-session"), 2)
            self.assertEqual(source.read_bytes(), before)
    def test_malformed_legacy_json_fails_loudly_without_modifying_source(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "user" / "broken.json"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"{broken")
            before = source.read_bytes()
            with self.assertRaisesRegex(ValueError, "invalid legacy chat JSON"):
                ChatArchiveJSON(root)
            self.assertEqual(source.read_bytes(), before)


class AdversarialCrossUserApiTests(unittest.TestCase):
    def test_independent_principals_cannot_enumerate_mutate_or_replay_each_other(self):
        import main
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            service = _service(root / "api.sqlite3")
            main._service = service
            main._feedback = FeedbackStore(root / "feedback.sqlite3")
            main._identity = IdentityManager(
                "cross-user-audit-identity-secret-123456789"
            )
            main.app.config.update(TESTING=True)
            victim = main.app.test_client()
            attacker = main.app.test_client()
            victim_identity = victim.get("/identity").get_json()
            attacker_identity = attacker.get("/identity").get_json()
            self.assertNotEqual(victim_identity["user_id"], attacker_identity["user_id"])

            victim_write = victim.post(
                "/chat", json={"message": "victim private trauma"},
                headers={"Idempotency-Key": "shared-key"},
            )
            self.assertEqual(victim_write.status_code, 200)
            victim_session = victim_identity["session_id"]

            self.assertEqual(attacker.get(
                f"/sessions/{victim_session}"
            ).status_code, 404)
            self.assertEqual(attacker.delete(
                f"/sessions/{victim_session}"
            ).status_code, 404)
            injected = attacker.post(
                "/chat",
                json={"message": "attacker turn", "session_id": victim_session,
                      "user_id": victim_identity["user_id"]},
                headers={"Idempotency-Key": "shared-key"},
            )
            self.assertEqual(injected.status_code, 200)
            self.assertEqual(service.archive.count(
                victim_identity["user_id"], victim_session
            ), 2)
            self.assertEqual(service.archive.count(
                attacker_identity["user_id"], attacker_identity["session_id"]
            ), 2)
            attacker_sessions = attacker.get("/sessions").get_json()["sessions"]
            self.assertNotIn(victim_session, {item["session_id"] for item in attacker_sessions})
            victim_history = victim.get(f"/sessions/{victim_session}")
            self.assertEqual(victim_history.status_code, 200)
            self.assertIn("victim private trauma", victim_history.get_data(as_text=True))

            issued = main._identity.issue().token
            payload, signature = issued.split(".", 1)
            tampered = payload + "." + ("A" if signature[0] != "A" else "B") + signature[1:]
            rejected = attacker.get(
                "/sessions", headers={"X-Soulene-Identity": tampered}
            )
            self.assertEqual(rejected.status_code, 401)
            main._feedback.close()
            main._feedback = None


if __name__ == "__main__":
    unittest.main(verbosity=2)
