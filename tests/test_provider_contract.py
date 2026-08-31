"""ISSUE-032: offline contract tests for external dependencies.

The live suites (`smoke_live.py`, `smoke_staging.py`, `test_mongo_integration.py`)
need real credentials, networking and destructive database access, so they cannot
run in ordinary CI. Their value is in the *contracts* they exercise, and those
contracts can be pinned offline with fakes that mimic the provider's shapes.

What this file does NOT do: prove the real provider or a real replica set
behaves this way. That remains an external gate. It proves that when a provider
returns these shapes, Soulene handles them correctly — which is what actually
regressed in the past.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from app.config.settings import Settings
from app.llm.client import BudgetExhausted, LLMClient, LLMError
from app.types import ModerationSignal


class _Response:
    def __init__(self, text):
        self.output_text = text


class _Responses:
    def __init__(self, behaviour):
        self._behaviour = behaviour
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._behaviour(kwargs)


class _FakeProvider:
    """Mimics the shape of the OpenAI SDK surface Soulene actually uses."""

    def __init__(self, behaviour):
        self.responses = _Responses(behaviour)
        self.moderations = self


def _client(behaviour, **settings_updates):
    settings = replace(Settings.from_env(), max_retries=1,
                       request_timeout_seconds=1.0, **settings_updates)
    return LLMClient(settings, client=_FakeProvider(behaviour))


class GenerationContractTests(unittest.TestCase):
    def test_normal_response_text_is_returned_stripped(self):
        client = _client(lambda kwargs: _Response("  hello there  "))
        self.assertEqual(
            client.generate(instructions="i", input_text="t", session_id="s"),
            "hello there")

    def test_empty_output_is_returned_as_empty_not_none(self):
        client = _client(lambda kwargs: _Response(None))
        self.assertEqual(
            client.generate(instructions="i", input_text="t", session_id="s"), "")

    def test_provider_errors_surface_as_llm_error(self):
        def explode(kwargs):
            raise RuntimeError("provider 500")

        client = _client(explode)
        with self.assertRaises(LLMError):
            client.generate(instructions="i", input_text="t", session_id="s")

    def test_required_request_fields_are_sent(self):
        client = _client(lambda kwargs: _Response("ok"))
        client.generate(instructions="INSTR", input_text="INPUT", session_id="sid")
        sent = client._client.responses.calls[-1]
        self.assertEqual(sent["instructions"], "INSTR")
        self.assertEqual(sent["input"], "INPUT")
        self.assertEqual(sent["user"], "sid")
        # Provider-side retention must stay disabled (ISSUE-028).
        self.assertFalse(sent["store"])

    def test_budget_exhaustion_is_distinguishable_from_a_provider_error(self):
        client = _client(lambda kwargs: _Response("ok"), model_daily_call_budget=1)
        client.generate(instructions="i", input_text="t", session_id="s")
        with self.assertRaises(BudgetExhausted):
            client.generate(instructions="i", input_text="t", session_id="s")


class ModerationContractTests(unittest.TestCase):
    def test_moderation_shape_is_parsed(self):
        class _Result:
            def __init__(self):
                self.flagged = True
                self.categories = type("C", (), {
                    "model_dump": lambda self: {"self_harm": True, "violence": False}
                })()

        class _ModerationResponse:
            results = [_Result()]

        class _Provider(_FakeProvider):
            def __init__(self):
                super().__init__(lambda kwargs: _Response("ok"))

            def create(self, **kwargs):
                return _ModerationResponse()

        settings = replace(Settings.from_env(), max_retries=1)
        client = LLMClient(settings, client=_Provider())
        signal = client.moderate("some text")
        self.assertIsInstance(signal, ModerationSignal)
        self.assertTrue(signal.flagged)
        self.assertTrue(signal.any_true("self_harm"))

    def test_moderation_failure_fails_open_with_the_error_recorded(self):
        """Moderation is one signal among several, so it must not block a turn.

        The deterministic guardrail floor stays authoritative (ISSUE-006/008),
        so an unavailable moderation service returns an unflagged signal that
        records the failure rather than raising into the pipeline.
        """
        class _Provider(_FakeProvider):
            def __init__(self):
                super().__init__(lambda kwargs: _Response("ok"))

            def create(self, **kwargs):
                raise RuntimeError("moderation unavailable")

        settings = replace(Settings.from_env(), max_retries=1)
        client = LLMClient(settings, client=_Provider())
        signal = client.moderate("text")
        self.assertFalse(signal.flagged)
        self.assertTrue(signal.error)
        self.assertFalse(signal.any_true("self_harm"))


class StorageContractTests(unittest.TestCase):
    """Pins the archive contract that the real-Mongo suite also asserts."""

    def test_sqlite_and_mongo_expose_the_same_archive_surface(self):
        from app.storage.chat_archive import ChatArchive
        from app.storage.chat_archive_mongo import ChatArchiveMongo
        required = (
            "record_turn", "get_request", "fetch_recent", "fetch_page", "count",
            "save_safety_state", "load_safety_state", "owns_session",
            "ensure_session", "create_session", "list_sessions",
            "delete_conversation", "delete_user", "is_user_deleted",
            "recent_sessions", "session_digests", "healthcheck",
            "purge_expired", "start_deletion_job", "record_deletion_step",
            "finish_deletion_job", "deletion_job", "claim_retention_run",
        )
        for name in required:
            with self.subTest(method=name):
                self.assertTrue(hasattr(ChatArchive, name),
                                f"SQLite archive missing {name}")
                self.assertTrue(hasattr(ChatArchiveMongo, name),
                                f"Mongo archive missing {name}")

    def test_memory_backends_expose_the_same_surface(self):
        from app.memory.long_term_memory import LongTermMemory
        from app.memory.long_term_memory_mongo import LongTermMemoryMongo
        from app.memory.long_term_memory_sqlite import LongTermMemorySQLite
        for name in ("observe", "retrieve", "contradiction_topics",
                     "forget_user", "forget_session"):
            for backend in (LongTermMemory, LongTermMemorySQLite,
                            LongTermMemoryMongo):
                with self.subTest(method=name, backend=backend.__name__):
                    self.assertTrue(hasattr(backend, name))
        # purge_expired is required of the durable backends (ISSUE-017).
        for backend in (LongTermMemorySQLite, LongTermMemoryMongo):
            self.assertTrue(hasattr(backend, "purge_expired"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
