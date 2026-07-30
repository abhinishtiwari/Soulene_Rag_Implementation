"""ChatbotService - CAG-based mental health companion pipeline.

Per turn:
    clean -> moderate -> Analyzer (deterministic strategy)
      -> SAFETY gate            (crisis: no humour, no cache, no knowledge)
      -> hard refusals          (harmful / sexual)
      -> CAG lookup            (response cache -> knowledge cache)
           * response-cache hit  = ZERO LLM calls
           * knowledge injected  = ONE LLM call
      -> single main LLM call   (compact prompt)
      -> light output validation
      -> persist: context cache + profile memory + chat archive (async)

Memory layers are strictly separated:
    Layer 1 chat archive (complete)   - app/storage/chat_archive.py
    Layer 2 profile memory (<=50)     - app/memory/long_term_memory.py
    Layer 3 feedback DB (isolated)    - NOT referenced here, by design
    Layer 4 CAG knowledge cache       - app/cag/knowledge_cache.py
"""

from __future__ import annotations

from typing import Iterator, List, Optional

from app.cag.cag_engine import CAGEngine
from app.chatbot.analyzer import Analyzer
from app.chatbot.response_builder import ResponseBuilder
from app.config.settings import Settings
from app.llm.client import LLMClient
from app.memory.long_term_memory import LongTermMemory
from app.prompts.system_prompt import build_instructions, build_model_input
from app.safety.crisis import CrisisHandler
from app.safety.guardrails import Guardrails
from app.safety.refusal import RefusalHandler
from app.storage.chat_archive import ChatArchive
from app.types import (
    ChatResult,
    Intent,
    KnowledgeType,
    Language,
    ModerationSignal,
    ResponseStrategy,
    Route,
    SafetyLevel,
)
from app.utils import clean_message, strip_markdown

# Intents whose answers are factual and therefore safe to cache/reuse.
_CACHEABLE_INTENTS = {Intent.SOULENE_INFO, Intent.MENTAL_HEALTH_INFO}


