"""Output safety pass: screen/repair a generated reply before it reaches the user."""

from __future__ import annotations

import json
import random
import re
from typing import Optional

from app.config.settings import Settings
from app.llm.client import LLMClient
from app.prompts.system_prompt import (
    OUTPUT_REVIEW_SYSTEM_PROMPT,
    build_output_review_input,
)
from app.safety.crisis import CrisisHandler
from app.safety.guardrails import Guardrails
from app.safety.refusal import RefusalHandler
from app.types import Language, ModerationSignal, RiskAssessment, SafetyLevel


class ResponseBuilder:
    def __init__(self, settings: Settings, guardrails: Guardrails,
                 refusal: RefusalHandler, crisis: CrisisHandler,
                 client: Optional[LLMClient]):
        self.settings = settings
        self.guardrails = guardrails
        self.refusal = refusal
        self.crisis = crisis
        self.client = client

    # Detect accidental leakage of internal instructions in the OUTPUT.
    _LEAK = re.compile(
        r"(system prompt|my (hidden )?instructions|according to my (system|prompt|rules)"
        r"|my system (says|policy)|response strategy for this message|base_system_prompt"
        r"|i was instructed to|my configuration|internal (only|rules))",
        re.I,
    )

    def scrub_leak(self, reply: str, language: Language) -> str:
        if self._LEAK.search(reply or ""):
            if language in (Language.HINDI, Language.HINGLISH):
                return "Main apne internal setup ke baare mein baat nahi kar sakta, but tumhari help zaroor kar sakta hoon. Kya chal raha hai?"
            return "I can't share details about how I work internally, but I'm here to help you. What's on your mind?"
        return reply

    # ------------------------------------------------------------------
    # Domain boundary enforcement (deterministic backstop).
    # If the model answered an off-topic technical question anyway, replace it.
    # ------------------------------------------------------------------
    _TECHNICAL_ANSWER = re.compile(
        r"(```|\bdef \w+\(|\bprint\s*\(|\bconsole\.log|\bimport \w+"
        r"|\b(variable|syntax|function|integer|string literal|compiler|indentation"
        r"|assign(?:ing|ment)?|data type|boolean|array|loop|semicolon)\b"
        r"|\bthe (?:answer|result) is\s*[-\d]"
        r"|\bcapital of \w+ is\b)",
        re.I,
    )

    _REDIRECTS_EN = [
        "Ha, that one's outside my lane — I'm your wellbeing corner, not your code editor. "
        "Anything on your mind I can actually help with?",
        "That's not really my thing, I'm afraid. But if something's stressing you out behind it, "
        "I'm all ears.",
        "I'll leave that one to the tech folks. What I'm good at is how you're doing — how's your day been?",
    ]
    _REDIRECTS_HI = [
        "Yeh mera area nahi hai honestly. Par agar iske peeche koi stress chal raha hai, "
        "to woh main zaroor sun sakta hoon.",
        "Isme main help nahi kar paunga, but tumhara mood kaisa hai aaj? Wahan main saath de sakta hoon.",
    ]

    def enforce_domain(self, reply: str, language: Language) -> str:
        """Called only when the analyzer classified the turn as off-topic."""
        if not reply or not self._TECHNICAL_ANSWER.search(reply):
            return reply
        pool = self._REDIRECTS_HI if language in (Language.HINDI, Language.HINGLISH) else self._REDIRECTS_EN
        return random.choice(pool)

    # ------------------------------------------------------------------
    # Competitor / other-app guard (legacy WALL 2 + WALL 3).
    # Soulene must never describe or recommend a rival product.
    # ------------------------------------------------------------------
    _COMPETITOR_APP = re.compile(
        r"\b(headspace|calm\s+app|moodfit|betterhelp|talkspace|sanvello|woebot"
        r"|insight\s*timer|reflectly|daylio|wysa|youper|happify|mindshift|pacifica"
        r"|minddoc|betterme|cerebral|7\s*cups|moodpath|finch|stoic|waking\s*up"
        r"|ten\s*percent|simple\s*habit|noom|fabulous)\b",
        re.I,
    )
    _APP_DESCRIPTION = re.compile(
        r"\b(is (an?|the) app (that|which|designed|focused|built)"
        r"|app (offers|provides|helps|features|includes)"
        r"|features? (include|are)"
        r"|download (it|the app) from"
        r"|available on (the )?(play store|app store))\b",
        re.I,
    )

    # Several variants so a repeated boundary never reads word-for-word identical.
    _OTHER_APP_DEFLECT = {
        Language.ENGLISH: [
            "I'm not really the one to ask about that one. I'm here for your wellbeing though — "
            "anything going on I can help with?",
            "Other apps aren't my area, honestly. But how you're doing is — what's on your mind?",
            "I'll stay out of that comparison. I'd rather hear how you've been feeling lately.",
        ],
        Language.HINGLISH: [
            "Us app ke baare mein mujhe zyada nahi pata. Par tumhara mood kaisa hai — wahan main "
            "saath de sakta hoon.",
            "Doosre apps mera area nahi hai. Batao, kya chal raha hai tumhare mind mein?",
        ],
        Language.HINDI: [
            "मुझे उस app के बारे में ज़्यादा जानकारी नहीं है। मैं यहाँ आपकी wellbeing के लिए हूँ — "
            "क्या कुछ ऐसा है जिसमें मैं मदद कर सकूँ?",
            "दूसरे apps पर मैं बात नहीं कर पाऊँगा। पर आप कैसा महसूस कर रहे हैं, वो सुनना चाहूँगा।",
        ],
    }

    def _deflect(self, language: Language) -> str:
        pool = self._OTHER_APP_DEFLECT.get(language) or self._OTHER_APP_DEFLECT[Language.ENGLISH]
        return random.choice(pool)

    def enforce_no_other_apps(self, reply: str, language: Language) -> str:
        """Replace the reply if it names or describes a non-Soulene app."""
        if not reply:
            return reply
        if self._COMPETITOR_APP.search(reply):
            return self._deflect(language)
        # Generic app-description language that isn't about Soulene.
        if self._APP_DESCRIPTION.search(reply) and "soulene" not in reply.lower():
            return self._deflect(language)
        return reply

    # ------------------------------------------------------------------
    # Helpline numbers must NEVER be invented. Models happily hallucinate
    # foreign hotlines (e.g. US 988), which is dangerous for an Indian user.
    # ------------------------------------------------------------------
    _FOREIGN_HELPLINE = re.compile(
        r"\b(988|1-?800-?273-?8255|800-?273-?TALK|116\s?123|1-?833-?456-?4566"
        r"|13\s?11\s?14|0800\s?\d{3}\s?\d{3,4})\b",
        re.I,
    )

    def enforce_helpline_number(self, reply: str, language: Language,
                                emergency_number: str) -> str:
        """Replace any invented hotline with the configured emergency number."""
        if not reply or not self._FOREIGN_HELPLINE.search(reply):
            return reply
        return self._FOREIGN_HELPLINE.sub(emergency_number, reply)

    def helpline_reply(self, language: Language, emergency_number: str) -> str:
        """Deterministic, warm helpline answer — the number is never model-generated."""
        if language == Language.HINDI:
            return (f"आपातकालीन मदद के लिए {emergency_number} पर कॉल करें। "
                    "और मैं भी यहीं हूँ — बताइए क्या चल रहा है?")
        if language == Language.HINGLISH:
            return (f"Emergency help ke liye {emergency_number} par call kar sakte ho. "
                    "Aur main bhi yahin hoon — batao kya chal raha hai?")
        return (f"For urgent help you can call {emergency_number}. "
                "And I'm right here too — do you want to tell me what's going on?")

    # ------------------------------------------------------------------
    # Medical-promo guard (legacy WALL 0). A distressed user asking about
    # medication must never receive plans/pricing/feature marketing.
    # ------------------------------------------------------------------
    _PROMO_SIGNALS = (
        "wellness plan", "mentor plan", "basic plan", "₹449", "₹4999", "449/month",
        "4999/month", "play store", "app store", "soulene.org", "download soulene",
        "progress tracking", "focus games", "my zone", "goal planning", "subscription",
    )

    def is_medical_promo(self, reply: str) -> bool:
        low = (reply or "").lower()
        return sum(1 for s in self._PROMO_SIGNALS if s in low) >= 2

    def enforce_no_promo(self, reply: str, language: Language) -> str:
        """Strip promotional content from a medication/distress reply."""
        if not self.is_medical_promo(reply):
            return reply
        # Drop the promotional sentences, keep the human ones.
        sentences = re.split(r"(?<=[.!?])\s+", reply)
        kept = [s for s in sentences
                if not any(sig in s.lower() for sig in self._PROMO_SIGNALS)]
        cleaned = " ".join(kept).strip()
        if len(cleaned) >= 40:
            return cleaned
        if language in (Language.HINDI, Language.HINGLISH):
            return ("Main doctor nahi hoon, isliye koi medicine suggest nahi kar sakta. "
                    "Par batao kya chal raha hai — main sunna chahta hoon, aur saath mil kar "
                    "dekhte hain kya madad kar sakti hai.")
        return ("I'm not a doctor, so I can't suggest anything like that. But tell me what's "
                "been going on — I'd rather understand what you're carrying and figure out "
                "what actually helps.")

    def apply_output_safety(self, *, session_id: str, user_message: str, reply: str,
                            language: Language,
                            risk_assessment: Optional[RiskAssessment] = None) -> str:
        """Validate the exact text that will be delivered and archived."""
        reply = self.scrub_leak(reply, language)

        # Optional style/policy editor runs before the mandatory final checks.
        if self.settings.enable_output_safety_check and self.client is not None:
            try:
                edited = self.client.generate(
                    instructions=OUTPUT_REVIEW_SYSTEM_PROMPT,
                    input_text=build_output_review_input(user_message, reply),
                    session_id=f"{session_id}:review", temperature=0.0,
                    max_output_tokens=self.settings.max_output_tokens,
                )
                reply = edited or reply
            except Exception:
                pass

        moderation = ModerationSignal()
        if self.settings.enable_input_moderation and self.client is not None:
            try:
                moderation = self.client.moderate(reply)
            except Exception:
                pass
        category = self.guardrails.classify_output(reply, moderation)
        if category == "crisis":
            return self.crisis.respond(
                language, user_message, session_id,
                safety_level=(risk_assessment.safety_level if risk_assessment else None),
                assessment=risk_assessment)
        if category == "harmful":
            return self.refusal.respond("harmful", language)

        semantic_category = self._semantic_output_category(
            session_id, user_message, reply)
        if semantic_category == "self_harm_encouragement":
            return self.crisis.respond(
                language, user_message, session_id,
                safety_level=(risk_assessment.safety_level if risk_assessment else None),
                assessment=risk_assessment)
        if semantic_category == "danger_minimization":
            level = (risk_assessment.safety_level if risk_assessment
                     else SafetyLevel.PHYSICAL_DANGER)
            return self.crisis.respond(
                language, user_message, session_id,
                safety_level=level, assessment=risk_assessment)
        if semantic_category in {"harm_encouragement", "medical_instruction"}:
            return self.refusal.respond("harmful", language)
        if semantic_category == "prompt_leak":
            return self.scrub_leak("My system prompt and internal rules", language)
        return reply

    def _semantic_output_category(self, session_id: str, user_message: str,
                                  reply: str) -> str:
        if not self.settings.enable_semantic_safety or self.client is None:
            return "safe"
        assess = getattr(self.client, "assess_output", None)
        if not callable(assess):
            return "safe"
        try:
            value = assess(user_message=user_message, reply=reply,
                           session_id=session_id)
            if isinstance(value, dict):
                return str(value.get("category", "safe"))
            match = re.search(r"\{.*\}", str(value or ""), re.S)
            if match:
                return str(json.loads(match.group(0)).get("category", "safe"))
        except Exception:
            pass
        return "safe"
