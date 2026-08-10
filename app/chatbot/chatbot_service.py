"""ChatbotService - CAG-based mental health companion pipeline.

Per turn:
    clean -> restore transcript + safety state -> moderate
      -> conversation-level semantic risk fusion
      -> Analyzer (response strategy)
      -> SAFETY gate            (crisis: no humour, no cache, no knowledge)
      -> hard refusals          (harmful / sexual)
      -> CAG lookup            (response cache -> knowledge cache)
           * response-cache hit  = zero response-generation calls
           * knowledge injected  = one response-generation call
      -> main LLM call when needed (compact prompt)
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
from app.safety.reasoner import ConversationRiskReasoner
from app.safety.refusal import RefusalHandler
from app.storage.chat_archive import ChatArchive
from app.types import (
    ChatResult,
    Intent,
    KnowledgeType,
    Language,
    ModerationSignal,
    ResponseStrategy,
    RiskAssessment,
    Route,
    SafetyLevel,
    Turn,
)
from app.utils import clean_message, strip_markdown

# Intents whose answers are factual and therefore safe to cache/reuse.
_CACHEABLE_INTENTS = {Intent.SOULENE_INFO, Intent.MENTAL_HEALTH_INFO}


class ChatbotService:
    def __init__(self, *, settings: Settings, client: Optional[LLMClient],
                 analyzer: Analyzer, guardrails: Guardrails, refusal: RefusalHandler,
                 crisis: CrisisHandler, cag: CAGEngine, profile: LongTermMemory,
                 response_builder: ResponseBuilder, archive: Optional[ChatArchive],
                 risk_reasoner: Optional[ConversationRiskReasoner] = None):
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
        self.risk_reasoner = risk_reasoner or ConversationRiskReasoner(
            settings, guardrails, client)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def handle(self, session_id: str, user_message: str, *,
               user_id: Optional[str] = None) -> ChatResult:
        user_id = user_id or session_id
        message = clean_message(user_message)
        if not message:
            return ChatResult(reply="I'm here whenever you're ready.", route=Route.SUPPORT)

        context_id = self._context_id(user_id, session_id)
        self._ensure_context_loaded(user_id, session_id, context_id)
        history = self.cag.context.all_cached(context_id)
        moderation = self._moderate(message)
        risk = self.risk_reasoner.assess(
            session_id=session_id, latest_message=message, history=history,
            moderation=moderation,
            previous_state=self.cag.context.safety_state(context_id),
        )
        # Safety reasoning and its durable state are complete before any reply.
        self.cag.context.set_safety_state(context_id, risk.to_dict())
        self._persist_safety_state(user_id, session_id, risk)
        strategy = self._analyze(context_id, message, moderation, risk)

        route, reply, lookup = self._respond(
            session_id, user_id, context_id, message, strategy)
        reply = strip_markdown(reply) or self._fallback(strategy.language)

        # Persist a complete pair after generation so prompt history contains the
        # current message exactly once and failed generations do not leave orphans.
        self._ingest_user_turn(user_id, session_id, context_id, message, strategy)
        self._ingest_assistant_turn(user_id, session_id, context_id, reply)

        # FIX: Refresh the rolling summary unconditionally after every turn pair.
        # Previously this only ran inside _build_prompt(), so crisis/refusal/cache-hit
        # paths never updated the summary — causing context loss after 50+ responses.
        self._refresh_summary(context_id)

        if (route == Route.SUPPORT and strategy.intent in _CACHEABLE_INTENTS
                and lookup is not None and not lookup.cache_hit):
            self.cag.store_answer(message, reply, lookup.sources)

        return ChatResult(
            reply=reply, route=route, knowledge_type=strategy.knowledge_type,
            used_rag=bool(lookup and (lookup.knowledge_hit or lookup.cache_hit)),
            retrieved=[], notes=[f"intent={strategy.intent.value}",
                                 f"emotion={strategy.emotion}",
                                 f"risk_source={risk.source}",
                                 f"cumulative_risk={risk.cumulative_score:.2f}",
                                 f"cache_hit={bool(lookup and lookup.cache_hit)}"],
            safety_level=strategy.safety_level, intent=strategy.intent,
            used_memory=strategy.memory_required,
        )

    def handle_message(self, session_id: str, user_message: str) -> str:
        return self.handle(session_id, user_message).reply

    def handle_stream(self, session_id: str, user_message: str, *,
                      user_id: Optional[str] = None) -> Iterator[str]:
        """Emit only a fully assessed and validated reply.

        SSE remains API-compatible, but safety-sensitive model deltas are buffered
        by using the same completed pipeline as the non-streaming endpoint.
        """
        yield self.handle(session_id, user_message, user_id=user_id).reply

    def clear(self, session_id: str, user_id: Optional[str] = None) -> None:
        self.cag.context.clear(self._context_id(user_id or session_id, session_id))

    def stats(self) -> dict:
        return self.cag.stats()

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------
    def _analyze(self, context_id: str, message: str,
                 moderation: ModerationSignal,
                 risk: RiskAssessment) -> ResponseStrategy:
        history = self.cag.context.all_cached(context_id)
        strategy = self.analyzer.analyze(
            message, moderation, history=history, risk_assessment=risk)

        if strategy.intent in (Intent.INJECTION, Intent.OFF_TOPIC):
            count = self.cag.context.bump(context_id, strategy.intent.value)
            strategy = self.analyzer.analyze(
                message, moderation, history=history,
                repeated_behaviour=count > 1, repetition_count=count,
                risk_assessment=risk)

        if strategy.intent == Intent.SEXUAL:
            self.cag.context.bump(context_id, "sexual_boundary")
        elif (self.cag.context.counter(context_id, "sexual_boundary") > 0
              and self.guardrails.is_sexual_procedural(message)):
            strategy.intent = Intent.SEXUAL

        if strategy.intent in (Intent.HARMFUL, Intent.SEXUAL, Intent.INJECTION):
            attempts = self.cag.context.bump(context_id, "unsafe_attempts")
            if attempts >= self.settings.strict_unsafe_threshold:
                strategy.humour = 0
                strategy.emoji = "none"
        return strategy

    def _ingest_user_turn(self, user_id, session_id, context_id,
                          message, strategy) -> None:
        self._archive(user_id, session_id, "user", message)
        self.cag.context.append(context_id, "user", message)
        # ISS-06 FIX: Store memories from ALL messages EXCEPT injection/harmful/sexual.
        # Important personal details are often shared during vulnerable moments
        # (e.g. "my dad has cancer", "my friend died"). These MUST be remembered.
        if strategy.intent not in (Intent.INJECTION, Intent.HARMFUL, Intent.SEXUAL):
            try:
                self.profile.observe(user_id, message)
            except Exception:
                pass

    def _ingest_assistant_turn(self, user_id, session_id, context_id, reply) -> None:
        self._archive(user_id, session_id, "assistant", reply)
        self.cag.context.append(context_id, "assistant", reply)

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

    def _respond(self, session_id, user_id, context_id, message, strategy, lookup=None):
        """Return (route, fully validated reply, lookup)."""
        if strategy.safety_level.is_crisis:
            reply = self.crisis.respond(
                strategy.language, message, session_id,
                safety_level=strategy.safety_level,
                assessment=strategy.risk_assessment,
            )
            return Route.CRISIS, self._finalize_reply(
                session_id, message, reply, strategy), None

        if strategy.intent == Intent.HARMFUL:
            reply = self.refusal.respond("harmful", strategy.language)
            return Route.REFUSAL, self._finalize_reply(
                session_id, message, reply, strategy), None
        if strategy.intent == Intent.SEXUAL:
            reply = self.refusal.respond("sexual", strategy.language)
            return Route.REFUSAL, self._finalize_reply(
                session_id, message, reply, strategy), None

        if strategy.intent == Intent.HELPLINE_REQUEST:
            reply = self.response_builder.helpline_reply(
                strategy.language, self.settings.emergency_number)
            return Route.SUPPORT, self._finalize_reply(
                session_id, message, reply, strategy), None

        if lookup is None:
            lookup = self._lookup(message, strategy)
        if lookup.cached_answer:
            reply = self._finalize_reply(
                session_id, message, lookup.cached_answer, strategy)
            return Route.SUPPORT, reply, lookup

        reply = self._generate(
            session_id, user_id, context_id, message, strategy, lookup)
        reply = self._finalize_reply(session_id, message, reply, strategy)
        route = Route.REFUSAL if strategy.intent == Intent.INJECTION else Route.SUPPORT
        return route, reply, lookup

    def _finalize_reply(self, session_id: str, message: str, reply: str,
                        strategy: ResponseStrategy) -> str:
        reply = self.response_builder.apply_output_safety(
            session_id=session_id, user_message=message, reply=reply,
            language=strategy.language,
            risk_assessment=strategy.risk_assessment)
        return self._enforce_reply_policy(reply, strategy)

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
    # ISS-01/04 FIX: Use LLM to generate a rich narrative summary that
    # preserves specific details (names, events, timelines) instead of
    # just broad topic keywords.
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

    _SUMMARY_INSTRUCTION = (
        "Summarize what this person shared in 3-5 sentences. Focus on:\n"
        "- Their name (if mentioned)\n"
        "- Specific people they mentioned (names, relationships)\n"
        "- What they're going through (specific events, not just categories)\n"
        "- Any decisions or commitments they made\n"
        "- Their stated communication preferences\n"
        "- Timeline markers (dates, durations)\n"
        "Do NOT give advice. Only summarize what they said. Be specific, not generic."
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

        # ISS-01/04 FIX: Try LLM-based summary for rich context preservation.
        if self.client is not None:
            try:
                overflow_text = "\n".join(
                    f"{'User' if t.role == 'user' else 'Soulene'}: {t.content}"
                    for t in overflow
                )
                summary = self.client.generate(
                    instructions=self._SUMMARY_INSTRUCTION,
                    input_text=overflow_text[:3000],
                    session_id=f"{session_id}_summary",
                )
                if summary and len(summary.strip()) > 20:
                    ctx.set_summary(session_id, summary.strip()[:500])
                    return
            except Exception:
                pass  # Fall back to keyword-based summary below

        # Fallback: keyword-based summary (original logic)
        topics = [label for label, keys in self._SUMMARY_TOPICS
                  if any(k in blob for k in keys)]
        if not topics:
            return
        summary = "Earlier they talked about: " + ", ".join(topics[:5]) + "."
        ctx.set_summary(session_id, summary)

    def _build_prompt(self, session_id, user_id, context_id, message, strategy, lookup):
        memories, contradictions = [], []
        if strategy.memory_required:
            try:
                memories = self.profile.retrieve(user_id, message)
                contradictions = self.profile.contradiction_topics(user_id, message)
            except Exception:
                memories, contradictions = [], []
        # Summary is now refreshed unconditionally in handle() after every turn,
        # so no need to call _refresh_summary here.
        instructions = build_instructions(strategy)
        # The current turn has not been appended yet, so it appears exactly once
        # through `message` rather than being duplicated in recent history.
        history = self.cag.context.formatted_window(context_id)
        input_text = build_model_input(
            message, history, lookup.knowledge_context if lookup else "",
            memories=memories, contradictions=contradictions,
            session_summary=self.cag.context.summary(context_id) or None,
            knowledge_missing=bool(lookup and strategy.rag_required and not lookup.knowledge_hit),
        )
        return instructions, input_text

    def _generate(self, session_id, user_id, context_id, message, strategy, lookup) -> str:
        if self.client is None:
            return self._fallback(strategy.language)
        instructions, input_text = self._build_prompt(
            session_id, user_id, context_id, message, strategy, lookup)
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

    @staticmethod
    def _context_id(user_id: str, session_id: str) -> str:
        # Preserve legacy keys when user/session are identical; otherwise use a
        # collision-resistant, ownership-scoped in-memory key.
        if user_id == session_id:
            return session_id
        return f"{len(user_id)}:{user_id}{session_id}"

    def _persist_safety_state(self, user_id: str, session_id: str,
                              risk: RiskAssessment) -> None:
        save = getattr(self.archive, "save_safety_state", None)
        if callable(save):
            try:
                state = risk.to_dict()
                # ISS-13 FIX: Also persist counters and summary for restart resilience.
                context_id = self._context_id(user_id, session_id)
                counters = self.cag.context.get_counters(context_id)
                if counters:
                    state["counters"] = counters
                summary = self.cag.context.summary(context_id)
                if summary:
                    state["summary"] = summary
                save(user_id, session_id, state)
            except Exception:
                pass

    def _ensure_context_loaded(self, user_id: str, session_id: str,
                               context_id: Optional[str] = None) -> None:
        """Restore transcript and cumulative safety state for this owner/session."""
        context_id = context_id or self._context_id(user_id, session_id)
        if self.archive is None:
            return
        if not self.cag.context.all_cached(context_id):
            try:
                messages = self.archive.fetch_recent(
                    user_id, session_id, limit=self.settings.context_cache_size)
                if messages:
                    turns = [Turn(role=m.role, content=m.content) for m in messages]
                    self.cag.context.prime(context_id, turns)
            except Exception:
                pass
        if not self.cag.context.safety_state(context_id):
            load = getattr(self.archive, "load_safety_state", None)
            if callable(load):
                try:
                    state = load(user_id, session_id)
                    if state:
                        self.cag.context.set_safety_state(context_id, state)
                        # ISS-13 FIX: Restore counters and summary from persisted state.
                        if "counters" in state:
                            self.cag.context.restore_counters(
                                context_id, state["counters"])
                        if "summary" in state and state["summary"]:
                            self.cag.context.set_summary(
                                context_id, state["summary"])
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

    # --- Storage: MongoDB if MONGO_URI configured, else JSON files ---
    archive = None
    profile = None
    mongo_db = None

    if settings.mongo_uri and settings.db_name:
        try:
            from app.storage.mongo_client import get_mongo_db
            mongo_db = get_mongo_db(settings.mongo_uri, settings.db_name)
        except Exception:
            mongo_db = None

    if mongo_db is not None:
        # Production (Render): use MongoDB
        try:
            from app.storage.chat_archive_mongo import ChatArchiveMongo
            archive = ChatArchiveMongo(mongo_db)
        except Exception:
            pass
        try:
            from app.memory.long_term_memory_mongo import LongTermMemoryMongo
            profile = LongTermMemoryMongo(mongo_db)
        except Exception:
            profile = LongTermMemory(storage_dir=settings.root / "data" / "profiles")
    else:
        # Local development: use JSON files
        profile = LongTermMemory(storage_dir=settings.root / "data" / "profiles")
        try:
            from app.storage.chat_archive_json import ChatArchiveJSON
            archive = ChatArchiveJSON(settings.root / "data" / "chats")
        except Exception:
            pass

    if profile is None:
        profile = LongTermMemory(storage_dir=settings.root / "data" / "profiles")

    response_builder = ResponseBuilder(settings, guardrails, refusal, crisis, client)

    return ChatbotService(
        settings=settings, client=client, analyzer=analyzer, guardrails=guardrails,
        refusal=refusal, crisis=crisis, cag=cag, profile=profile,
        response_builder=response_builder, archive=archive,
    )