class ChatbotService:
    def __init__(self, *, settings: Settings, client: Optional[LLMClient],
                 analyzer: Analyzer, guardrails: Guardrails, refusal: RefusalHandler,
                 crisis: CrisisHandler, cag: CAGEngine, profile: LongTermMemory,
                 response_builder: ResponseBuilder, archive: Optional[ChatArchive]):
        self.settings = settings
        self.client = client
        self.analyzer = analyzer
        self.guardrails = guardrails
        self.refusal = refusal
        self.crisis = crisis
        self.cag = cag
        self.profile = profile
        self.response_builder = response_builder
        self.archive = archive

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def handle(self, session_id: str, user_message: str, *,
               user_id: Optional[str] = None) -> ChatResult:
        user_id = user_id or session_id
        message = clean_message(user_message)
        if not message:
            return ChatResult(reply="I'm here whenever you're ready.", route=Route.SUPPORT)

        strategy = self._analyze(session_id, message)
        self._ingest_user_turn(user_id, session_id, message, strategy)

        route, reply, lookup = self._respond(session_id, user_id, message, strategy)
        reply = strip_markdown(reply) or self._fallback(strategy.language)

        self._ingest_assistant_turn(user_id, session_id, reply)

        # Cache factual answers only (never emotional replies).
        if (route == Route.SUPPORT and strategy.intent in _CACHEABLE_INTENTS
                and lookup is not None and not lookup.cache_hit):
            self.cag.store_answer(message, reply, lookup.sources)

        return ChatResult(
            reply=reply, route=route, knowledge_type=strategy.knowledge_type,
            used_rag=bool(lookup and (lookup.knowledge_hit or lookup.cache_hit)),
            retrieved=[], notes=[f"intent={strategy.intent.value}",
                                 f"emotion={strategy.emotion}",
                                 f"cache_hit={bool(lookup and lookup.cache_hit)}"],
            safety_level=strategy.safety_level, intent=strategy.intent,
            used_memory=strategy.memory_required,
        )

    def handle_message(self, session_id: str, user_message: str) -> str:
        return self.handle(session_id, user_message).reply

    def handle_stream(self, session_id: str, user_message: str, *,
                      user_id: Optional[str] = None) -> Iterator[str]:
        user_id = user_id or session_id
        message = clean_message(user_message)
        if not message:
            yield "I'm here whenever you're ready."
            return

        strategy = self._analyze(session_id, message)
        self._ingest_user_turn(user_id, session_id, message, strategy)

        # Cached factual answer -> emit instantly, zero LLM calls.
        lookup = self._lookup(message, strategy)
        if lookup.cached_answer:
            self._ingest_assistant_turn(user_id, session_id, lookup.cached_answer)
            yield lookup.cached_answer
            return

        # Turns needing deterministic post-checks are NOT streamed — the
        # validators must run before any text reaches the user.
        streamable = (
            self.client is not None
            and strategy.safety_level == SafetyLevel.SAFE
            and not strategy.medical_request
            and strategy.intent not in (Intent.HARMFUL, Intent.SEXUAL,
                                        Intent.OFF_TOPIC, Intent.INJECTION,
                                        Intent.MEDICAL_REQUEST, Intent.DIAGNOSIS_REQUEST,
                                        Intent.CLARIFY)
        )
        if not streamable:
            route, reply, _ = self._respond(session_id, user_id, message, strategy, lookup=lookup)
            reply = strip_markdown(reply) or self._fallback(strategy.language)
            self._ingest_assistant_turn(user_id, session_id, reply)
            yield reply
            return

        instructions, input_text = self._build_prompt(session_id, user_id, message, strategy, lookup)
        acc: List[str] = []
        try:
            for delta in self.client.generate_stream(
                    instructions=instructions, input_text=input_text, session_id=session_id):
                acc.append(delta)
                yield delta
        except Exception:
            if not acc:
                fb = self._fallback(strategy.language)
                acc.append(fb)
                yield fb

        full = strip_markdown("".join(acc)) or self._fallback(strategy.language)
        full = self.response_builder.scrub_leak(full, strategy.language)
        full = self._enforce_reply_policy(full, strategy)
        self._ingest_assistant_turn(user_id, session_id, full)
        if strategy.intent in _CACHEABLE_INTENTS and not lookup.cache_hit:
            self.cag.store_answer(message, full, lookup.sources)

    def clear(self, session_id: str) -> None:
        self.cag.context.clear(session_id)

    def stats(self) -> dict:
        return self.cag.stats()

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------
    def _analyze(self, session_id: str, message: str) -> ResponseStrategy:
        moderation = self._moderate(message)
        history = self.cag.context.all_cached(session_id)
        strategy = self.analyzer.analyze(message, moderation, history=history)

        if strategy.intent in (Intent.INJECTION, Intent.OFF_TOPIC):
            count = self.cag.context.bump(session_id, strategy.intent.value)
            strategy = self.analyzer.analyze(message, moderation, history=history,
                                             repeated_behaviour=count > 1,
                                             repetition_count=count)

        # --- session safety state (ported from legacy) ---
        # 1) Once a sexual boundary is set, later intimacy probes stay refused.
        if strategy.intent == Intent.SEXUAL:
            self.cag.context.bump(session_id, "sexual_boundary")
        elif (self.cag.context.counter(session_id, "sexual_boundary") > 0
              and self.guardrails.is_sexual_procedural(message)):
            strategy.intent = Intent.SEXUAL

        # 2) Repeated unsafe attempts -> strict mode (harden, never soften).
        if strategy.intent in (Intent.HARMFUL, Intent.SEXUAL, Intent.INJECTION):
            attempts = self.cag.context.bump(session_id, "unsafe_attempts")
            if attempts >= self.settings.strict_unsafe_threshold:
                strategy.humour = 0
                strategy.emoji = "none"
        return strategy

    def _ingest_user_turn(self, user_id, session_id, message, strategy) -> None:
        self._archive(user_id, session_id, "user", message)
        self.cag.context.append(session_id, "user", message)
        if (strategy.safety_level == SafetyLevel.SAFE
                and strategy.intent not in (Intent.INJECTION, Intent.HARMFUL, Intent.SEXUAL)):
            try:
                self.profile.observe(user_id, message)
            except Exception:
                pass  # memory failure must never break chat

    def _ingest_assistant_turn(self, user_id, session_id, reply) -> None:
        self._archive(user_id, session_id, "assistant", reply)
        self.cag.context.append(session_id, "assistant", reply)

    def _lookup(self, message: str, strategy: ResponseStrategy):
        # Knowledge is available for info questions even if the user is distressed
        # (e.g. "I'm anxious, what breathing exercise helps?") — but never in a crisis.
        needs_knowledge = strategy.rag_required and not strategy.safety_level.is_crisis
        try:
            return self.cag.lookup(
                message, needs_knowledge=needs_knowledge,
                knowledge_type=None if strategy.knowledge_type == KnowledgeType.NONE
                else strategy.knowledge_type.value,
                allow_response_cache=strategy.intent in _CACHEABLE_INTENTS,
            )
        except Exception:
            from app.cag.cag_engine import CAGLookup
            return CAGLookup()  # cache failure -> degrade to plain generation

    def _respond(self, session_id, user_id, message, strategy, lookup=None):
        """Return (route, reply, lookup)."""
        # 1) SAFETY FIRST.
        if strategy.safety_level.is_crisis:
            return (Route.CRISIS,
                    self.crisis.respond(strategy.language, message, session_id,
                                        safety_level=strategy.safety_level),
                    None)

        # 2) Deterministic hard refusals.
        if strategy.intent == Intent.HARMFUL:
            return Route.REFUSAL, self.refusal.respond("harmful", strategy.language), None
        if strategy.intent == Intent.SEXUAL:
            return Route.REFUSAL, self.refusal.respond("sexual", strategy.language), None

        # 2b) Helpline: the number must be authoritative, never model-invented.
        if strategy.intent == Intent.HELPLINE_REQUEST:
            return (Route.SUPPORT,
                    self.response_builder.helpline_reply(
                        strategy.language, self.settings.emergency_number),
                    None)

        # 3) CAG lookup.
        if lookup is None:
            lookup = self._lookup(message, strategy)
        if lookup.cached_answer:
            return Route.SUPPORT, lookup.cached_answer, lookup

        # 4) Single LLM call.
        reply = self._generate(session_id, user_id, message, strategy, lookup)
        reply = self.response_builder.apply_output_safety(
            session_id=session_id, user_message=message, reply=reply,
            language=strategy.language)
        reply = self._enforce_reply_policy(reply, strategy)
        route = Route.REFUSAL if strategy.intent == Intent.INJECTION else Route.SUPPORT
        return route, reply, lookup

    def _enforce_reply_policy(self, reply: str, strategy: ResponseStrategy) -> str:
        """Deterministic post-checks ported from the legacy output walls."""
        rb, lang = self.response_builder, strategy.language
        if strategy.intent == Intent.OFF_TOPIC:
            reply = rb.enforce_domain(reply, lang)
        # Never describe/recommend a rival app.
        reply = rb.enforce_no_other_apps(reply, lang)
        # Never market plans/pricing at someone asking about medication or in distress.
        if strategy.medical_request or strategy.safety_level == SafetyLevel.EMOTIONAL_DISTRESS:
            reply = rb.enforce_no_promo(reply, lang)
        # Never let an invented (often foreign) hotline number reach the user.
        reply = rb.enforce_helpline_number(reply, lang, self.settings.emergency_number)
        return reply

    # ------------------------------------------------------------------
    # Rolling summary: keeps continuity when messages scroll out of the
    # prompt window, without ever sending the whole transcript.
    # Built deterministically (no extra LLM call) from the overflow turns.
    # ------------------------------------------------------------------
    _SUMMARY_TOPICS = (
        ("work stress", ("work", "job", "boss", "office", "deadline", "career")),
        ("study/exam stress", ("exam", "study", "college", "school", "assignment", "semester")),
        ("anxiety", ("anxious", "anxiety", "panic", "nervous")),
        ("low mood", ("sad", "depressed", "low", "empty", "hopeless")),
        ("loneliness", ("lonely", "alone", "isolated", "akela")),
        ("sleep trouble", ("sleep", "insomnia", "awake", "tired", "exhausted")),
        ("relationship strain", ("partner", "girlfriend", "boyfriend", "wife", "husband",
                                 "breakup", "friend", "family", "parents")),
        ("grief", ("passed away", "died", "funeral", "grief", "lost my")),
        ("self-confidence", ("confidence", "worthless", "not good enough", "failure")),
        ("burnout", ("burnout", "burned out", "drained", "no energy")),
    )

    def _refresh_summary(self, session_id: str) -> None:
        """Update the rolling summary from turns that fell out of the window."""
        ctx = self.cag.context
        if not ctx.needs_summary(session_id):
            return
        overflow = ctx.overflow_turns(session_id)
        if not overflow:
            return
        blob = " ".join(t.content.lower() for t in overflow if t.role == "user")
        if not blob:
            return
        topics = [label for label, keys in self._SUMMARY_TOPICS
                  if any(k in blob for k in keys)]
        if not topics:
            return
        summary = "Earlier they talked about: " + ", ".join(topics[:5]) + "."
        ctx.set_summary(session_id, summary)

    def _build_prompt(self, session_id, user_id, message, strategy, lookup):
        memories, contradictions = [], []
        if strategy.memory_required:
            try:
                memories = self.profile.retrieve(user_id, message)
                contradictions = self.profile.contradiction_topics(user_id, message)
            except Exception:
                memories, contradictions = [], []
        self._refresh_summary(session_id)
        instructions = build_instructions(strategy)
        history = self.cag.context.formatted_window(session_id)
        input_text = build_model_input(
            message, history, lookup.knowledge_context if lookup else "",
            memories=memories, contradictions=contradictions,
            session_summary=self.cag.context.summary(session_id) or None,
            knowledge_missing=bool(lookup and strategy.rag_required and not lookup.knowledge_hit),
        )
        return instructions, input_text

    def _generate(self, session_id, user_id, message, strategy, lookup) -> str:
        if self.client is None:
            return self._fallback(strategy.language)
        instructions, input_text = self._build_prompt(session_id, user_id, message, strategy, lookup)
        try:
            reply = self.client.generate(instructions=instructions, input_text=input_text,
                                         session_id=session_id)
        except Exception:
            return self._fallback(strategy.language)
        return reply or self._fallback(strategy.language)

    def _moderate(self, message: str) -> ModerationSignal:
        if self.settings.enable_input_moderation and self.client is not None:
            try:
                return self.client.moderate(message)
            except Exception:
                return ModerationSignal()
        return ModerationSignal()

    def _archive(self, user_id, conversation_id, role, content) -> None:
        if self.archive is not None:
            try:
                self.archive.record(user_id, conversation_id, role, content)
            except Exception:
                pass

    def _fallback(self, language: Language) -> str:
        if language == Language.HINDI:
            return "मुझे अभी एक छोटा technical issue आ रहा है, लेकिन मैं यहीं तुम्हारे साथ हूँ।"
        if language == Language.HINGLISH:
            return "Mujhe abhi ek chhota technical issue aa raha hai, but main yahin tumhare saath hoon."
        return "I hit a small technical snag just now, but I'm still right here with you."


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def build_chatbot(settings: Optional[Settings] = None, *, client: Optional[LLMClient] = None,
                  build_client: bool = True, warm_cache: bool = True) -> ChatbotService:
    settings = settings or Settings.from_env()
    if client is None and build_client:
        try:
            client = LLMClient(settings)
        except Exception:
            client = None

    guardrails = Guardrails()
    analyzer = Analyzer(guardrails)
    refusal = RefusalHandler()
    crisis = CrisisHandler(settings, client=client)

    cag = CAGEngine(
        knowledge_dir=settings.knowledge_path,
        cache_dir=settings.root / "cache",
        token_budget=settings.knowledge_token_budget,
        context_cache_size=settings.context_cache_size,
        prompt_window=settings.prompt_window,
    )
    if warm_cache:
        try:
            cag.warm()
        except Exception:
            pass

    profile = LongTermMemory(storage_dir=settings.root / "data" / "profiles")
    response_builder = ResponseBuilder(settings, guardrails, refusal, crisis, client)
    try:
        archive = ChatArchive(settings.root / "data" / "chat_archive.sqlite3")
    except Exception:
        archive = None

    return ChatbotService(
        settings=settings, client=client, analyzer=analyzer, guardrails=guardrails,
        refusal=refusal, crisis=crisis, cag=cag, profile=profile,
        response_builder=response_builder, archive=archive,
    )
