"""Shared types used across the chatbot."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class Language(str, Enum):
    ENGLISH = "english"
    HINDI = "hindi"
    HINGLISH = "hinglish"


class Route(str, Enum):
    SUPPORT = "support"
    REFUSAL = "refusal"
    CRISIS = "crisis"


class ResponseMode(str, Enum):
    BALANCED = "balanced"
    EMOTIONAL = "emotional"
    ADVICE = "advice"


class KnowledgeType(str, Enum):
    """Which RAG knowledge base (if any) to consult."""

    SOULENE = "soulene"
    MENTAL_HEALTH = "mental_health"
    NONE = "none"


class SafetyLevel(str, Enum):
    """Graded safety assessment. Higher levels short-circuit normal generation."""

    SAFE = "safe"
    EMOTIONAL_DISTRESS = "emotional_distress"
    SELF_HARM_CONCERN = "self_harm_concern"
    IMMINENT_SELF_HARM = "imminent_self_harm"
    HARM_TO_OTHERS = "harm_to_others"
    ABUSE_OR_DANGER = "abuse_or_danger"

    @property
    def is_crisis(self) -> bool:
        return self in {
            SafetyLevel.SELF_HARM_CONCERN,
            SafetyLevel.IMMINENT_SELF_HARM,
            SafetyLevel.HARM_TO_OTHERS,
            SafetyLevel.ABUSE_OR_DANGER,
        }


class Intent(str, Enum):
    GREETING = "greeting"
    EMOTIONAL_SUPPORT = "emotional_support"
    SOULENE_INFO = "soulene_info"
    MENTAL_HEALTH_INFO = "mental_health_info"
    OFF_TOPIC = "off_topic"            # coding / general-purpose assistant asks
    INJECTION = "injection"            # prompt-extraction / jailbreak
    HARMFUL = "harmful"
    SEXUAL = "sexual"
    SMALL_TALK = "small_talk"
    MEDICAL_REQUEST = "medical_request"    # asking for pills/medication
    DIAGNOSIS_REQUEST = "diagnosis_request"  # "do I have BPD?"
    HELPLINE_REQUEST = "helpline_request"
    IDENTITY = "identity"
    CLARIFY = "clarify"                # ambiguous restricted intent


class ResponseFamily(str, Enum):
    """One primary family per reply (harvested from core/.txt draft)."""

    EMOTIONAL_HOLDING = "emotional_holding"      # venting -> feel understood
    COGNITIVE_CLARITY = "cognitive_clarity"      # confusion -> simplify
    PATTERN_INTERRUPTION = "pattern_interruption"  # loops -> awareness
    REGULATION_SUPPORT = "regulation_support"    # anxiety/panic -> calm body
    GENTLE_ACTIVATION = "gentle_activation"      # low mood -> tiny action
    VALUES_DIRECTION = "values_direction"        # decisions -> alignment
    SAFETY_MODE = "safety_mode"                  # distress/crisis -> stability
    INFORMATIONAL = "informational"              # factual answer


@dataclass
class ResponseStrategy:
    """Internal-only plan for how the main LLM should respond. Never shown to users."""

    language: "Language"
    intent: "Intent"
    emotion: str = "neutral"
    safety_level: "SafetyLevel" = None  # set post-init
    humour: int = 0          # 0..3
    warmth: int = 2          # 0..3
    emoji: str = "light"     # none | light | normal
    length: str = "short"    # short | medium | long
    redirect: bool = False   # gently steer back to wellness
    rag_required: bool = False
    memory_required: bool = False
    repeated_behaviour: bool = False
    repetition_count: int = 0
    knowledge_type: "KnowledgeType" = None
    # --- behaviours ported from the legacy bot ---
    family: "ResponseFamily" = None
    medical_request: bool = False      # asked for meds -> acknowledge, decline, offer help
    repeat_frustration: bool = False   # "I just told you" -> never ask again
    multi_intent: bool = False         # several questions in one message
    emotional_pattern: bool = False    # recurring theme across the conversation
    previous_advice: bool = False      # last reply already gave advice/steps
    avoid_techniques: List[str] = field(default_factory=list)  # anti-repetition ladder

    def __post_init__(self):
        if self.safety_level is None:
            self.safety_level = SafetyLevel.SAFE
        if self.knowledge_type is None:
            self.knowledge_type = KnowledgeType.NONE
        if self.family is None:
            self.family = ResponseFamily.EMOTIONAL_HOLDING


@dataclass
class UserMemory:
    """One long-term memory item for a user."""

    text: str
    kind: str = "fact"          # name | preference | context | health | relationship
    created_at: float = 0.0
    updated_at: float = 0.0
    weight: float = 1.0


@dataclass
class Turn:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class ModerationSignal:
    flagged: bool = False
    categories: Dict[str, bool] = field(default_factory=dict)
    error: Optional[str] = None

    def any_true(self, *names: str) -> bool:
        return any(self.categories.get(name, False) for name in names)


@dataclass
class SafetyDecision:
    route: Route
    language: Language
    response_mode: ResponseMode = ResponseMode.BALANCED
    refusal_reason: Optional[str] = None
    distress: bool = False
    notes: List[str] = field(default_factory=list)


@dataclass
class RetrievedChunk:
    text: str
    score: float
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class ChatResult:
    """Full result of handling one message (useful for tests + UI)."""

    reply: str
    route: Route
    knowledge_type: KnowledgeType = KnowledgeType.NONE
    used_rag: bool = False
    retrieved: List[RetrievedChunk] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    safety_level: "SafetyLevel" = SafetyLevel.SAFE
    intent: "Intent" = Intent.SMALL_TALK
    used_memory: bool = False
