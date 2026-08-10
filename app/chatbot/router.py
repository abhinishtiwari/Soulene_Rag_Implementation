"""Lightweight knowledge router.

Decides — with fast regexes, no LLM call — whether a SUPPORT-routed message
should consult a RAG knowledge base and which one:

    KnowledgeType.SOULENE        -> factual questions about the Soulene product
    KnowledgeType.MENTAL_HEALTH  -> informational mental-health questions / exercises
    KnowledgeType.NONE           -> normal chat + emotional support (NO RAG)

Emotional venting ("I feel lonely") deliberately does NOT trigger RAG — it goes
to the normal empathetic LLM path, preserving the existing bot's behaviour.
"""

from __future__ import annotations

import re

from app.types import KnowledgeType, SafetyDecision

# --- Soulene product signals ---
_SOULENE_NAME = re.compile(r"\bsoulene\b", re.I)
# ISS-08 FIX: Narrowed product keywords — removed overly broad terms like
# "plan", "school", "college", "sport" that frequently appear in emotional
# conversations. These only trigger Soulene routing when "soulene" is present.
_SOULENE_BUSINESS_STRICT = re.compile(
    r"\b(pricing|price|cost|subscription|tier|tiers|feature|features|offer|offers"
    r"|offering|mentor|mentorship|membership|download|app store|play store"
    r"|corporate program)\b",
    re.I,
)
# Broad terms that only trigger Soulene routing when "soulene" is explicitly mentioned.
_SOULENE_BUSINESS_BROAD = re.compile(
    r"\b(plan|plans|service|services|school|schools|university|universities"
    r"|college|workplace|workplaces|athlete|athletes|sports|sport)\b",
    re.I,
)

# ISS-08 FIX: First-person emotional language is a negative guard.
# If the message is clearly personal/emotional, never route to Soulene product KB.
_FIRST_PERSON_EMOTIONAL = re.compile(
    r"\b(i feel|i'?m feeling|i have no|i don'?t have|my life|my future"
    r"|stressed|anxious|overwhelmed|depressed|worried|scared|lonely|hopeless)\b",
    re.I,
)

# --- Informational mental-health signals ---
_INFO_QUESTION = re.compile(
    r"\b(what is|what are|what'?s|explain|define|tell me about|how does|how do i deal with"
    r"|ways to|techniques? for|how to manage|how to cope|how do i cope|symptoms? of|signs? of"
    r"|difference between)\b",
    re.I,
)
_MH_TOPIC = re.compile(
    r"\b(anxiety|depression|stress|panic|overthinking|insomnia|sleep|anger|grief|loneliness"
    r"|burnout|trauma|mindfulness|meditation|breathing|grounding|coping|self[- ]care|wellbeing"
    r"|mental health|mood|nervous|worry|calm)\b",
    re.I,
)
_EXERCISE_REQUEST = re.compile(
    r"\b(exercise|exercises|breathing exercise|grounding exercise|coping exercise|technique"
    r"|meditation|mindfulness practice|relaxation|stress relief|give me .*exercise"
    r"|suggest .*exercise)\b",
    re.I,
)


def classify_knowledge(message: str, decision: SafetyDecision) -> KnowledgeType:
    lowered = message.lower()

    # ISS-08 FIX: If message contains first-person emotional language, never
    # route to Soulene product knowledge — this is emotional support, not a product question.
    is_emotional = bool(_FIRST_PERSON_EMOTIONAL.search(lowered))

    # Soulene product / business questions -> Soulene RAG.
    # Strict keywords always trigger; broad keywords only when "soulene" is mentioned.
    if not is_emotional:
        if _SOULENE_NAME.search(lowered):
            if _SOULENE_BUSINESS_STRICT.search(lowered) or _SOULENE_BUSINESS_BROAD.search(lowered):
                return KnowledgeType.SOULENE
        elif _SOULENE_BUSINESS_STRICT.search(lowered):
            return KnowledgeType.SOULENE

    # Informational mental-health questions or exercise requests -> mental-health RAG.
    if _EXERCISE_REQUEST.search(lowered):
        return KnowledgeType.MENTAL_HEALTH
    if _INFO_QUESTION.search(lowered) and _MH_TOPIC.search(lowered):
        return KnowledgeType.MENTAL_HEALTH

    # Everything else (greetings, venting, general chat) -> no RAG.
    return KnowledgeType.NONE
