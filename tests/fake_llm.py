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

    def generate(self, *, instructions: str, input_text: str, session_id: str,
                 temperature=None, max_output_tokens=None) -> str:
        self.calls.append({"instructions": instructions, "input": input_text,
                           "session": session_id})
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
