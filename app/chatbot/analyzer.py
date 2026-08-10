"""Fast response-strategy router.

This stage merges the upstream structured conversation-risk assessment with
cheap deterministic rules for language, intent, restricted content, tone, and
RAG/memory needs. It never calls an LLM itself. The resulting ResponseStrategy
is internal only and never shown to the user.
"""

from __future__ import annotations

import re

from typing import List, Optional

from app.chatbot.router import classify_knowledge
from app.safety.guardrails import Guardrails
from app.types import (
    Intent,
    KnowledgeType,
    Language,
    ModerationSignal,
    ResponseFamily,
    ResponseStrategy,
    RiskAssessment,
    RiskDisposition,
    SafetyLevel,
    Turn,
)
from app.utils import detect_language

_SAFETY_RANK = {
    SafetyLevel.SAFE: 0, SafetyLevel.EMOTIONAL_DISTRESS: 1,
    SafetyLevel.SELF_HARM_CONCERN: 2, SafetyLevel.PHYSICAL_DANGER: 3,
    SafetyLevel.ABUSE_OR_DANGER: 3, SafetyLevel.HARM_TO_OTHERS: 4,
    SafetyLevel.IMMINENT_SELF_HARM: 5,
}

# --- emotion cues ---
_SAD = re.compile(r"\b(sad|down|low|depressed|lonely|alone|empty|hurt|crying|udaas|akela|dukhi)\b", re.I)
# Understated low mood — how people actually phrase it ("my mood isn't good today").
_LOW_MOOD = re.compile(
    r"\b(mood (?:is|isn'?t|is not|not) (?:good|great|okay|ok|fine|nice|the best)"
    r"|(?:bad|off|rough|terrible|awful|hard) day"
    r"|not feeling (?:so |too |very |that |all that )?(?:good|great|okay|ok|myself|it)"
    r"|feeling (?:kind of |kinda |sort of |a bit |a little |really |so |pretty |quite )?"
    r"(?:off|meh|blah|flat|heavy|drained|low|down)"
    r"|don'?t feel like (?:doing anything|myself|talking)"
    r"|mann nahi lag raha|mood theek nahi|dil nahi lag raha)\b",
    re.I,
)
_ANXIOUS = re.compile(r"\b(anxious|anxiety|panic|nervous|worried|scared|overwhelmed|ghabra|pareshan|tension)\b", re.I)
_ANGRY = re.compile(r"\b(angry|furious|mad|hate|annoyed|frustrated|gussa|pissed)\b", re.I)
_CONFUSED = re.compile(r"\b(confused|don'?t (get|understand)|samajh nahi|kya matlab|what do you mean)\b", re.I)
_PLAYFUL = re.compile(r"(😂|😄|😆|🙂|lol|lmao|haha|hehe|just kidding|mazak|majak|test kar)", re.I)
_GREETING = re.compile(r"^\s*(hi+|hey+|hello+|yo+|namaste|hii|helo|good (morning|evening|afternoon))\b[\s!.]*$", re.I)

_VULNERABLE = re.compile(r"\b(worthless|hopeless|numb|can'?t cope|breaking down|falling apart|nobody cares)\b", re.I)

# Positive states — the companion should celebrate / match energy, not console.
_HAPPY = re.compile(
    r"\b(happy|glad|content|peaceful|grateful|thankful|good news|feeling better|feeling good"
    r"|proud of myself|went well|khush|acha lag raha)\b", re.I)
_EXCITED = re.compile(
    r"\b(excited|thrilled|can'?t wait|so pumped|amazing news|i did it|i got (the|it|in)"
    r"|finally happened|best day|guess what)\b|!{2,}", re.I)

# Grief / trauma — humour is NEVER appropriate here (spec requirement), but this
# is not automatically a crisis; it needs gentle, patient presence.
_GRIEF = re.compile(
    r"\b(passed away|died|death of|lost my (mum|mom|mother|dad|father|brother|sister|son"
    r"|daughter|wife|husband|partner|friend|grandma|grandpa|pet|dog|cat|baby)"
    r"|funeral|grieving|grief|mourning|miscarriage|terminal|cancer diagnosis"
    r"|anniversary of (her|his|their) death|he'?s gone|she'?s gone"
    r"|was abused|assaulted|raped|molested|ptsd|flashbacks|trauma|traumatic)\b", re.I)

# Negation guard so "I'm not happy" is never read as a positive state.
_NEGATED_POSITIVE = re.compile(
    r"\b(not|isn'?t|aren'?t|never|no longer|hardly|don'?t|dont|didn'?t|can'?t)\b"
    r"(?:\W+\w+){0,3}?\W+(happy|glad|good|great|excited|better|okay|ok|fine)\b", re.I)

