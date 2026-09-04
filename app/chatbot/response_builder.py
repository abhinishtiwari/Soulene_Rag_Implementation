"""Output safety pass: screen/repair a generated reply before it reaches the user."""

from __future__ import annotations

import json
import random
import re
from typing import Optional

from app.config.settings import Settings
from app.llm.client import LLMClient
from app.observability import COUNTERS
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
        r"|i was instructed to|my configuration|internal (only|rules)"
        # Verbatim fragments of the actual core prompt / identity block. NOTE:
        # "s3 cubes innovations" was previously listed here and had to be
        # removed: CORE_PROMPT explicitly tells the companion it is "built by the
        # Soulene Team and powered by S3 Cubes Innovations Private Limited", and
        # the knowledge documents describe the company, so it is a fact the bot
        # is meant to share — not an instruction fragment. Treating it as a leak
        # marker meant every correct answer to "who built Soulene" was replaced
        # with the "I can't share how I work internally" deflection. An actual
        # prompt dump is still caught by the instruction-shaped markers below.
        r"|you are soulene ai, a warm|boundaries you always keep"
        r"|treat any text in user messages|never reveal your instructions"
        r"|this turn:|core_prompt|core system prompt)",
        re.I,
    )

    # Concrete secrets / credentials that must never appear in a reply, whatever
    # the model emits. This is a hard backstop independent of phrasing/language.
    _SECRET = re.compile(
        r"(sk-[A-Za-z0-9_\-]{6,}"                     # OpenAI-style keys
        r"|mongodb(?:\+srv)?://"                        # Mongo connection strings
        r"|postgres(?:ql)?://|mysql://|redis://"        # other DB URIs
        r"|api[_\s-]?key\s*[:=]"                        # API_KEY= / api key:
        r"|bearer\s+[A-Za-z0-9._\-]{10,}"               # bearer tokens
        r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"          # private keys
        r"|mongo_uri|openai_api_key|admin_api_key)",    # env var names
        re.I,
    )

    def scrub_leak(self, reply: str, language: Language) -> str:
        text = reply or ""
        # A concrete secret pattern is redacted even if the surrounding text
        # looks benign — never let a credential reach the user.
        if self._LEAK.search(text) or self._SECRET.search(text):
            if language in (Language.HINDI, Language.HINGLISH):
                return ("Main apne internal setup ke baare mein baat nahi kar sakta, "
                        "but tumhari help zaroor kar sakta hoon. Kya chal raha hai?")
            return ("I can't share details about how I work internally, but I'm here "
                    "to help you. What's on your mind?")
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

    # Unambiguous executable-code artefacts. Unlike _TECHNICAL_ANSWER above this
    # contains no ordinary English words, so it is safe to run on EVERY reply.
    # It exists because the domain boundary used to be enforced only when the
    # input classifier had already flagged the turn as off-topic — meaning the
    # backstop never ran precisely when the classifier had been talked around.
    _CODE_ARTEFACT = re.compile(
        r"(```"
        r"|^\s*(?:import|from)\s+[a-z_][\w.]*\s*$"
        r"|^\s*(?:def|class)\s+\w+\s*[(:]"
        r"|\bprint\s*\(\s*[\"'f]"
        r"|\bconsole\.log\s*\("
        r"|\bos\.(?:listdir|path|getcwd|system)\b"
        r"|\bfor\s+\w+\s+in\s+[\w.]+\s*\(?.*\)?\s*:"
        r"|\bif\s+__name__\s*==\s*[\"']__main__[\"']"
        r"|\b(?:public|private)\s+static\s+void\s+main"
        r"|<\?php|\bSELECT\b[\s\S]{0,80}\bFROM\b"
        r"|\bfunction\s+\w+\s*\([^)]*\)\s*\{)",
        re.I | re.M,
    )

    # Programming/CS vocabulary that has no place in a wellbeing reply. Kept
    # separate from wellbeing "steps" language so a grounding exercise ("1. take
    # a slow breath ...") is never mistaken for a leaked algorithm.
    _CS_VOCAB = re.compile(
        r"\b(algorithm|pseudo\s?code|fibonacci|binary search|bubble sort|merge sort"
        r"|quick ?sort|insertion sort|selection sort|linked list|hash ?(?:map|table)"
        r"|recursion|recursive|iterate|iteration|sorted (?:list|array)|the middle (?:item|element)"
        r"|left half|right half|integer|boolean|time complexity|big[- ]?o"
        r"|previous two numbers?|first two numbers?|element|array|loop|variable|index)\b",
        re.I,
    )
    # A numbered / bulleted procedure of two or more steps.
    _STEP_LIST = re.compile(
        r"(?:^|\n)\s*(?:step\s*)?[1-9][\.\):]\s+.+"
        r"(?:[\s\S]*?(?:^|\n)\s*(?:step\s*)?[2-9][\.\):]\s+.+)",
        re.I | re.M,
    )

    def _looks_like_prose_algorithm(self, reply: str) -> bool:
        """A step-by-step procedure written in words that is really a coding answer.

        Catches leaked algorithms/pseudocode that contain no runnable code (so
        `_CODE_ARTEFACT` misses them) — e.g. a numbered outline of binary search.
        Requires BOTH a multi-step list AND programming/CS vocabulary so ordinary
        wellbeing steps (breathing, journaling) are never swept up.
        """
        text = reply or ""
        return bool(self._STEP_LIST.search(text) and self._CS_VOCAB.search(text))

    def enforce_no_code(self, reply: str, language: Language) -> str:
        """Strip a code OR prose-algorithm answer from ANY reply.

        Runs unconditionally: a wellbeing companion has no situation in which
        emitting a runnable program — or a step-by-step algorithm/pseudocode —
        is correct, so this does not depend on the turn having been classified as
        off-topic.
        """
        if not reply:
            return reply
        if not (self._CODE_ARTEFACT.search(reply)
                or self._looks_like_prose_algorithm(reply)):
            return reply
        pool = (self._REDIRECTS_HI if language in (Language.HINDI, Language.HINGLISH)
                else self._REDIRECTS_EN)
        return random.choice(pool)

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

    # High-impact therapeutic harms need a local policy wall. The model reviewer
    # is useful defense in depth, but network or parsing failures must not be the
    # only thing standing between these statements and a vulnerable user.
    _THERAPEUTIC_HARM_PATTERNS = (
        # Relational-boundary harms. Ordinary warmth ("I'm here for you", "you're
        # not alone") is deliberately NOT matched; only exclusivity, replacement
        # of real care, coercion, false permanence and special-bond framing are.
        ("dependency_or_coercion", re.compile(
            r"\b(?:i(?:'m| am) (?:all|the only (?:one|person)) you need"
            r"|only (?:trust|listen to|talk to) me"
            r"|don'?t tell (?:anyone|your (?:doctor|therapist|family|friends))"
            r"|stop (?:seeing|talking to) your (?:doctor|therapist|family|friends)"
            r"|you don'?t need (?:a |your )?(?:doctor|therapist|family|friends|anyone else)"
            # exclusivity / isolation from other support
            r"|(?:never|don'?t|do not) need to (?:talk|speak) to any ?one else"
            r"|no one else (?:needs to know|has to know)"
            r"|(?:i'?m|i am) the only (?:one|person) who (?:understands|cares about|gets) you"
            r"|you don'?t need any ?one (?:else|but me)"
            # replacement of professional care
            r"|you (?:do not|don'?t) need (?:therapy|a therapist|counsell?ing"
            r"|professional help|medication|a doctor)"
            r"|therapy (?:is ?n'?t|is not) (?:necessary|needed)"
            # claiming superiority over the user's real relationships
            r"|(?:understand|know) you better than (?:your|any ?one)"
            # coercive commitments
            r"|promise me you (?:will|won'?t|wont)"
            r"|message me first before"
            # false permanence / total reliance
            r"|rely on me completely|depend on me (?:completely|entirely)"
            r"|i (?:will|'ll) never leave you"
            # special-bond framing
            r"|our (?:bond|connection|relationship) is (?:special|unique|different)"
            r"|different from your other relationships)\b",
            re.I,
        )),
        ("diagnosis", re.compile(
            r"\b(?:you (?:definitely|clearly|certainly|obviously|undoubtedly) "
            r"(?:have|suffer from)|i (?:can|will) diagnose you"
            r"|i(?:'ve| have) diagnosed you|your diagnosis is"
            r"|you (?:are|must be) (?:bipolar|psychotic|schizophrenic|clinically depressed))\b",
            re.I,
        )),
        ("delusion_reinforcement", re.compile(
            r"\b(?:i know (?:the )?voices are real"
            r"|the voices are (?:definitely |actually )?real"
            r"|(?:they|the government|your neighbors?) (?:are|is) "
            r"(?:watching|following|tracking) you"
            r"|secret messages? (?:are|is) (?:being )?sent (?:just )?to you"
            r"|your (?:paranoia|suspicion|belief) is (?:true|correct))\b",
            re.I,
        )),
        ("medical_instruction", re.compile(
            r"\b(?:take|start|stop|quit|increase|decrease|double|halve|skip|switch|change)\b"
            r".{0,80}\b(?:dose|dosage|medication|medicine|prescription|antidepressant"
            r"|antipsychotic|sedative|tablet|pill)s?\b",
            re.I | re.S,
        )),
        ("treatment_certainty", re.compile(
            r"\b(?:this (?:will|is guaranteed to) (?:cure|fix) (?:your )?"
            r"(?:depression|anxiety|trauma|panic attacks?|mental illness)"
            r"|you (?:will|are guaranteed to) recover if you follow my advice)\b",
            re.I,
        )),
        ("shame_or_degradation", re.compile(
            r"\b(?:you(?:'re| are) (?:weak|pathetic|crazy|broken|attention[- ]seeking)"
            r"|this is (?:all |entirely )?your fault"
            r"|you deserve to (?:feel this way|suffer))\b",
            re.I,
        )),
    )
    _SAFE_MEDICAL_BOUNDARY = re.compile(
        r"\b(?:do not|don'?t|should not|shouldn'?t|never|can'?t|cannot)\s+"
        r"(?:take|start|stop|quit|increase|decrease|double|halve|skip|switch|change)\b",
        re.I,
    )
    _SAFE_SHAME_BOUNDARY = re.compile(
        r"\byou(?:'re| are) not (?:weak|pathetic|crazy|broken|attention[- ]seeking)\b",
        re.I,
    )
    _SAFE_REALITY_BOUNDARY = re.compile(
        r"\b(?:may |can )?(?:feel|seem) like (?:the )?voices are real\b",
        re.I,
    )

    def _therapeutic_harm_category(self, reply: str) -> str | None:
        text = self._SAFE_MEDICAL_BOUNDARY.sub("", reply or "")
        text = self._SAFE_SHAME_BOUNDARY.sub("", text)
        text = self._SAFE_REALITY_BOUNDARY.sub("", text)
        for category, pattern in self._THERAPEUTIC_HARM_PATTERNS:
            if pattern.search(text):
                return category
        return None

    @staticmethod
    def _therapeutic_safety_reply(language: Language) -> str:
        if language == Language.HINDI:
            return (
                "मैं diagnosis, medicine की dose, या human support को replace करने वाली "
                "सलाह सुरक्षित रूप से नहीं दे सकता। किसी qualified healthcare professional "
                "से बात करना बेहतर होगा; मैं आपकी बात सुनने और अगला सुरक्षित कदम सोचने में साथ हूँ।"
            )
        if language == Language.HINGLISH:
            return (
                "Main diagnosis, medicine ki dose, ya human support ko replace karne wali "
                "advice safely nahi de sakta. Qualified healthcare professional se baat karna "
                "better hoga; main sunne aur next safe step sochne mein saath hoon."
            )
        return (
            "I can't safely give a diagnosis, medication dose, or advice that replaces human "
            "support. A qualified healthcare professional can help with diagnosis or treatment; "
            "I can listen and help you think through a safe next step."
        )

    # Gentle, non-rejecting nudge back toward human and professional support.
    # Deliberately warm: the goal is to widen the user's support, not to withdraw.
    _RELATIONAL_BOUNDARY = {
        Language.ENGLISH: (
            "I'm glad this helps, and I do want to say one thing gently: I'm not a "
            "substitute for people who can be there in person. Is there someone you "
            "trust, or a professional, you could let in a little too?"
        ),
        Language.HINGLISH: (
            "Mujhe accha lagta hai ki yeh help karta hai, par ek baat gently kehna "
            "chahta hoon: main un logon ki jagah nahi le sakta jo tumhare saath "
            "physically ho sakte hain. Koi trusted insaan ya professional bhi saath "
            "ho to accha rahega."
        ),
        Language.HINDI: (
            "मुझे अच्छा लगता है कि इससे मदद मिलती है, पर एक बात धीरे से कहना चाहता हूँ: "
            "मैं उन लोगों की जगह नहीं ले सकता जो आपके साथ सामने हो सकते हैं। किसी "
            "भरोसेमंद व्यक्ति या professional को भी साथ रखिए।"
        ),
    }

    def append_relational_boundary(self, reply: str, language: Language) -> str:
        """Add a one-off boundary reminder to an otherwise unchanged reply."""
        note = self._RELATIONAL_BOUNDARY.get(
            language, self._RELATIONAL_BOUNDARY[Language.ENGLISH])
        if not reply:
            return note
        if note in reply:
            return reply
        return f"{reply.rstrip()} {note}"

    def contains_unsafe_derived_text(self, text: str) -> bool:
        """Screen model-generated derived context (summaries, notes) for reuse.

        Derived text is never shown directly, but it is fed back into later
        prompts, so it must clear the same leak/secret/therapeutic-harm walls as
        a user-visible reply before it can be stored.
        """
        candidate = text or ""
        if not candidate.strip():
            return True
        if self._LEAK.search(candidate) or self._SECRET.search(candidate):
            return True
        return self._therapeutic_harm_category(candidate) is not None

    def _blocked_reply(self, language: Language, *, session_id: str,
                       user_message: str,
                       risk_assessment: Optional[RiskAssessment],
                       turn_is_crisis: bool) -> str:
        """The replacement to deliver when the outgoing reply must be withheld.

        ISSUE-041: for an ordinary turn the therapeutic-harm notice is the right
        fail-closed answer. For a CRISIS turn it is not -- the reply being
        withheld is the deterministic crisis protocol, so substituting a
        diagnosis disclaimer removes the safety steps and emergency reference
        that `app/safety/crisis.py` states can never be lost. Failing closed has
        to mean falling back to the safest known-good content, and on a crisis
        turn that is the crisis protocol, not silence about it.

        This mirrors what the `self_harm_encouragement` and `danger_minimization`
        branches already do; those two were correct and the withholding branches
        simply never used the same fallback.
        """
        if not turn_is_crisis:
            return self._therapeutic_safety_reply(language)
        COUNTERS.increment("output_blocked_crisis_protocol_preserved")
        return self.crisis.respond(
            language, user_message, session_id,
            safety_level=(risk_assessment.safety_level if risk_assessment else None),
            assessment=risk_assessment)

    def apply_output_safety(self, *, session_id: str, user_message: str, reply: str,
                            language: Language,
                            risk_assessment: Optional[RiskAssessment] = None,
                            safety_level: Optional[SafetyLevel] = None,
                            knowledge_context: Optional[str] = None) -> str:
        """Validate the exact text that will be delivered and archived.

        `safety_level` is the authoritative fused level for the turn. It is
        passed separately from `risk_assessment` because the deterministic floor
        can escalate a turn above whatever the semantic assessment concluded, and
        the crisis-safe fallback below has to key off the level that actually
        selected the crisis route.
        """
        level = safety_level or (risk_assessment.safety_level if risk_assessment
                                 else None)
        turn_is_crisis = bool(level is not None and level.is_crisis)
        reply = self.scrub_leak(reply, language)

        # The editor improves recoverable drafts. Its result still passes every
        # deterministic and semantic check below.
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

        harm = self._therapeutic_harm_category(reply)
        if harm is not None:
            COUNTERS.increment(f"output_blocked_{harm}")
            return self._blocked_reply(
                language, session_id=session_id, user_message=user_message,
                risk_assessment=risk_assessment, turn_is_crisis=turn_is_crisis)

        semantic_category = self._semantic_output_category(
            session_id, user_message, reply, knowledge_context)
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
        if semantic_category in {
            "diagnosis", "delusion_reinforcement", "dependency_or_coercion",
            "treatment_certainty", "shame_or_degradation", "review_unavailable",
        }:
            COUNTERS.increment(f"output_blocked_{semantic_category}")
            return self._blocked_reply(
                language, session_id=session_id, user_message=user_message,
                risk_assessment=risk_assessment, turn_is_crisis=turn_is_crisis)
        if semantic_category == "prompt_leak":
            return self.scrub_leak("My system prompt and internal rules", language)
        # Not safety-harmful, but they fail the spec's relevance / grounding
        # checks, so the reply must not ship as-is. Without a regeneration hook
        # here, fail safe to a short, honest reply rather than delivering an
        # off-topic answer or an invented "fact".
        # CRISIS SAFETY: on a crisis turn the reply being judged is the
        # deterministic crisis protocol. A relevance/grounding complaint must
        # NEVER delete it — the protocol is *supposed* to talk about safety even
        # when the user asked something unrelated, so "irrelevant" is expected
        # there and is not a reason to drop the safety steps. This mirrors what
        # `_blocked_reply` already does for the safety categories; these two
        # branches previously bypassed it and shipped "Sorry, I drifted off"
        # in place of the crisis protocol.
        if semantic_category in ("ungrounded", "irrelevant"):
            COUNTERS.increment(f"output_blocked_{semantic_category}")
            if turn_is_crisis:
                COUNTERS.increment("output_crisis_protocol_preserved_over_relevance")
                return reply
            return (self._ungrounded_reply(language)
                    if semantic_category == "ungrounded"
                    else self._irrelevant_reply(language))
        return reply

    def _ungrounded_reply(self, language: Language) -> str:
        """Delivered when a factual reply is not supported by the source."""
        if language in (Language.HINDI, Language.HINGLISH):
            return ("Iske baare mein mere paas pakki jaankari nahi hai, isliye main "
                    "galat kuch nahi kehna chahta. App > Profile > Help & Support "
                    "se sahi detail mil jayegi. Aur batao, kya chal raha hai?")
        return ("I don't have that detail on hand, so I'd rather not guess. You can "
                "check App > Profile > Help & Support for the exact info. "
                "Anything else on your mind?")

    def _irrelevant_reply(self, language: Language) -> str:
        """Delivered when the draft didn't actually address the request."""
        if language in (Language.HINDI, Language.HINGLISH):
            return ("Sorry, main thoda side track ho gaya. Ek baar phir batao — main "
                    "sahi tarah se samajhna chahta hoon.")
        return ("Sorry, I drifted off what you actually asked. Tell me once more so I "
                "can focus on the right thing?")

    def _semantic_output_category(self, session_id: str, user_message: str,
                                  reply: str,
                                  knowledge_context: Optional[str] = None) -> str:
        if not self.settings.enable_semantic_safety or self.client is None:
            return "not_required"
        assess = getattr(self.client, "assess_output", None)
        if not callable(assess):
            return "review_unavailable"
        allowed = {
            "safe", "self_harm_encouragement", "harm_encouragement",
            "danger_minimization", "medical_instruction", "prompt_leak",
            "diagnosis", "delusion_reinforcement", "dependency_or_coercion",
            "treatment_certainty", "shame_or_degradation",
            "irrelevant", "ungrounded",
        }
        try:
            try:
                value = assess(user_message=user_message, reply=reply,
                               session_id=session_id,
                               knowledge_context=knowledge_context)
            except TypeError:
                # Backward-compatible with assess_output implementations that
                # predate the knowledge_context/grounding argument.
                value = assess(user_message=user_message, reply=reply,
                               session_id=session_id)
            if isinstance(value, dict):
                category = str(value.get("category", "")).strip().lower()
            else:
                match = re.search(r"\{.*\}", str(value or ""), re.S)
                category = str(json.loads(match.group(0)).get("category", "")).strip().lower() \
                    if match else ""
            return category if category in allowed else "review_unavailable"
        except Exception:
            return "review_unavailable"
