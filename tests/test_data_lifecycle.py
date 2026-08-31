"""Deterministic lifecycle tests for identity, archive, cache, and memory."""

from __future__ import annotations

import concurrent.futures
import multiprocessing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.cag.context_cache import ContextCache
from app.identity import IdentityManager, InvalidIdentity
from app.memory.long_term_memory_sqlite import LongTermMemorySQLite
from app.storage.chat_archive import ChatArchive
from app.types import Turn


def _process_write_turns(db_path: str, start: int, count: int, results) -> None:
    try:
        archive = ChatArchive(Path(db_path))
        for index in range(start, start + count):
            archive.record_turn(
                "process-user", "process-session", f"question-{index}",
                f"answer-{index}", f"request-{index}",
            )
        results.put(None)
    except BaseException as exc:
        results.put(f"{type(exc).__name__}: {exc}")


class IdentityLifecycleTests(unittest.TestCase):
    SECRET = "fixed-test-secret-that-is-at-least-thirty-two-bytes"

    def test_signed_roundtrip_and_permanent_session_is_stable(self):
        with tempfile.TemporaryDirectory() as raw:
            data_dir = Path(raw)
            manager = IdentityManager.from_config("", data_dir)
            issued = manager.issue()
            verified = manager.verify(issued.token)
            restarted = IdentityManager.from_config("", data_dir).verify(issued.token)

            self.assertTrue(issued.is_new)
            self.assertFalse(verified.is_new)
            self.assertEqual((verified.user_id, verified.session_id),
                             (issued.user_id, issued.session_id))
            self.assertEqual((restarted.user_id, restarted.session_id),
                             (issued.user_id, issued.session_id))
            self.assertEqual(restarted.token, issued.token)

    def test_forged_token_is_rejected(self):
        manager = IdentityManager(self.SECRET)
        token = manager.issue().token
        payload, signature = token.split(".", 1)
        replacement = "A" if signature[0] != "A" else "B"
        with self.assertRaises(InvalidIdentity):
            manager.verify(f"{payload}.{replacement}{signature[1:]}")

    def test_many_principals_are_unique(self):
        principals = [IdentityManager(self.SECRET).issue() for _ in range(256)]
        self.assertEqual(len({p.user_id for p in principals}), len(principals))
        self.assertEqual(len({p.session_id for p in principals}), len(principals))
        self.assertEqual(len({p.token for p in principals}), len(principals))


class ChatArchiveLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "chat.sqlite3"
        self.archive = ChatArchive(self.db_path)

    def tearDown(self):
        self.archive.close()
        self.temp_dir.cleanup()

    def test_global_session_owner_is_immutable_and_collisions_are_rejected(self):
        created = self.archive.create_session("owner-a", "global-session")
        self.assertEqual(created["user_id"], "owner-a")
        self.assertTrue(self.archive.owns_session("owner-a", "global-session"))
        self.assertFalse(self.archive.owns_session("owner-b", "global-session"))

        with self.assertRaises(PermissionError):
            self.archive.ensure_session("owner-b", "global-session")
        with self.assertRaises(PermissionError):
            self.archive.record("owner-b", "global-session", "user", "intrusion")
        with self.assertRaises(ValueError):
            self.archive.create_session("owner-b", "global-session")
        self.assertEqual(self.archive.list_sessions("owner-b"), [])

    def test_record_turn_is_atomic_and_replay_survives_archive_restart(self):
        first = self.archive.record_turn(
            "user-a", "session-a", "hello", "welcome", "request-1",
            state={"risk": "low"}, route="support",
        )
        self.assertFalse(first["duplicate"])
        self.assertEqual(self.archive.count("user-a", "session-a"), 2)

        restarted = ChatArchive(self.db_path)
        replay = restarted.record_turn(
            "user-a", "session-a", "hello", "welcome", "request-1",
            state={"risk": "low"}, route="support",
        )
        messages = restarted.fetch_page("user-a", "session-a", limit=10)
        self.assertTrue(replay["duplicate"])
        self.assertEqual(replay["user_message_id"], first["user_message_id"])
        self.assertEqual(replay["assistant_message_id"], first["assistant_message_id"])
        self.assertEqual([(m.role, m.content) for m in messages],
                         [("user", "hello"), ("assistant", "welcome")])
        self.assertEqual([m.sequence_number for m in messages], [1, 2])

    def test_reusing_idempotency_key_with_different_payload_raises(self):
        self.archive.record_turn("user-a", "session-a", "one", "reply", "same-key")
        with self.assertRaises(ValueError):
            self.archive.record_turn(
                "user-a", "session-a", "different", "reply", "same-key"
            )
        self.assertEqual(self.archive.count("user-a", "session-a"), 2)

    def test_two_instances_allocate_contiguous_sequences_concurrently(self):
        other = ChatArchive(self.db_path)
        total = 48

        def write(index: int) -> int:
            archive = self.archive if index % 2 == 0 else other
            return archive.record(
                "thread-user", "thread-session", "user", f"message-{index}"
            ).sequence_number

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            allocated = list(pool.map(write, range(total)))

        stored = self.archive.fetch_page(
            "thread-user", "thread-session", limit=total + 1
        )
        expected = list(range(1, total + 1))
        self.assertEqual(sorted(allocated), expected)
        self.assertEqual([m.sequence_number for m in stored], expected)
        self.assertEqual(len({m.message_id for m in stored}), total)
        self.assertEqual({m.content for m in stored},
                         {f"message-{i}" for i in range(total)})

    def test_multiple_processes_cannot_duplicate_or_corrupt_turns(self):
        context = multiprocessing.get_context("spawn")
        results = context.Queue()
        processes = [
            context.Process(target=_process_write_turns,
                            args=(str(self.db_path), offset, 12, results))
            for offset in (0, 12)
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(30)
            self.assertFalse(process.is_alive(), "worker process deadlocked")
            self.assertEqual(process.exitcode, 0)
        self.assertEqual([results.get(timeout=5) for _ in processes], [None, None])

        messages = self.archive.fetch_page(
            "process-user", "process-session", limit=100)
        self.assertEqual(len(messages), 48)
        self.assertEqual([m.sequence_number for m in messages], list(range(1, 49)))
        self.assertEqual(len({m.message_id for m in messages}), 48)
        self.assertEqual(self.archive.count("process-user", "process-session"), 48)

    def test_write_failure_and_invalid_role_store_nothing(self):
        connection = sqlite3.connect(str(self.db_path))
        try:
            connection.executescript(
                """
                CREATE TRIGGER simulate_assistant_failure
                BEFORE INSERT ON chat_messages
                WHEN NEW.role = 'assistant'
                BEGIN
                    SELECT RAISE(ABORT, 'simulated write failure');
                END;
                """
            )
        finally:
            connection.close()

        with self.assertRaises(sqlite3.IntegrityError):
            self.archive.record_turn(
                "failure-user", "failure-session", "question", "answer", "failure-key"
            )
        self.assertEqual(self.archive.count("failure-user", "failure-session"), 0)
        self.assertIsNone(self.archive.get_request(
            "failure-user", "failure-session", "failure-key"
        ))
        self.assertEqual(self.archive.list_sessions("failure-user"), [])

        with self.assertRaises(ValueError):
            self.archive.record(
                "failure-user", "failure-session", "system", "not allowed"
            )
        self.assertEqual(self.archive.count("failure-user"), 0)

    def test_cache_clear_and_restart_do_not_remove_permanent_messages(self):
        self.archive.record_turn(
            "cache-user", "cache-session", "persist me", "still here", "cache-key"
        )
        context = ContextCache(cache_size=10, prompt_window=4)
        context.prime("cache-session", [
            Turn(role=m.role, content=m.content)
            for m in self.archive.fetch_recent("cache-user", "cache-session", 20)
        ])
        self.assertEqual(len(context.all_cached("cache-session")), 2)
        context.clear("cache-session")
        self.assertEqual(context.all_cached("cache-session"), [])

        restarted_archive = ChatArchive(self.db_path)
        permanent = restarted_archive.fetch_recent(
            "cache-user", "cache-session", 20
        )
        restarted_cache = ContextCache(cache_size=10, prompt_window=4)
        restarted_cache.prime("cache-session", [
            Turn(role=m.role, content=m.content) for m in permanent
        ])
        self.assertEqual([(m.role, m.content) for m in permanent],
                         [("user", "persist me"), ("assistant", "still here")])
        self.assertEqual([(t.role, t.content)
                          for t in restarted_cache.all_cached("cache-session")],
                         [("user", "persist me"), ("assistant", "still here")])

    def test_old_sessions_remain_discoverable_beyond_active_cache_size(self):
        context = ContextCache(cache_size=10, prompt_window=4)
        session_ids = [f"history-{i:02d}" for i in range(35)]
        for index, session_id in enumerate(session_ids):
            self.archive.record_turn(
                "history-user", session_id, f"old question {index}",
                f"old answer {index}", f"history-request-{index}",
            )
            context.append(session_id, "user", f"old question {index}")
        for session_id in session_ids:
            context.clear(session_id)

        recent = self.archive.recent_sessions(
            "history-user", limit=50, per_session=10
        )
        digests = self.archive.session_digests("history-user", limit=50)
        self.assertEqual({item["session_id"] for item in recent}, set(session_ids))
        self.assertEqual({item["session_id"] for item in digests}, set(session_ids))
        oldest_digest = next(
            item for item in digests if item["session_id"] == session_ids[0]
        )
        self.assertIn("old question 0", oldest_digest["text"])

    def test_safety_summary_and_counters_survive_restart(self):
        state = {
            "level": "elevated",
            "summary": "User reported recurring work stress.",
            "counters": {"injection": 2, "off_topic": 3},
        }
        self.archive.save_safety_state("state-user", "state-session", state)
        restarted = ChatArchive(self.db_path)
        restored = restarted.load_safety_state("state-user", "state-session")
        self.assertEqual(restored, state)

        cache = ContextCache()
        cache.set_safety_state("state-session", restored)
        cache.restore_counters("state-session", restored["counters"])
        cache.set_summary("state-session", restored["summary"])
        self.assertEqual(cache.safety_state("state-session"), state)
        self.assertEqual(cache.get_counters("state-session"), state["counters"])
        self.assertEqual(cache.summary("state-session"), state["summary"])

    def test_cross_user_reads_and_exports_return_nothing(self):
        self.archive.record_turn(
            "alice", "private-session", "alice secret", "alice reply", "private-key"
        )
        self.assertEqual(self.archive.fetch_recent("bob", "private-session", 20), [])
        self.assertEqual(self.archive.fetch_page("bob", "private-session", 0, 20), [])
        self.assertEqual(self.archive.count("bob", "private-session"), 0)
        self.assertEqual(self.archive.export_user("bob"), [])
        self.assertEqual(self.archive.list_sessions("bob"), [])
        self.assertEqual(self.archive.recent_sessions("bob", limit=20), [])
        self.assertEqual(self.archive.session_digests("bob", limit=20), [])
        self.assertIsNone(self.archive.get_request(
            "bob", "private-session", "private-key"
        ))
        self.assertEqual(self.archive.load_safety_state("bob", "private-session"), {})

    def test_session_deletion_removes_messages_idempotency_and_state(self):
        self.archive.record_turn(
            "delete-user", "delete-session", "erase", "erased", "delete-key",
            state={"summary": "must disappear", "counters": {"risk": 4}},
        )
        self.assertTrue(self.archive.delete_conversation(
            "delete-user", "delete-session"
        ))
        self.assertFalse(self.archive.delete_conversation(
            "delete-user", "delete-session"
        ))
        self.assertEqual(self.archive.fetch_recent(
            "delete-user", "delete-session", 20
        ), [])
        self.assertEqual(self.archive.count("delete-user", "delete-session"), 0)
        self.assertIsNone(self.archive.get_request(
            "delete-user", "delete-session", "delete-key"
        ))
        self.assertEqual(self.archive.load_safety_state(
            "delete-user", "delete-session"
        ), {})
        self.assertFalse(self.archive.owns_session(
            "delete-user", "delete-session"
        ))

    def test_user_deletion_removes_everything_and_tombstone_blocks_recreation(self):
        memory = LongTermMemorySQLite(self.db_path)
        memory.observe("revoked-user", "My name is Revoked")
        for index in range(2):
            self.archive.record_turn(
                "revoked-user", f"revoked-session-{index}", f"question {index}",
                f"answer {index}", f"revoked-key-{index}",
                state={"summary": f"summary {index}"},
            )
        self.assertEqual(self.archive.delete_user("revoked-user"), 4)
        self.assertTrue(self.archive.is_user_deleted("revoked-user"))
        self.assertEqual(memory.retrieve("revoked-user", "name"), [])
        with self.assertRaises(PermissionError):
            memory.observe("revoked-user", "My name is Resurrected")
        self.assertEqual(self.archive.export_user("revoked-user"), [])
        self.assertEqual(self.archive.list_sessions("revoked-user"), [])
        self.assertEqual(self.archive.session_digests("revoked-user"), [])
        for index in range(2):
            self.assertIsNone(self.archive.get_request(
                "revoked-user", f"revoked-session-{index}", f"revoked-key-{index}"
            ))
            self.assertEqual(self.archive.load_safety_state(
                "revoked-user", f"revoked-session-{index}"
            ), {})

        with self.assertRaises(PermissionError):
            self.archive.ensure_session("revoked-user", "replacement-session")
        with self.assertRaises(PermissionError):
            self.archive.record_turn(
                "revoked-user", "replacement-session", "new", "blocked", "new-key"
            )
        with self.assertRaises(PermissionError):
            self.archive.create_session("revoked-user", "replacement-session")


class LongTermMemorySQLiteLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "memory.sqlite3"
        self.memory = LongTermMemorySQLite(self.db_path, busy_timeout_ms=10_000)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _rows_for(self, user_id: str):
        connection = sqlite3.connect(str(self.db_path))
        try:
            return connection.execute(
                "SELECT text, kind FROM long_term_memories "
                "WHERE user_id = ? ORDER BY ordinal", (user_id,)
            ).fetchall()
        finally:
            connection.close()

    def test_memories_are_user_isolated_and_survive_restart(self):
        self.memory.observe("alice", "My name is Alice")
        self.memory.observe("bob", "My name is Bob")

        alice = self.memory.retrieve("alice", "")
        bob = self.memory.retrieve("bob", "")
        self.assertEqual([item.text for item in alice], ["User's name: Alice"])
        self.assertEqual([item.text for item in bob], ["User's name: Bob"])
        self.assertNotIn("Bob", " ".join(item.text for item in alice))
        self.assertNotIn("Alice", " ".join(item.text for item in bob))

        restarted = LongTermMemorySQLite(self.db_path)
        self.assertEqual([item.text for item in restarted.retrieve("alice", "")],
                         ["User's name: Alice"])
        self.assertEqual(restarted.retrieve("unknown-user", ""), [])

    def test_concurrent_observations_merge_atomically_and_remain_bounded(self):
        other = LongTermMemorySQLite(self.db_path, busy_timeout_ms=10_000)
        total = 60

        def observe(index: int) -> None:
            target = self.memory if index % 2 == 0 else other
            target.observe(
                "shared-user",
                f"I prefer artifact{index} color{index} hobby{index}",
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(observe, range(total)))

        rows = self._rows_for("shared-user")
        self.assertEqual(len(rows), 50)
        self.assertEqual(len({text for text, _kind in rows}), 50)
        self.assertTrue(all(kind == "preference" for _text, kind in rows))
        self.assertLessEqual(len(rows), 50)

    def test_forget_user_fully_removes_only_that_users_memory(self):
        self.memory.observe("forgotten", "My name is Forgettable")
        self.memory.observe("forgotten", "I prefer quiet forests and tea")
        self.memory.observe("retained", "My name is Remembered")
        self.assertGreater(len(self._rows_for("forgotten")), 0)

        self.memory.forget_user("forgotten")
        restarted = LongTermMemorySQLite(self.db_path)
        self.assertEqual(self._rows_for("forgotten"), [])
        self.assertEqual(restarted.retrieve("forgotten", ""), [])
        self.assertEqual([item.text for item in restarted.retrieve("retained", "")],
                         ["User's name: Remembered"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