# Distress only counts as the USER's distress when they talk about themselves.
# "What is anxiety?" is a definitional question, not a person in distress.
_FIRST_PERSON = re.compile(r"\b(i|i'?m|im|i'?ve|me|my|myself|mujhe|mera|meri|main|mai|hum)\b", re.I)


def _detect_emotion(lowered: str) -> str:
    """Map a message to one emotional state. Heavier states win."""
    # Grief/trauma outranks generic sadness: it needs presence, never humour.
    if _GRIEF.search(lowered):
        return "grief"
    if _VULNERABLE.search(lowered):
        return "vulnerable"
    if _ANXIOUS.search(lowered):
        return "anxious"
    if _SAD.search(lowered) or _LOW_MOOD.search(lowered):
        return "sad"
    if _ANGRY.search(lowered):
        return "angry"
    if _CONFUSED.search(lowered):
        return "confused"
    # Positive states only when not negated ("I'm not happy" is not happiness).
    if not _NEGATED_POSITIVE.search(lowered):
        if _EXCITED.search(lowered):
            return "excited"
        if _HAPPY.search(lowered):
            return "happy"
    if _PLAYFUL.search(lowered):
        return "playful"
    return "neutral"


class Analyzer:
    def __init__(self, guardrails: Guardrails):
        self.guardrails = guardrails

    def analyze(self, message: str, moderation: ModerationSignal, *,
                repeated_behaviour: bool = False,
                repetition_count: int = 0,
                history: Optional[List[Turn]] = None,
                risk_assessment: Optional[RiskAssessment] = None) -> ResponseStrategy:
        lowered = message.lower()
        language = detect_language(message)
        deterministic_level = self.guardrails.assess_safety_level(message, moderation)
        safety_level = deterministic_level
        if (risk_assessment is not None
                and _SAFETY_RANK[risk_assessment.safety_level] > _SAFETY_RANK[safety_level]):
            safety_level = risk_assessment.safety_level
        emotion = _detect_emotion(lowered)
        if (risk_assessment is not None
                and risk_assessment.emotional_state not in {"neutral", "unclear"}):
            emotion = risk_assessment.emotional_state
        history = history or []

        injection = self.guardrails.is_injection(message) or bool(
            risk_assessment and (
                risk_assessment.prompt_injection
                or risk_assessment.semantic_intent == "safety_bypass"))
        harmful = self.guardrails.is_harmful(message, moderation) or bool(
            risk_assessment and (
                risk_assessment.disposition == RiskDisposition.REFUSE_HARMFUL
                or risk_assessment.semantic_intent == "harmful_instruction"))
        sexual = self.guardrails.is_sexual_procedural(message) or bool(
            risk_assessment and (
                risk_assessment.disposition == RiskDisposition.REFUSE_SEXUAL
                or risk_assessment.semantic_intent == "sexual_instruction"))
        off_topic = self.guardrails.is_off_topic(message)
        medical = self.guardrails.is_medical_request(message)
        repeat_frustration = self.guardrails.is_repeat_frustration(message)

        # Ambiguous restricted intent -> clarify instead of hard refusing.
        needs_clarify = False
        if harmful and not self.guardrails.should_refuse("harmful", message, moderation):
            harmful, needs_clarify = False, True
        if sexual and not self.guardrails.should_refuse("sexual", message, moderation):
            sexual, needs_clarify = False, True

        # --- ISS-16 FIX: Check injection BEFORE crisis override ---
        # Jailbreak detection runs regardless of distress level. A message can be
        # both emotionally distressed AND a jailbreak attempt — injection wins.
        if injection:
            intent = Intent.INJECTION
        # --- intent (priority order) ---
        elif safety_level.is_crisis:
            intent = Intent.HARMFUL if safety_level == SafetyLevel.HARM_TO_OTHERS else Intent.EMOTIONAL_SUPPORT
        elif harmful:
            intent = Intent.HARMFUL
        elif sexual:
            intent = Intent.SEXUAL
        elif self.guardrails.is_helpline_request(message):
            intent = Intent.HELPLINE_REQUEST
        elif medical:
            # A medication ask is emotional support with a firm boundary.
            intent = Intent.MEDICAL_REQUEST
        elif self.guardrails.is_diagnosis_request(message):
            intent = Intent.DIAGNOSIS_REQUEST
        elif needs_clarify:
            intent = Intent.CLARIFY
        elif self.guardrails.is_identity_request(message) and "soulene" not in lowered:
            intent = Intent.IDENTITY
        else:
            knowledge = classify_knowledge(message, None)  # type: ignore[arg-type]
            if knowledge == KnowledgeType.SOULENE:
                intent = Intent.SOULENE_INFO
            elif knowledge == KnowledgeType.MENTAL_HEALTH:
                intent = Intent.MENTAL_HEALTH_INFO
            elif off_topic:
                intent = Intent.OFF_TOPIC
            elif _GREETING.match(message.strip()):
                intent = Intent.GREETING
            elif safety_level == SafetyLevel.EMOTIONAL_DISTRESS or emotion in {"sad", "anxious", "vulnerable", "angry"}:
                intent = Intent.EMOTIONAL_SUPPORT
            else:
                # --- ISS-02/03 FIX: Contextual carry-forward ---
                # Before defaulting to SMALL_TALK, check conversational momentum.
                intent = self._contextual_intent_resolution(
                    message, history, risk_assessment, emotion)

        # --- ISS-07 FIX: Semantic classifier override for borderline cases ---
        # If deterministic layer says SMALL_TALK but semantic classifier detected
        # emotional_support or implicit_self_harm, upgrade the intent.
        if (intent == Intent.SMALL_TALK and risk_assessment is not None):
            semantic = risk_assessment.semantic_intent
            if semantic in ("emotional_support", "implicit_self_harm"):
                intent = Intent.EMOTIONAL_SUPPORT
            elif risk_assessment.emotional_distress_score >= 0.4:
                # Even below the 0.45 threshold for safety_level, a notable
                # distress score means this isn't casual small talk.
                intent = Intent.EMOTIONAL_SUPPORT

        # An informational question isn't the user reporting their own distress.
        # Crisis levels are never downgraded — only EMOTIONAL_DISTRESS.
        if (safety_level == SafetyLevel.EMOTIONAL_DISTRESS
                and intent in (Intent.SOULENE_INFO, Intent.MENTAL_HEALTH_INFO)
                and not _FIRST_PERSON.search(message)):
            safety_level = SafetyLevel.SAFE
            emotion = "neutral"

        # --- knowledge / rag ---
        knowledge_type = KnowledgeType.NONE
        rag_required = False
        if intent == Intent.SOULENE_INFO:
            knowledge_type, rag_required = KnowledgeType.SOULENE, True
        elif intent == Intent.MENTAL_HEALTH_INFO:
            knowledge_type, rag_required = KnowledgeType.MENTAL_HEALTH, True

        # --- memory: only fetch long-term memory when it could matter ---
        memory_required = intent in {
            Intent.EMOTIONAL_SUPPORT, Intent.SMALL_TALK, Intent.SOULENE_INFO,
            Intent.MENTAL_HEALTH_INFO, Intent.MEDICAL_REQUEST, Intent.DIAGNOSIS_REQUEST,
        } and not safety_level.is_crisis

        # --- conversation-level patterns (ported from legacy note system) ---
        multi_intent = message.count("?") >= 2 or any(
            t in lowered for t in (" and also ", " also ", " plus ", " aur ")
        )
        user_texts = [t.content.lower() for t in history if t.role == "user"]
        assistant_texts = [t.content.lower() for t in history if t.role == "assistant"]
        emotional_pattern = sum(
            1 for t in user_texts
            if any(k in t for k in ("stress", "overwhelm", "anxious", "anxiety",
                                    "thak", "akela", "lonely", "sad"))
        ) >= 2
        previous_advice = any(
            ("1." in t or "👉" in t or "try " in t) for t in assistant_texts[-2:]
        )
        avoid = self._avoid_techniques(assistant_texts[-1] if assistant_texts else "")

        # --- tone knobs (dynamic) ---
        humour, warmth, emoji, length, redirect = self._tone(
            intent, emotion, safety_level, repeated_behaviour, repetition_count
        )
        family = self._family(intent, emotion, safety_level, emotional_pattern)

        return ResponseStrategy(
            language=language,
            intent=intent,
            emotion=emotion,
            safety_level=safety_level,
            humour=humour,
            warmth=warmth,
            emoji=emoji,
            length=length,
            redirect=redirect,
            rag_required=rag_required,
            memory_required=memory_required,
            repeated_behaviour=repeated_behaviour,
            repetition_count=repetition_count,
            knowledge_type=knowledge_type,
            family=family,
            medical_request=medical,
            repeat_frustration=repeat_frustration,
            multi_intent=multi_intent,
            emotional_pattern=emotional_pattern,
            previous_advice=previous_advice,
            avoid_techniques=avoid,
            risk_assessment=risk_assessment,
        )

    # ------------------------------------------------------------------
    # ISS-02/03 FIX: Contextual intent resolution
    # Prevents "intent flicker" — short follow-ups after emotional disclosures
    # should maintain emotional_support intent, not drop to small_talk.
    # ------------------------------------------------------------------
    _AFFIRMATIVE = re.compile(
        r"^\s*(yes|yeah|yep|ya|yea|haan|ha|ok|okay|sure|right|i know|help me"
        r"|please|tell me|go on|continue|mhm|hmm|i guess|maybe|idk)\s*[.!?]*\s*$", re.I)

    def _contextual_intent_resolution(self, message: str, history: List[Turn],
                                       risk_assessment: Optional[RiskAssessment],
                                       emotion: str) -> Intent:
        """Determine intent for ambiguous messages using conversational context."""
        # Short or affirmative message in an emotional conversation => carry forward
        is_short = len(message.split()) < 15
        is_affirmative = bool(self._AFFIRMATIVE.match(message))

        if is_short or is_affirmative:
            # Check: were recent user turns emotional?
            recent_user = [t for t in history if t.role == "user"][-5:]
            emotional_recent = sum(
                1 for t in recent_user
                if any(k in t.content.lower() for k in (
                    "stress", "anxious", "anxiety", "sad", "lonely", "overwhelm",
                    "depressed", "hurt", "scared", "worried", "hopeless", "crying",
                    "breakup", "died", "grief", "worthless", "numb", "empty",
                    "thak", "akela", "udaas", "pareshan"))
            )
            if emotional_recent >= 1:
                return Intent.EMOTIONAL_SUPPORT

        # Check trajectory from semantic reasoner
        if (risk_assessment is not None
                and risk_assessment.emotional_trajectory in ("worsening", "rapidly_worsening")):
            return Intent.EMOTIONAL_SUPPORT

        return Intent.SMALL_TALK

    # ------------------------------------------------------------------
    # Anti-repetition ladder (from core/.txt): if the last reply used X,
    # prefer something different this turn.
    # ------------------------------------------------------------------
    _LADDER = {
        "breath": ["breathing"],
        "inhale": ["breathing"],
        "ground": ["grounding"],
        "5-4-3-2-1": ["grounding"],
        "journal": ["journaling"],
        "write down": ["journaling"],
        "walk": ["movement"],
    }

    def _avoid_techniques(self, last_assistant: str) -> List[str]:
        if not last_assistant:
            return []
        avoid: List[str] = []
        for needle, labels in self._LADDER.items():
            if needle in last_assistant:
                avoid.extend(labels)
        if last_assistant.rstrip().endswith("?"):
            avoid.append("ending with a question")
        return sorted(set(avoid))

    def _family(self, intent, emotion, safety_level, emotional_pattern) -> ResponseFamily:
        if safety_level.is_crisis:
            return ResponseFamily.SAFETY_MODE
        if intent in (Intent.SOULENE_INFO, Intent.MENTAL_HEALTH_INFO,
                      Intent.HELPLINE_REQUEST, Intent.IDENTITY):
            return ResponseFamily.INFORMATIONAL
        if emotion == "anxious" or safety_level == SafetyLevel.EMOTIONAL_DISTRESS and emotion == "anxious":
            return ResponseFamily.REGULATION_SUPPORT
        if emotional_pattern:
            return ResponseFamily.PATTERN_INTERRUPTION
        if emotion == "confused":
            return ResponseFamily.COGNITIVE_CLARITY
        if emotion in ("sad", "vulnerable"):
            return ResponseFamily.GENTLE_ACTIVATION
        return ResponseFamily.EMOTIONAL_HOLDING

    def _tone(self, intent, emotion, safety_level, repeated, rep_count):
        # Safety first: no humour, minimal emoji, supportive & calm.
        if safety_level.is_crisis or safety_level == SafetyLevel.IMMINENT_SELF_HARM:
            return 0, 3, "none", "short", False
        # Medication / diagnosis / helpline asks are serious: warm, never jokey.
        if intent in (Intent.MEDICAL_REQUEST, Intent.DIAGNOSIS_REQUEST,
                      Intent.HELPLINE_REQUEST, Intent.CLARIFY):
            return 0, 3, "none", "short", False
        # Grief / trauma: gentle presence, NEVER humour, no emojis.
        if emotion == "grief":
            return 0, 3, "none", "short", False
        if safety_level == SafetyLevel.EMOTIONAL_DISTRESS or emotion in {"sad", "vulnerable", "anxious"}:
            return 0, 3, "light", "short", False

        if intent in {Intent.INJECTION, Intent.OFF_TOPIC}:
            # Escalating playfulness on repeats, but boundary stays firm.
            humour = 1 if rep_count <= 1 else (2 if rep_count == 2 else 3)
            return humour, 2, "normal" if rep_count >= 2 else "light", "short", True

        # Positive states: celebrate with them / match their energy.
        if emotion == "excited":
            return 2, 3, "normal", "short", False
        if emotion == "happy":
            return 2, 3, "normal", "short", False
        if emotion == "playful" or intent == Intent.GREETING:
            return 2, 2, "normal", "short", False
        if emotion == "angry":
            return 0, 2, "light", "short", False
        if emotion == "confused":
            return 0, 2, "light", "short", False
        if intent in {Intent.SOULENE_INFO, Intent.MENTAL_HEALTH_INFO}:
            return 1, 2, "light", "medium", False
        return 1, 2, "light", "short", False
