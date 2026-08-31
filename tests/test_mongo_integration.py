"""Opt-in real MongoDB replica-set, multi-process integration evidence.

Run with RUN_MONGO_INTEGRATION=1 and a disposable replica-set MONGO_URI.
No mock/mongomock path is accepted by this suite.
"""

from __future__ import annotations

import multiprocessing
import os
import unittest
import uuid

from pymongo import MongoClient

from app.config.settings import Settings
from app.memory.long_term_memory_mongo import LongTermMemoryMongo
from app.storage.chat_archive_mongo import ChatArchiveMongo


def _write_turns(uri: str, db_name: str, start: int, count: int, output) -> None:
    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    try:
        archive = ChatArchiveMongo(client[db_name])
        for index in range(start, start + count):
            archive.record_turn(
                "worker-user", "shared-session", f"question-{index}",
                f"answer-{index}", f"request-{index}",
            )
        output.put(None)
    except BaseException as exc:
        output.put(f"{type(exc).__name__}: {exc}")
    finally:
        client.close()


def _race_key(uri: str, db_name: str, content: str, ready, start, output) -> None:
    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    try:
        archive = ChatArchiveMongo(client[db_name])
        ready.put(True)
        start.wait(20)
        archive.record_turn(
            "race-user", "race-session", content, "reply", "one-key"
        )
        output.put((content, "committed"))
    except BaseException as exc:
        output.put((content, type(exc).__name__))
    finally:
        client.close()


def _write_memories(uri: str, db_name: str, start: int, count: int, output) -> None:
    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    try:
        memory = LongTermMemoryMongo(client[db_name])
        for index in range(start, start + count):
            memory.observe(
                "memory-user", f"I prefer artifact{index} color{index} hobby{index}",
                source_session_id=f"session-{index % 2}",
                source_message_id=f"message-{index}",
            )
        output.put(None)
    except BaseException as exc:
        output.put(f"{type(exc).__name__}: {exc}")
    finally:
        client.close()
@unittest.skipUnless(
    os.getenv("RUN_MONGO_INTEGRATION") == "1",
    "set RUN_MONGO_INTEGRATION=1 to run against a real replica set",
)
class RealMongoMultiWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings = Settings.from_env()
        if not settings.mongo_uri:
            raise unittest.SkipTest("MONGO_URI is not configured")
        cls.uri = settings.mongo_uri
        cls.db_name = f"soulene_audit_{uuid.uuid4().hex}"
        client = MongoClient(cls.uri, serverSelectionTimeoutMS=10000)
        hello = client.admin.command("hello")
        if not hello.get("setName"):
            client.close()
            raise unittest.SkipTest("MongoDB must be a real replica set")
        cls.replica_set = hello["setName"]
        client.close()

    @classmethod
    def tearDownClass(cls):
        client = MongoClient(cls.uri, serverSelectionTimeoutMS=10000)
        client.drop_database(cls.db_name)
        client.close()

    def test_multi_process_sequence_idempotency_and_fresh_client_durability(self):
        context = multiprocessing.get_context("spawn")
        output = context.Queue()
        workers = [
            context.Process(
                target=_write_turns,
                args=(self.uri, self.db_name, offset, 12, output),
            )
            for offset in (0, 12, 24, 36)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(60)
            self.assertFalse(worker.is_alive(), "Mongo worker deadlocked")
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual([output.get(timeout=10) for _ in workers], [None] * 4)

        # A wholly new client proves acknowledged writes outlive worker clients.
        fresh = MongoClient(self.uri, serverSelectionTimeoutMS=10000)
        archive = ChatArchiveMongo(fresh[self.db_name])
        messages = archive.fetch_page("worker-user", "shared-session", 0, 200)
        self.assertEqual(len(messages), 96)
        self.assertEqual([m.sequence_number for m in messages], list(range(1, 97)))
        self.assertEqual(len({m.message_id for m in messages}), 96)
        fresh.close()

    def test_conflicting_payload_race_rejects_loser(self):
        context = multiprocessing.get_context("spawn")
        ready, output, start = context.Queue(), context.Queue(), context.Event()
        workers = [
            context.Process(
                target=_race_key,
                args=(self.uri, self.db_name, content, ready, start, output),
            )
            for content in ("payload-a", "payload-b")
        ]
        for worker in workers:
            worker.start()
        for _ in workers:
            ready.get(timeout=20)
        start.set()
        for worker in workers:
            worker.join(60)
            self.assertEqual(worker.exitcode, 0)
        results = [output.get(timeout=10) for _ in workers]
        self.assertEqual(sorted(status for _, status in results),
                         ["ValueError", "committed"])
        client = MongoClient(self.uri, serverSelectionTimeoutMS=10000)
        archive = ChatArchiveMongo(client[self.db_name])
        self.assertEqual(archive.count("race-user", "race-session"), 2)
        stored = archive.get_request("race-user", "race-session", "one-key")
        winner = next(content for content, status in results if status == "committed")
        self.assertEqual(stored["user_content"], winner)
        client.close()
    def test_multi_process_memory_provenance_majority_durability_and_isolation(self):
        context = multiprocessing.get_context("spawn")
        output = context.Queue()
        workers = [
            context.Process(
                target=_write_memories,
                args=(self.uri, self.db_name, offset, 10, output),
            )
            for offset in (0, 10)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(60)
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual([output.get(timeout=10) for _ in workers], [None, None])

        fresh = MongoClient(self.uri, serverSelectionTimeoutMS=10000)
        db = fresh[self.db_name]
        rows = list(db["memory"].find({"user_id": "memory-user"}))
        self.assertEqual(len(rows), 20)
        self.assertTrue(all(row.get("sources") for row in rows))
        self.assertTrue(all(
            row.get("extraction_version") == "rules-v1" for row in rows
        ))
        self.assertEqual(list(db["memory"].find({"user_id": "attacker"})), [])
        archive = ChatArchiveMongo(db)
        self.assertEqual(archive.fetch_recent(
            "attacker", "shared-session", 100
        ), [])
        self.assertEqual(archive.session_digests("attacker", limit=100), [])
        fresh.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
