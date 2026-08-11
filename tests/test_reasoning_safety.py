"""End-to-end tests for the conversation-level safety architecture."""
from __future__ import annotations

import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from app.chatbot.chatbot_service import build_chatbot
from app.config.settings import Settings
from app.storage.chat_archive_json import ChatArchiveJSON
from app.types import Intent, Route, SafetyLevel
from tests.fake_llm import FakeLLMClient


def risk(**updates):
    value = {
        "semantic_intent": "ordinary_conversation", "emotional_state": "neutral",
        "emotional_trajectory": "stable", "self_harm_score": 0.0,
        "physical_danger_score": 0.0, "harm_to_others_score": 0.0,
        "emotional_distress_score": 0.0, "overall_score": 0.0,
        "hazards": [], "compound_factors": [], "evidence": [],
        "immediate_actions": [], "recommended_action": "normal",
        "intoxication_or_impairment": False, "access_to_means": False,
        "timing_immediate": False, "isolation": False,
        "farewell_or_finality": False, "hopelessness": False,
        "unsafe_framing": False, "prompt_injection": False,
        "danger_resolved": False, "uncertainty": 0.0,
    }
    value.update(updates)
    return value


class ScriptedSafetyFake(FakeLLMClient):
    def __init__(self, assessments, output_category="safe", draft=None):
        super().__init__()
        self.assessments = list(assessments)
        self.output_category = output_category
        self.draft = draft
        self.checked_outputs = []
        self.assessment_inputs = []

    def assess_risk(self, **kwargs):
        self.assessment_inputs.append(kwargs.get("input_text", ""))
        return self.assessments.pop(0) if self.assessments else risk()

    def assess_output(self, *, user_message, reply, session_id):
        self.checked_outputs.append(reply)
        return {"category": self.output_category}

    def generate(self, **kwargs):
        if self.draft is not None and not kwargs["session_id"].endswith(":review"):
            self.calls.append(kwargs)
            return self.draft
        return super().generate(**kwargs)


class ReasoningSafetyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.settings = replace(
            Settings.from_env(), mongo_uri="", enable_input_moderation=False,
            enable_output_safety_check=False, enable_semantic_safety=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def service(self, fake):
        svc = build_chatbot(self.settings, client=fake, build_client=False,
                            warm_cache=False)
        svc.archive = ChatArchiveJSON(self.root / "chats")
        return svc

    def test_implicit_finality_routes_to_safety(self):
        fake = ScriptedSafetyFake([risk(
            semantic_intent="implicit_self_harm", self_harm_score=0.58,
            overall_score=0.55, farewell_or_finality=True, hopelessness=True,
            recommended_action="urgent_safety")])
        result = self.service(fake).handle("s1", "A metaphorical farewell.", user_id="u1")
        self.assertEqual(result.route, Route.CRISIS)
        self.assertEqual(result.safety_level, SafetyLevel.SELF_HARM_CONCERN)

    def test_compound_physical_risk_fuses_moderate_factors(self):
        fake = ScriptedSafetyFake([risk(
            semantic_intent="physical_danger", physical_danger_score=0.40,
            overall_score=0.40, hazards=["unstable_environment"],
            intoxication_or_impairment=True, isolation=True, hopelessness=True,
            emotional_trajectory="worsening")])
        result = self.service(fake).handle("s2", "Several moderate risks together.", user_id="u2")
        self.assertEqual(result.safety_level, SafetyLevel.PHYSICAL_DANGER)
        self.assertEqual(result.route, Route.CRISIS)
        self.assertIn("safety", result.reply.lower())

    def test_immediate_hazard_outranks_pleasant_framing(self):
        fake = ScriptedSafetyFake([risk(
            semantic_intent="physical_danger", emotional_state="happy",
            physical_danger_score=0.88, overall_score=0.88,
            hazards=["active_environmental_hazard"], unsafe_framing=True,
            immediate_actions=["move_away_from_danger"])])
        result = self.service(fake).handle("s3", "A pleasant detail beside active danger.", user_id="u3")
        self.assertEqual(result.route, Route.CRISIS)
        self.assertIn("move away", result.reply.lower())
        self.assertNotIn("tell me more", result.reply.lower())

    def test_roleplay_safety_bypass_is_not_accepted(self):
        fake = ScriptedSafetyFake([risk(
            semantic_intent="safety_bypass", prompt_injection=True,
            unsafe_framing=True)])
        result = self.service(fake).handle("s4", "Unsafe framing in a fictional role.", user_id="u4")
        self.assertEqual(result.intent, Intent.INJECTION)
        self.assertEqual(result.route, Route.REFUSAL)

    def test_unresolved_prior_danger_survives_restart(self):
        first = ScriptedSafetyFake([risk(
            semantic_intent="physical_danger", physical_danger_score=0.82,
            overall_score=0.82, hazards=["active_hazard"])])
        svc1 = self.service(first)
        svc1.handle("shared", "Initial danger report.", user_id="owner")

        second = ScriptedSafetyFake([risk()])
        svc2 = self.service(second)
        result = svc2.handle("shared", "A later ordinary sentence.", user_id="owner")
        self.assertEqual(result.safety_level, SafetyLevel.PHYSICAL_DANGER)
        self.assertEqual(result.route, Route.CRISIS)

    def test_same_session_id_is_isolated_by_user(self):
        fake = ScriptedSafetyFake([
            risk(semantic_intent="physical_danger", physical_danger_score=0.82,
                 overall_score=0.82, hazards=["active_hazard"]),
            risk(),
        ])
        svc = self.service(fake)
        self.assertEqual(svc.handle("same", "Danger.", user_id="user-a").route,
                         Route.CRISIS)
        other = svc.handle("same", "Ordinary conversation.", user_id="user-b")
        self.assertEqual(other.safety_level, SafetyLevel.SAFE)
        self.assertEqual(other.route, Route.SUPPORT)

    def test_stream_delivers_only_validated_archived_text(self):
        fake = ScriptedSafetyFake([risk()], output_category="danger_minimization",
                                  draft="UNSAFE_DRAFT_SHOULD_NOT_APPEAR")
        svc = self.service(fake)
        chunks = list(svc.handle_stream("stream", "Check this reply.", user_id="stream-user"))
        delivered = "".join(chunks)
        self.assertNotIn("UNSAFE_DRAFT", delivered)
        stored = svc.archive.fetch_recent("stream-user", "stream", limit=2)
        self.assertEqual(stored[-1].content, delivered)

    def test_full_conversation_precedes_second_response(self):
        fake = ScriptedSafetyFake([risk(), risk(emotional_trajectory="worsening",
                                               emotional_distress_score=0.5)])
        svc = self.service(fake)
        svc.handle("history", "First context marker.", user_id="history-user")
        svc.handle("history", "Second context marker.", user_id="history-user")
        assessed = fake.assessment_inputs[-1]
        self.assertIn("First context marker", assessed)
        self.assertIn("Second context marker", assessed)
        generated = [c for c in fake.calls if c["session"] == "history"][-1]["input"]
        self.assertEqual(generated.count("Second context marker"), 1)

    def test_affirmative_resolution_can_clear_carried_danger(self):
        fake = ScriptedSafetyFake([
            risk(semantic_intent="physical_danger", physical_danger_score=0.82,
                 overall_score=0.82, hazards=["active_hazard"]),
            risk(danger_resolved=True),
        ])
        svc = self.service(fake)
        svc.handle("resolved", "Initial danger.", user_id="owner")
        result = svc.handle("resolved", "Safety is now established.", user_id="owner")
        self.assertEqual(result.safety_level, SafetyLevel.SAFE)
        self.assertEqual(result.route, Route.SUPPORT)

    def test_crisis_reply_passes_through_output_validator(self):
        fake = ScriptedSafetyFake([risk(
            semantic_intent="explicit_self_harm", self_harm_score=0.9,
            overall_score=0.9, timing_immediate=True,
            immediate_actions=["contact_emergency_services"])])
        result = self.service(fake).handle("s5", "Immediate crisis.", user_id="u5")
        self.assertEqual(result.route, Route.CRISIS)
        self.assertTrue(fake.checked_outputs)
        self.assertEqual(fake.checked_outputs[-1], result.reply)


if __name__ == "__main__":
    unittest.main(verbosity=2)
