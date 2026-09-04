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
# Names of the entities our own knowledge documents describe: the product
# (Soulene) and the company behind it (S3 Cubes Innovations), which has its own
# document in knowledge/soulene/. These are entity ALIASES — the lookup key for
# "this question is about us" — not an attempt to guess intent from vocabulary.
# Without the company alias, "what is S3 Cubes" retrieved nothing and the model
# answered from its own knowledge instead of the document.
_SOULENE_NAME = re.compile(r"\bsoulene\b|\bs3\s*cubes?\b", re.I)
# Definitional / explanatory question about the product itself. Only meaningful
# when the message also names Soulene (checked by the caller).
_SOULENE_DEFINITIONAL = re.compile(
    # NOTE: every alternative here is only consulted when the message already
    # names Soulene / S3 Cubes, so bare verbs like "tell me" cannot over-trigger
    # on unrelated chat. "tell me soulene" (no "about") is a very common phrasing
    # that previously fell through to small talk.
    r"\b(what\s+is|what'?s|what\s+are|who\s+is|tell\s+me|about|explain"
    r"|how\s+does|how\s+do|how\s+can|what\s+can|what\s+does"
    # Ownership / origin questions are product questions too ("who built
    # soulene", "who's behind S3 Cubes"). Bare/uninflected forms are included on
    # purpose: users type "who build soulene" and "who develop soulene" far more
    # often than the grammatical form, and missing those sent the turn to small
    # talk with no document at all.
    r"|who\s+(?:build|built|make|made|own|owns|run|runs|create|created"
    r"|found|founded|develop|develops|developed)"
    r"|which\s+company|how\s+many\s+(?:members|people|employees)"
    r"|behind|know\s+about|heard\s+of)\b", re.I)
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
# Second-person questions about the bot's OWN offerings ("what are your plans",
# "do you have pricing", "what are your features"). These are product questions,
# unambiguously distinct from first-person emotional statements like "I have no
# plan for my life" (which the emotional guard below excludes).
_SOULENE_SECOND_PERSON = re.compile(
    r"\byour\s+(plan|plans|pricing|price|prices|features?|services?|offering|offerings"
    r"|subscription|tiers?|membership|cost|costs|packages?)\b",
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
            # A definitional question naming the product ("what is Soulene",
            # "tell me about Soulene", "how does Soulene work") is a product
            # question even without a business keyword, and should be answered
            # from knowledge rather than falling through to small talk.
            if _SOULENE_DEFINITIONAL.search(lowered):
                return KnowledgeType.SOULENE
        elif _SOULENE_BUSINESS_STRICT.search(lowered):
            return KnowledgeType.SOULENE
        elif _SOULENE_SECOND_PERSON.search(lowered):
            # "what are your plans / pricing / features" — asking the bot about
            # its own offerings is a product question, not small talk.
            return KnowledgeType.SOULENE

    # Informational mental-health questions or exercise requests -> mental-health RAG.
    if _EXERCISE_REQUEST.search(lowered):
        return KnowledgeType.MENTAL_HEALTH
    if _INFO_QUESTION.search(lowered) and _MH_TOPIC.search(lowered):
        return KnowledgeType.MENTAL_HEALTH

    # Everything else (greetings, venting, general chat) -> no RAG.
    return KnowledgeType.NONE
