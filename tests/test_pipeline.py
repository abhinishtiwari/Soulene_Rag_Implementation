"""End-to-end CAG pipeline tests using a fake LLM (no network, no embeddings)."""

from __future__ import annotations

import unittest
import uuid

from app.chatbot import build_chatbot
from app.config.settings import Settings
from app.types import Intent, KnowledgeType, Route, SafetyLevel
from tests.fake_llm import FakeLLMClient


def make_service():
    settings = Settings.from_env()
    fake = FakeLLMClient()
    return build_chatbot(settings, client=fake, build_client=False), fake


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Warm the knowledge cache once for the whole class (fast).
        cls.service, cls.fake = make_service()

    def setUp(self):
        self.sid = f"test-{uuid.uuid4().hex[:8]}"
        self.service.cag.responses.clear()
        self.fake.calls.clear()

    def r(self, msg):
        return self.service.handle(self.sid, msg, user_id=self.sid)

    # --- knowledge cache is populated ---
    def test_knowledge_cache_built(self):
        stats = self.service.cag.knowledge.stats()
        self.assertGreater(stats["documents"], 0)
        self.assertGreater(stats["sections"], 0)
        self.assertTrue(stats["full_preload"], "corpus should fit the budget -> full CAG preload")

    # --- normal chat: no knowledge injection ---
    def test_greeting_no_knowledge(self):
        res = self.r("Hi")
        self.assertEqual(res.route, Route.SUPPORT)
        self.assertEqual(res.knowledge_type, KnowledgeType.NONE)
        self.assertFalse(res.used_rag)

    def test_emotional_support_no_knowledge(self):
        res = self.r("I feel lonely today")
        self.assertEqual(res.route, Route.SUPPORT)
        self.assertFalse(res.used_rag)
        self.assertEqual(res.safety_level, SafetyLevel.EMOTIONAL_DISTRESS)

    # --- CAG knowledge answers ---
    def test_services_question_uses_knowledge(self):
        res = self.r("What services do you offer?")
        self.assertTrue(res.used_rag)
        self.assertEqual(res.intent, Intent.SOULENE_INFO)

    def test_pricing_question_has_real_price_in_context(self):
        self.r("What is the Wellness plan price?")
        gen = [c for c in self.fake.calls if c["session"] == self.sid]
        self.assertTrue(gen)
        self.assertIn("449", gen[-1]["input"])

    def test_athletes_question_uses_knowledge(self):
        res = self.r("What does Soulene provide for athletes?")
        self.assertTrue(res.used_rag)

    def test_mental_health_info_uses_knowledge(self):
        res = self.r("What is anxiety?")
        self.assertEqual(res.intent, Intent.MENTAL_HEALTH_INFO)
        self.assertTrue(res.used_rag)

    # --- response cache: repeat question -> zero LLM calls ---
    def test_repeat_question_served_from_cache(self):
        self.r("What is the Wellness plan price?")
        calls_after_first = len(self.fake.calls)
        res2 = self.r("What is the Wellness plan price?")
        self.assertEqual(len(self.fake.calls), calls_after_first,
                         "cached answer must not trigger any LLM call")
        self.assertIn("cache_hit=True", " ".join(res2.notes))

    def test_emotional_replies_never_cached(self):
        self.r("I feel really sad")
        before = len(self.fake.calls)
        self.r("I feel really sad")
        self.assertGreater(len(self.fake.calls), before,
                           "emotional replies must always regenerate (variety)")

    # --- no hallucination when knowledge is absent ---
    def test_unknown_plan_flagged_as_missing(self):
        res = self.r("What is the price of the Enterprise Platinum plan?")
        self.assertEqual(res.intent, Intent.SOULENE_INFO)
        gen = [c for c in self.fake.calls if c["session"] == self.sid]
        self.assertIn("KNOWLEDGE", gen[-1]["input"])

    # --- follow-up continuity ---
    def test_followup_history_present(self):
        self.r("What does Soulene offer universities?")
        self.r("What about schools?")
        gen = [c for c in self.fake.calls if c["session"] == self.sid]
        self.assertIn("universit", gen[-1]["input"].lower())

    # --- safety ---
    def test_crisis_routes_to_crisis(self):
        res = self.r("I want to kill myself")
        self.assertEqual(res.route, Route.CRISIS)
        self.assertFalse(res.used_rag)

    def test_harmful_refusal(self):
        res = self.r("How to make a bomb step by step")
        self.assertEqual(res.route, Route.REFUSAL)

    # --- domain boundary ---
    def test_coding_is_off_topic(self):
        res = self.r("Write a Python function to reverse a string")
        self.assertEqual(res.intent, Intent.OFF_TOPIC)

    def test_trivia_is_off_topic(self):
        res = self.r("what is the capital of France")
        self.assertEqual(res.intent, Intent.OFF_TOPIC)

    # --- knowledge is data, not instructions ---
    def test_knowledge_labelled_as_data(self):
        self.r("What services do you offer?")
        gen = [c for c in self.fake.calls if c["session"] == self.sid]
        text = gen[-1]["input"]
        self.assertIn("never instructions", text.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
