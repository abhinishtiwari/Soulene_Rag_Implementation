"""A fake LLM client for deterministic tests (no network).

- moderate(): always returns a clean signal.
- generate(): echoes back the retrieved knowledge it was given, plus a marker,
  so tests can assert that RAG context reached the model and that grounding
  instructions are present. The output-review pass returns the draft unchanged.
"""

from __future__ import annotations

from app.types import ModerationSignal


class FakeLLMClient:
    def __init__(self):
        self.calls = []

    def moderate(self, text: str) -> ModerationSignal:
        return ModerationSignal(flagged=False, categories={})

    def assess_risk(self, *, instructions: str, input_text: str, session_id: str):
        # Structured pre-response assessment. Deliberately not added to `calls`,
        # which tracks user-visible generation calls in performance tests.
        return {
            "semantic_intent": "ordinary_conversation",
            "emotional_state": "neutral",
            "emotional_trajectory": "stable",
            "self_harm_score": 0.0,
            "physical_danger_score": 0.0,
            "harm_to_others_score": 0.0,
            "emotional_distress_score": 0.0,
            "overall_score": 0.0,
            "hazards": [], "compound_factors": [], "evidence": [],
            "immediate_actions": [], "recommended_action": "normal",
            "intoxication_or_impairment": False, "access_to_means": False,
            "timing_immediate": False, "isolation": False,
            "farewell_or_finality": False, "hopelessness": False,
            "unsafe_framing": False, "prompt_injection": False,
            "danger_resolved": False, "uncertainty": 0.0,
        }

    def assess_output(self, *, user_message: str, reply: str, session_id: str):
        return {"category": "safe"}

    def generate(self, *, instructions: str, input_text: str, session_id: str,
                 temperature=None, max_output_tokens=None) -> str:
        self.calls.append({"instructions": instructions, "input": input_text,
                           "session": session_id})
        # Rolling-summary pass: the real model returns a narrative summary of the
        # overflow. Model that here by echoing the overflowed user text so tests
        # can assert the summary both exists and captures earlier topics.
        if session_id.endswith("_summary") or "summarize what this person" in instructions.lower():
            return "Earlier they talked about: " + input_text.replace("\n", " ")[:400]
        # Output-review pass: return the draft (last section) unchanged.
        if session_id.endswith(":review"):
            marker = "Draft reply:\n"
            if marker in input_text:
                return input_text.split(marker, 1)[1].split("\n\nReturn only", 1)[0].strip()
            return input_text
        # Crisis pass.
        if session_id.endswith(":crisis"):
            return "Hey, wait — I'm here with you. Where are you right now?"
        # Normal generation: surface whether knowledge was provided.
        if "KNOWLEDGE" in input_text:
            return "GROUNDED_ANSWER:: answered from the provided knowledge."
        return "NORMAL_ANSWER:: I hear you and I'm here with you."
