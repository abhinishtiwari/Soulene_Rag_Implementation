"""Fast, deterministic message analysis -> internal ResponseStrategy.

This is the "fast router" stage. It uses cheap regex/heuristics (NO LLM calls)
to decide language, intent, emotion, safety level, injection/off-topic flags,
repeated-behaviour, tone knobs, and whether RAG / memory are required.

The resulting ResponseStrategy is INTERNAL ONLY and never shown to the user.
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
    SafetyLevel,
    Turn,
)
from app.utils import detect_language

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
                history: Optional[List[Turn]] = None) -> ResponseStrategy:
        lowered = message.lower()
        language = detect_language(message)
        safety_level = self.guardrails.assess_safety_level(message, moderation)
        emotion = _detect_emotion(lowered)
        history = history or []

        injection = self.guardrails.is_injection(message)
        harmful = self.guardrails.is_harmful(message, moderation)
        sexual = self.guardrails.is_sexual_procedural(message)
        off_topic = self.guardrails.is_off_topic(message)
        medical = self.guardrails.is_medical_request(message)
        repeat_frustration = self.guardrails.is_repeat_frustration(message)

        # Ambiguous restricted intent -> clarify instead of hard refusing.
        needs_clarify = False
        if harmful and not self.guardrails.should_refuse("harmful", message, moderation):
            harmful, needs_clarify = False, True
        if sexual and not self.guardrails.should_refuse("sexual", message, moderation):
            sexual, needs_clarify = False, True

        # --- intent (priority order) ---
        if safety_level.is_crisis:
            intent = Intent.HARMFUL if safety_level == SafetyLevel.HARM_TO_OTHERS else Intent.EMOTIONAL_SUPPORT
        elif injection:
            intent = Intent.INJECTION
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
                intent = Intent.SMALL_TALK

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
        )

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
