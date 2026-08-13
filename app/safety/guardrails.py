"""Deterministic safety rule engine (runs BEFORE any LLM call).

Ported and cleaned from the reference project's safety/rules.py. Priority:
    crisis/self-harm > harmful/illegal > sexual-procedural > programming > support

These rules fire on fast regexes so latency-critical safety signals are never
delayed by a network call. Model moderation is layered on top as a second net.
"""

from __future__ import annotations

import re

from app.normalize import despace, normalize_for_detection
from app.types import Language, ModerationSignal, ResponseMode, Route, SafetyDecision


class Guardrails:
    # --- crisis / self-harm ---
    _self_harm = re.compile(
        r"(want to die|wanna die|kill myself|killing myself|end my life|ending my life"
        r"|suicide|suicidal|hurt myself|harm myself|don'?t want to live|dont want to live"
        r"|cut myself|cutting myself|hang myself|overdose"
        # common euphemisms / community slang used to dodge filters
        r"|unalive myself|unalive me|end it all|end things|off myself|do myself in"
        r"|take my own life|not want to be alive|no longer want to be here"
        r"|\bkms\b|\bsewerslide\b|delete myself"
        # Hindi / Hinglish
        r"|marna chahta|marna chahti|khud ko maar|jaan dena|jaan de dun|khatam kar dun"
        r"|मरना चाहता|मरना चाहती|आत्महत्या|खुद को मारना|जान दे)",
        re.I,
    )
    _immediate_danger = re.compile(
        r"(i have pills ready|i have a knife|tonight i will kill myself|bleeding badly"
        r"|अभी मार रहा|अभी खतरा)",
        re.I,
    )

    # --- distress / emotional ---
    _distress = re.compile(
        r"\b(overwhelmed|anxious|anxiety|stressed|stress|burned out|burnout|drained|tired"
        r"|exhausted|alone|lonely|hopeless|numb|crying|hurt|heavy|frustrated|sad|depressed"
        r"|thak gaya|thak gayi|pareshan|akela|udaas|tension|ghabrahat"
        # understated phrasings people actually use
        r"|mood (?:is|isn'?t|is not|not) (?:good|great|okay|ok|fine)"
        r"|(?:bad|off|rough) day"
        r"|not feeling (?:so |too |very )?(?:good|great|okay|myself)"
        r"|feeling (?:kind of |kinda |a bit |a little |really |so )?(?:off|meh|flat|blah|low|down))\b",
        re.I,
    )

    # --- programming ---
    _code_block = re.compile(r"```|Traceback \(most recent call last\)", re.M)
    _programming_terms = re.compile(
        r"\b(coding|code|codes|debug(?:ging)?|traceback|stack trace|python|java(script)?|c\+\+|c#"
        r"|sql|html|css|react|node(?:\.?js)?|algorithm|compile|runtime|syntax error"
        r"|script|snippet|program|programming|regex|api call|function call)\b",
        re.I,
    )
    # Request-shaped phrasing, kept deliberately generic so a boundary cannot be
    # bypassed by rewording. Previously only "write a" matched, so "write it for
    # me" / "you need to write it" slipped past and the refusal was abandoned.
    _programming_intent = re.compile(
        r"\b(how to|how do i|write a|fix this|debug|create a function|build an app"
        r"|not working|compile|run this code|explain this code"
        # generic task requests
        r"|write (?:it|this|that|me|one|some)\b|(?:you|u) (?:need to|have to|should|must) write"
        r"|give me (?:the|a|some|that)?\s*(?:code|script|program|snippet|solution)"
        r"|send me (?:the|a)?\s*(?:code|script|program)"
        r"|(?:can|could|would|will) (?:you|u) (?:please )?(?:write|make|create|build|generate|code|do)"
        r"|(?:just )?(?:make|create|generate|build|code) (?:it|this|that|me|one)\b"
        r"|do it for me|write it for me|make it for me|need the code|want the code"
        r"|help me (?:write|code|build|make))\b",
        re.I,
    )

    # --- harmful / illegal ---
    _harmful_topics = re.compile(
        r"\b(hack(ing)?|phish|steal|fraud|scam|bomb|weapon|gun|poison|acid|malware|ddos"
        r"|drug dealing|kill someone|hurt someone|bypass security|murder|make a bomb)\b",
        re.I,
    )
    _harmful_native = re.compile(
        r"(मार दूं|मार दूँ|हत्या|क़त्ल|कत्ल|जान से मार|mar dunga|qatl)", re.I,
    )
    _instructional = re.compile(
        r"\b(how to|how do i|teach me|step by step|steps to|instructions for|guide me"
        r"|walk me through|show me how|best way to|make a|build a)\b",
        re.I,
    )

    # --- sexual (procedural / explicit) ---
    _sexual_procedural = re.compile(
        r"\b(how to have sex|how do i have sex|step by step sex|teach me sex|how to perform"
        r"|how to give oral|how to perform oral|what sex position|how to escalate physically"
        r"|how to go from (?:hugging|kissing) to more|intimacy steps|physical intimacy steps"
        r"|how to move forward physically)\b",
        re.I,
    )
    _sexual_explicit = re.compile(
        r"\b(blowjob|handjob|oral sex|penetrat(e|ion)|thrust|make (her|him) orgasm|fingering)\b",
        re.I,
    )

    # --- medication / medical requests (ported from legacy _MEDICAL_REQUEST_RE) ---
    # Must be checked BEFORE off-topic/knowledge routing: words like "suggest"
    # and "recommend" appear in medication asks and would misroute otherwise.
    _medical_request = re.compile(
        r"\b(pill|pills|tablet|tablets|medicine|medicines|medication|medications|drug|drugs"
        r"|anti.?anxiety|antidepressant|antidepressants|sedative|tranquilizer|xanax|prozac"
        r"|paracetamol|ibuprofen|over.the.counter|off.the.counter|otc|pharmacy|chemist"
        r"|prescription|prescribe|dose|dosage|\d+\s*mg|supplement|supplements)\b",
        re.I,
    )

    # --- frustration at being asked to repeat (legacy _REPEAT_FRUSTRATION_RE) ---
    _repeat_frustration = re.compile(
        r"\b(i just told you|i already said|i already told|didn'?t you read|you didn'?t read"
        r"|are you listening|weren'?t you listening|i said it already|i just said"
        r"|i told you already|as i said|ek baar bola tha|pehle hi bola|mujhe dobara mat poocho"
        r"|abhi bola tha)\b",
        re.I,
    )

    # --- clinical self-diagnosis asks (intellectual humility) ---
    _diagnosis_request = re.compile(
        r"\b(do i have|am i|do you think i have|diagnose me|is this)\b[^?]{0,40}"
        r"\b(bpd|adhd|ocd|ptsd|bipolar|borderline|depression|anxiety disorder|autism"
        r"|schizophrenia|personality disorder|clinical|disorder)\b"
        r"|\bdiagnose me\b|\bwhat'?s my diagnosis\b",
        re.I,
    )

    # --- helpline / emergency number asks ---
    _helpline_request = re.compile(
        r"\b(helpline|help\s*line|emergency\s*number|crisis\s*line|hotline|kiran"
        r"|suicide\s*helpline|mental\s*health\s*number)\b",
        re.I,
    )

    # --- identity / creator questions ---
    _identity_request = re.compile(
        r"\b(who are you|who are u|who r u|what are you|about you|who made you|who built you"
        r"|who developed you|who created you|your creator|who owns you|kisne banaya"
        r"|kisne develop|tum kaun ho|aap kaun ho|what is soulene|about soulene"
        r"|soulene kya hai)\b",
        re.I,
    )

    # --- wellness (protects grounding/breathing from sexual misclassification) ---
    _wellness = re.compile(
        r"\b(grounding|mindfulness|meditat(?:e|ion)|breath(?:e|ing)?|body scan|somatic"
        r"|relax(?:ation)?|calm down|calming|panic attack|coping|5[- ]?4[- ]?3[- ]?2[- ]?1)\b",
        re.I,
    )

    # --- harm to others / abuse / danger (graded safety) ---
    _harm_to_others = re.compile(
        r"\b(kill (him|her|them|someone|my)|hurt (him|her|them|someone)|stab|shoot (him|her|them)"
        r"|beat (him|her|them) up|i (want|am going) to (kill|hurt|attack)|take revenge on)\b",
        re.I,
    )
    _abuse_victim = re.compile(
        r"(\bhits me\b|\bhit me\b|\bbeats me\b|\bbeat me\b|\bhurts me\b|being abused|abusing me"
        r"|bad touch|touched me inappropriately|molest|domestic violence|forces me to"
        r"|not safe at home|threatens to hurt me|hits me every|beats me every)",
        re.I,
    )
    # Hidden / indirect distress (maps to SELF_HARM_CONCERN).
    _hidden_distress = re.compile(
        r"\b(no point (in )?(living|anymore)|what'?s the point|don'?t want to be here"
        r"|want it to (stop|end)|can'?t do this anymore|tired of living|give up on life"
        r"|everyone.{0,15}better off without me|disappear forever|nothing matters anymore"
        # ISS-11: expanded common phrasings of indirect despair
        r"|don'?t see the point( anymore)?"
        r"|nothing (seems|feels|is) worth it"
        r"|i'?m done (trying|with everything|with life|with this)"
        r"|wish i could (just )?disappear"
        r"|don'?t care what happens to me"
        r"|wouldn'?t matter if i (wasn'?t|weren'?t) here"
        r"|everyone would be (fine|better|okay) without me"
        r"|what'?s the use"
        r"|i give up"
        r"|i can'?t keep going"
        r"|no reason to (keep going|stay|be here|live)"
        r"|i'?m done with everything"
        r"|there'?s no point|there is no point"
        r"|life (isn'?t|is not) worth (it|living))\b",
        re.I,
    )

    # --- jailbreak / prompt injection (semantic-oriented) ---
    _jailbreak = re.compile(
        # Any "set aside your instructions" phrasing, not just "ignore".
        r"((?:ignore|disregard|forget|override|bypass|skip|discard|drop|erase|abandon|"
        r"disobey|unlearn|set aside)\s+(?:all |any |the |your |these |those )*"
        r"(?:previous|prior|above|earlier|initial|original|existing|system|preceding|safety)?\s*"
        r"(?:instructions?|rules?|prompts?|guidelines?|constraints?|restrictions?|directives?|training|scripts?|filters?)"
        r"|bypass (?:your )?safety|developer mode|dev mode|dan mode|jailbreak"
        r"|pretend (?:you have|there are) no rules|act as (?:if )?(?:you have no rules|the developer)"
        r"|you are (?:now )?(?:the )?(?:developer|admin|root)"
        r"|reset your (?:rules|instructions|prompt)"
        r"|(?:new|updated) (?:system )?(?:instructions?|prompt)\s*:"
        r"|drop (?:the |your )?(?:safety|act|persona|character))",
        re.I,
    )
    # Attempts to extract / reveal the hidden prompt or config.
    _prompt_extraction = re.compile(
        r"(reveal|show|share|print|output|repeat|tell me|give me|display|reveal to me)\b"
        r".{0,40}\b(system prompt|hidden (instructions|rules|prompt)|your (\w+ )?(instructions|rules|prompt|config"
        r"|configuration|guidelines|first (line|instruction)|initial prompt)|everything above"
        r"|prompt above|the text above|your setup|secret instructions)"
        r"|repeat everything above|what (are|were) your (instructions|rules)"
        r"|first (line|sentence) of your (prompt|instructions)"
        r"|(base64|encode|encoded|translate your) (your )?(prompt|instructions|system)"
        r"|output your (instructions|prompt|rules) as (json|text|list)",
        re.I,
    )
    _meta_question = re.compile(
        r"\b(what is|what does|meaning of|explain|why do you|how do you handle|tell me about)\b",
        re.I,
    )
    # Hindi / Hinglish injection & extraction attempts.
    _jailbreak_native = re.compile(
        r"(previous instructions? (?:bhula|bhool|ignore kar|chhod)"
        r"|apne (?:rules?|instructions?|niyam|guidelines?) "
        r"(?:bhula|bhool|bhul jao|bhool jao|bhula do|todo|tod do|tod do|chhod do|ignore)"
        r"|(?:rules?|niyam) (?:bhul jao|bhool jao|tod do|chhod do)"
        r"|sab (?:kuch )?(?:bata do|bata de|dikha do|reveal kar)"
        r"|system prompt (?:batao|bata do|bata de|dikhao|dikha do|share karo|reveal)"
        r"|tumhare (?:rules?|instructions?|niyam) (?:kya (?:hain|hai)|batao|dikhao)"
        r"|hidden (?:instructions?|rules?) (?:batao|dikhao|bata do)"
        r"|apna (?:prompt|system prompt) (?:batao|dikhao|likho|bata do)"
        r"|developer mode (?:on|chalu|activate|kar do)"
        r"|(?:sari|saari|apni) (?:secret|hidden|internal) .{0,20}(?:batao|dikhao|bata do)"
        r"|निर्देश (?:भूल|बताओ|दिखाओ)|सिस्टम प्रॉम्प्ट|अपने नियम (?:भूल|तोड़))",
        re.I,
    )

    # --- off-topic: domain boundary (this is a mental-health companion) ---
    _off_topic = re.compile(
        # coding / technical tasks
        r"\b(write|fix|debug|explain|generate|refactor|optimi[sz]e|compile|run)\b.{0,30}"
        r"\b(code|program|function|script|java|javascript|python|c\+\+|c#|css|html|react|sql|api|app)\b"
        r"|\b(python|javascript|java|css|html|react|sql)\b.{0,20}\b(correct|sahi|hello|code|program|error)\b"
        # math / homework
        r"|\b(solve|calculate|compute)\b.{0,20}\b(equation|math|sum|integral|derivative|problem)\b"
        r"|\bwhat is \d+\s*[\+\-\*/x]\s*\d+"
        # content generation
        r"|\bwrite (me )?(an? )?(essay|poem|song|story|article|blog|email|resume|cover letter)\b"
        r"|\b(translate|summari[sz]e) (this|the following)\b"
        # general-assistant / trivia domains
        r"|\b(who won|match score|cricket score|football score|election result|stock price"
        r"|weather (today|tomorrow|forecast)|recipe for|book a (flight|ticket|hotel)"
        r"|movie recommendation|latest news|capital of|population of)\b",
        re.I,
    )

    _practical = re.compile(
        r"\b(what should i do|what do i do|how should i|how do i handle|should i talk"
        r"|kya karu|kya karun|kaise handle|main kya karu)\b",
        re.I,
    )

    # ------------------------------------------------------------------
    # Obfuscation-resistant matching.
    # Every detector below tests the raw text AND a de-obfuscated variant, so
    # Unicode homoglyphs, zero-width splits, leetspeak and letter-spacing
    # cannot slip past a guardrail. Matching only ever ADDS coverage.
    # ------------------------------------------------------------------
    def _match(self, pattern: re.Pattern, message: str) -> bool:
        if not message:
            return False
        if pattern.search(message):
            return True
        normalized = normalize_for_detection(message)
        return bool(normalized and normalized != message.lower()
                    and pattern.search(normalized))

    # Compact (whitespace-free) signatures for uniformly spaced-out payloads
    # such as "i g n o r e a l l p r e v i o u s i n s t r u c t i o n s",
    # where word boundaries cannot be recovered.
    _COMPACT_INJECTION = re.compile(
        r"(ignore(all)?(previous|prior|the|your|my)?instructions?|disregard(all)?(previous|your)?instructions?"
        r"|ignoreyour(rules?|instructions?|prompts?|guidelines?)"
        r"|systemprompt|hiddeninstructions?|revealyourinstructions?|showyourprompt"
        r"|developermode|danmode|jailbreak|repeateverythingabove|yourinstructionsare"
        r"|forgetyour(rules?|instructions?)|bypassyour(safety|rules?|filters?))",
        re.I,
    )
    _COMPACT_SELF_HARM = re.compile(
        r"(killmyself|endmylife|unalivemyself|hurtmyself|cutmyself|hangmyself"
        r"|wanttodie|endital{1,2}|offmyself|\bkms\b)",
        re.I,
    )

    def _compact_match(self, pattern: re.Pattern, message: str) -> bool:
        """Match a whitespace-free signature. Catches ZWSP-split and spaced input."""
        if not message:
            return False
        # Run compact match on any message that might contain invisible chars or spaces
        despaced = despace(message)
        if not despaced:
            return False
        return bool(pattern.search(despaced))

    def decide(self, message: str, language: Language,
               moderation: ModerationSignal) -> SafetyDecision:
        lowered = message.lower()
        notes: list[str] = []

        wellness = bool(self._wellness.search(lowered))
        coding_stress = bool(self._programming_terms.search(lowered) and self._distress.search(lowered))

        # 1) CRISIS (highest priority)
        crisis = bool(self._self_harm.search(lowered) or self._immediate_danger.search(lowered))
        crisis = crisis or moderation.any_true("self_harm", "self_harm_intent", "self_harm_instructions")
        if crisis:
            notes.append("crisis_detected")
            return SafetyDecision(Route.CRISIS, language, ResponseMode.EMOTIONAL,
                                  distress=True, notes=notes)

        # 2) PROGRAMMING refusal (unless it's really about coding stress)
        if self._is_programming_request(lowered) and not coding_stress:
            return SafetyDecision(Route.REFUSAL, language, refusal_reason="programming", notes=notes)

        # 3) HARMFUL / ILLEGAL
        harmful = (
            (self._harmful_topics.search(lowered) or self._harmful_native.search(message))
            and self._instructional.search(lowered)
        )
        harmful = harmful or (
            moderation.any_true("illicit", "illicit_violent", "violence", "violence_graphic")
            and self._instructional.search(lowered)
        )
        if harmful:
            return SafetyDecision(Route.REFUSAL, language, refusal_reason="harmful", notes=notes)

        # 4) SEXUAL (procedural / explicit) — but never wellness
        if not wellness and (self._sexual_procedural.search(lowered)
                             or (self._sexual_explicit.search(lowered) and self._instructional.search(lowered))):
            return SafetyDecision(Route.REFUSAL, language, refusal_reason="sexual", notes=notes)

        # 5) SUPPORT
        if self._jailbreak.search(lowered) and not self._meta_question.search(lowered):
            notes.append("jailbreak_attempt")
        if wellness:
            notes.append("wellness_context")
        if coding_stress:
            notes.append("coding_stress_only")

        distress = bool(self._distress.search(lowered)) or coding_stress
        practical = bool(self._practical.search(lowered))

        if practical:
            mode = ResponseMode.ADVICE
        elif distress:
            mode = ResponseMode.EMOTIONAL
            notes.append("distress")
        else:
            mode = ResponseMode.BALANCED

        return SafetyDecision(Route.SUPPORT, language, mode, distress=distress, notes=notes)

    # ------------------------------------------------------------------
    # Graded safety assessment (used by the analyzer). Deterministic + fast.
    # ------------------------------------------------------------------
    def assess_safety_level(self, message: str, moderation: "ModerationSignal"):
        from app.types import SafetyLevel

        # Abuse victim first (being harmed by someone else).
        if self._match(self._abuse_victim, message):
            return SafetyLevel.ABUSE_OR_DANGER

        # Explicit self-harm BEFORE harm-to-others so "kill myself" isn't misread.
        explicit_self_harm = (
            self._match(self._self_harm, message)
            or self._compact_match(self._COMPACT_SELF_HARM, message)
            or moderation.any_true("self_harm", "self_harm_intent", "self_harm_instructions")
        )
        if explicit_self_harm:
            if self._match(self._immediate_danger, message):
                return SafetyLevel.IMMINENT_SELF_HARM
            return SafetyLevel.SELF_HARM_CONCERN

        if self._match(self._immediate_danger, message):
            return SafetyLevel.IMMINENT_SELF_HARM

        if self._match(self._harm_to_others, message):
            return SafetyLevel.HARM_TO_OTHERS

        if self._match(self._hidden_distress, message):
            return SafetyLevel.SELF_HARM_CONCERN

        if self._match(self._distress, message):
            return SafetyLevel.EMOTIONAL_DISTRESS

        return SafetyLevel.SAFE

    def is_injection(self, message: str) -> bool:
        if self._match(self._prompt_extraction, message):
            return True
        if self._match(self._jailbreak, message) and not self._match(self._meta_question, message):
            return True
        # Hindi / Hinglish phrasings of the same attacks.
        if self._match(self._jailbreak_native, message):
            return True
        # Uniformly spaced-out payloads.
        if (self._compact_match(self._COMPACT_INJECTION, message)
                and not self._match(self._meta_question, message)):
            return True
        return False

    def is_off_topic(self, message: str) -> bool:
        # A medication ask is an in-domain wellbeing concern, never "off topic".
        if self.is_medical_request(message):
            return False
        if self._is_programming_request((message or "").lower()):
            return True
        return self._match(self._off_topic, message)

    # --- ported legacy detectors (all obfuscation-resistant) ---
    def is_medical_request(self, message: str) -> bool:
        return self._match(self._medical_request, message)

    def is_repeat_frustration(self, message: str) -> bool:
        return self._match(self._repeat_frustration, message)

    def is_diagnosis_request(self, message: str) -> bool:
        return self._match(self._diagnosis_request, message)

    def is_helpline_request(self, message: str) -> bool:
        return self._match(self._helpline_request, message)

    def is_identity_request(self, message: str) -> bool:
        return self._match(self._identity_request, message)

    def is_harmful(self, message: str, moderation: "ModerationSignal") -> bool:
        local = bool(
            (self._match(self._harmful_topics, message)
             or self._match(self._harmful_native, message))
            and self._match(self._instructional, message)
        )
        moderated = moderation.any_true("illicit", "illicit_violent", "violence", "violence_graphic") \
            and self._match(self._instructional, message)
        return bool(local or moderated)

    def is_sexual_procedural(self, message: str) -> bool:
        if self._match(self._wellness, message):
            return False
        return bool(
            self._match(self._sexual_procedural, message)
            or (self._match(self._sexual_explicit, message)
                and self._match(self._instructional, message))
        )

    # ------------------------------------------------------------------
    # Confidence scoring: ambiguous restricted intent should ask ONE
    # clarifying question instead of hard-refusing a possibly-innocent user.
    # Ported from the legacy should_refuse(intent, confidence > 0.8) rule.
    # ------------------------------------------------------------------
    RESTRICTED_CONFIDENCE_THRESHOLD = 0.8

    def restricted_confidence(self, kind: str, message: str,
                              moderation: "ModerationSignal") -> float:
        lowered = (message or "").lower()
        score = 0.0
        if kind == "harmful":
            if self._harmful_topics.search(lowered) or self._harmful_native.search(message or ""):
                score += 0.50
            if self._instructional.search(lowered):
                score += 0.35
            if re.search(r"\b(step by step|steps|instructions|guide|exactly how)\b", lowered):
                score += 0.10
            if moderation.any_true("illicit", "illicit_violent", "violence", "violence_graphic"):
                score += 0.20
        elif kind == "sexual":
            if self._sexual_procedural.search(lowered):
                score += 0.85
            if self._sexual_explicit.search(lowered):
                score += 0.25
            if self._instructional.search(lowered):
                score += 0.15
        else:
            return 1.0
        return max(0.0, min(score, 0.99))

    def should_refuse(self, kind: str, message: str,
                      moderation: "ModerationSignal") -> bool:
        """True = hard refuse. False = ask one clarifying question instead."""
        return self.restricted_confidence(kind, message, moderation) > self.RESTRICTED_CONFIDENCE_THRESHOLD

    def _is_programming_request(self, lowered: str) -> bool:
        if self._code_block.search(lowered):
            return True
        # ISS-09 FIX: Only trigger off-topic programming refusal when message has
        # programming terms + instruction pattern BUT NO emotional keywords.
        # If any distress/emotion is present, it's an emotional conversation
        # about code — not a request for code help.
        if self._programming_terms.search(lowered) and self._programming_intent.search(lowered):
            if self._distress.search(lowered):
                return False  # "my python assignment is stressing me out" = in-domain
            return True
        return False

    # ------------------------------------------------------------------
    # Output safety: screen a generated reply before it reaches the user.
    # ------------------------------------------------------------------
    _out_self_harm = re.compile(
        r"\b(you should|just|try|go ahead and|step 1|first)\b.{0,40}"
        r"\b(kill yourself|end your life|take .*pills|jump from|cut yourself|hang yourself)\b",
        re.I,
    )
    _out_harm = re.compile(
        r"\b(you should|just|try|step 1|first)\b.{0,40}"
        r"\b(kill them|hurt them|make a bomb|build a bomb|hack (?:into|their)|poison them)\b",
        re.I,
    )

    def classify_output(self, text: str, moderation: ModerationSignal) -> str | None:
        lowered = text.lower()
        if moderation.any_true("self_harm", "self_harm_intent", "self_harm_instructions"):
            return "crisis"
        if moderation.any_true("illicit", "illicit_violent", "violence", "violence_graphic"):
            return "harmful"
        if self._out_self_harm.search(lowered):
            return "crisis"
        if self._out_harm.search(lowered):
            return "harmful"
        return None
