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
_SOULENE_BUSINESS = re.compile(
    r"\b(plan|plans|pricing|price|cost|subscription|tier|tiers|feature|features|offer|offers"
    r"|offering|service|services|mentor|mentorship|membership|download|app store|play store"
    r"|school|schools|university|universities|college|workplace|workplaces|corporate"
    r"|athlete|athletes|sports|sport)\b",
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

    # Soulene product / business questions -> Soulene RAG.
    if _SOULENE_NAME.search(lowered) or _SOULENE_BUSINESS.search(lowered):
        return KnowledgeType.SOULENE

    # Informational mental-health questions or exercise requests -> mental-health RAG.
    if _EXERCISE_REQUEST.search(lowered):
        return KnowledgeType.MENTAL_HEALTH
    if _INFO_QUESTION.search(lowered) and _MH_TOPIC.search(lowered):
        return KnowledgeType.MENTAL_HEALTH

    # Everything else (greetings, venting, general chat) -> no RAG.
    return KnowledgeType.NONE
