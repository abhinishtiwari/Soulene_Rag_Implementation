"""Deterministic, language-matched refusal messages."""

from __future__ import annotations

from app.types import Language


class RefusalHandler:
    def respond(self, reason: str, language: Language, distress: bool = False) -> str:
        if reason == "programming":
            return self._programming(language, distress)
        if reason == "sexual":
            return self._sexual(language)
        return self._harmful(language)

    def _programming(self, language: Language, distress: bool) -> str:
        if language == Language.HINDI:
            base = "मैं programming assistant नहीं हूँ, इसलिए code या technical instructions में मदद नहीं कर सकता।"
            return base + (" अगर इसका pressure तुम्हें थका रहा है, तो उस stress पर मैं तुम्हारे साथ बात कर सकता हूँ।" if distress else "")
        if language == Language.HINGLISH:
            base = "main programming assistant nahi hoon, isliye code ya technical instructions mein help nahi kar sakta."
            return base + (" agar iska pressure tumhe thaka raha hai, to us stress pe main tumhare saath baat kar sakta hoon." if distress else "")
        base = "I'm not a programming assistant, so I can't help with code, debugging, or technical instructions."
        return base + (" If the pressure around it is what's getting to you, I can help with that side." if distress else "")

    def _harmful(self, language: Language) -> str:
        if language == Language.HINDI:
            return "मैं किसी को नुकसान पहुँचाने, कानून तोड़ने, या dangerous instructions देने में मदद नहीं कर सकता।"
        if language == Language.HINGLISH:
            return "main kisi ko nuksan pahunchane, law todne, ya dangerous instructions dene mein help nahi kar sakta."
        return "I can't help with harming someone, breaking the law, or dangerous instructions."

    def _sexual(self, language: Language) -> str:
        if language in (Language.HINDI, Language.HINGLISH):
            return (
                "Main physical intimacy ya sex ke steps nahi de sakta. "
                "Main consent, respect, communication aur emotional connection par high-level baat kar sakta hoon."
            )
        return (
            "I can't help with steps or progression for physical intimacy or sex. "
            "I can help with high-level topics like respect, consent, communication, and emotional connection instead."
        )
