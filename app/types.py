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
    PHYSICAL_DANGER = "physical_danger"
    HARM_TO_OTHERS = "harm_to_others"
    ABUSE_OR_DANGER = "abuse_or_danger"

    @property
    def is_crisis(self) -> bool:
        return self in {
            SafetyLevel.SELF_HARM_CONCERN,
            SafetyLevel.IMMINENT_SELF_HARM,
            SafetyLevel.PHYSICAL_DANGER,
            SafetyLevel.HARM_TO_OTHERS,
            SafetyLevel.ABUSE_OR_DANGER,
        }


class RiskDisposition(str, Enum):
    """Constrained response decision produced before reply generation."""

    NORMAL = "normal"
    SUPPORT = "support"
    URGENT_SAFETY = "urgent_safety"
    EMERGENCY = "emergency"
    REFUSE_HARMFUL = "refuse_harmful"
    REFUSE_SEXUAL = "refuse_sexual"


@dataclass
class RiskAssessment:
    """Structured conversation-level safety result; contains no chain-of-thought."""

    safety_level: "SafetyLevel" = SafetyLevel.SAFE
    disposition: "RiskDisposition" = RiskDisposition.NORMAL
    semantic_intent: str = "ordinary_conversation"
    emotional_state: str = "neutral"
    emotional_trajectory: str = "stable"
    overall_score: float = 0.0
    cumulative_score: float = 0.0
    self_harm_score: float = 0.0
    physical_danger_score: float = 0.0
    harm_to_others_score: float = 0.0
    emotional_distress_score: float = 0.0
    hazards: List[str] = field(default_factory=list)
    compound_factors: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    immediate_actions: List[str] = field(default_factory=list)
    intoxication_or_impairment: bool = False
    access_to_means: bool = False
    timing_immediate: bool = False
    isolation: bool = False
    farewell_or_finality: bool = False
    hopelessness: bool = False
    unsafe_framing: bool = False
    prompt_injection: bool = False
    danger_resolved: bool = False
    uncertainty: float = 0.0
    source: str = "deterministic"
    # True when THIS turn independently evidences crisis-level risk. False when
    # the level is elevated only by carried background risk from earlier turns.
    # Lets the responder use the full safety protocol for an acute moment but a
    # warm, non-repetitive reply once the user has moved on.
    acute_now: bool = True
    # Who the danger concerns: "self" (the user), "other" (someone they're
    # worried about), or "unclear". Defaults to "self" (conservative).
    risk_subject: str = "self"

    def to_dict(self) -> Dict[str, object]:
        data = dict(self.__dict__)
        data["safety_level"] = self.safety_level.value
        data["disposition"] = self.disposition.value
        return data


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
    risk_assessment: Optional["RiskAssessment"] = None
    # True when the message depends on earlier turns to be understood at all
    # (unbound pronoun, bare continuation, comparative with no subject).
    referential: bool = False

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
