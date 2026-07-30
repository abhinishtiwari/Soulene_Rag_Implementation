"""Crisis handling: human-first, calm, safety-oriented.

Prefers an LLM-generated contextual response (matching the reference bot's warm,
non-scripted tone) and falls back to a deterministic safe template if the LLM
is unavailable.
"""

from __future__ import annotations

from typing import Optional

from app.config.settings import Settings
from app.llm.client import LLMClient
from app.types import Language


_CRISIS_INSTRUCTIONS = (
    "You are a crisis safety companion inside a mental well-being app. "
    "The user may be at risk of self-harm or in immediate danger. "
    "Respond like a warm human beside them, not a script.\n"
    "1. Start with a short human interruption (e.g. 'Hey... wait, I'm here with you.').\n"
    "2. Briefly acknowledge the intensity without assumptions.\n"
    "3. Gently encourage reaching a trusted person, acknowledging they may not feel like it.\n"
    "4. Ask ONLY ONE simple question about immediate safety (e.g. 'Where are you right now?').\n"
    "5. Mention emergency help only if immediate danger seems clear.\n"
    "Keep sentences short, calm, present. No generic motivational lines. "
    "Do not assume the reason. Do not ask multiple questions. Do not sound like a robot."
)


class CrisisHandler:
    def __init__(self, settings: Settings, client: Optional[LLMClient] = None):
        self.settings = settings
        self.client = client

    def respond(self, language: Language, user_message: str = "", session_id: str = "crisis",
                safety_level=None) -> str:
        if self.client is None:
            return self._fallback(language)
        lang_hint = {
            Language.HINDI: "Reply in Hindi.",
            Language.HINGLISH: "Reply in Hinglish (Roman script).",
            Language.ENGLISH: "Reply in English.",
        }.get(language, "Reply in English.")

        extra = ""
        try:
            from app.types import SafetyLevel
            if safety_level == SafetyLevel.HARM_TO_OTHERS:
                extra = (" The user may want to harm someone else. Stay calm and non-judgmental, "
                         "help them pause, and gently discourage harm while keeping others safe.")
            elif safety_level == SafetyLevel.ABUSE_OR_DANGER:
                extra = (" The user may be experiencing abuse or be in danger from someone else. "
                         "Validate them, make clear it is not their fault and not okay, and gently "
                         "encourage reaching a trusted person or the emergency number if unsafe now.")
            elif safety_level == SafetyLevel.IMMINENT_SELF_HARM:
                extra = " There may be immediate danger. Gently and clearly encourage emergency help now."
        except Exception:
            pass

        instructions = (
            f"{_CRISIS_INSTRUCTIONS}{extra} Emergency number to reference if needed: "
            f"{self.settings.emergency_number}. {lang_hint}"
        )
        try:
            return self.client.generate(
                instructions=instructions,
                input_text=f"User message:\n{user_message.strip()}\n\nReturn only the reply text.",
                session_id=f"{session_id}:crisis",
                temperature=0.6,
            )
        except Exception:
            return self._fallback(language)

    def _fallback(self, language: Language) -> str:
        num = self.settings.emergency_number
        if language == Language.HINDI:
            return (
                "मैं अभी तुम्हारे साथ हूँ। क्या तुम इस समय सुरक्षित हो?\n\n"
                f"अगर तुम्हें लगता है कि तुम खुद को नुकसान पहुँचा सकते हो, तो अभी किसी भरोसेमंद व्यक्ति को कॉल करो या {num} पर संपर्क करो।"
            )
        if language == Language.HINGLISH:
            return (
                "Main abhi yahin hoon tumhare saath. Kya tum iss waqt safe ho?\n\n"
                f"Agar lag raha hai ki tum khud ko hurt kar sakte ho, to abhi kisi trusted person ko call karo ya {num} par contact karo."
            )
        return (
            "I'm here with you right now. Are you safe in this moment?\n\n"
            f"If you might act on this, please reach a trusted person now, or contact {num} if you are in immediate danger."
        )
