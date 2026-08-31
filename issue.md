# Soulene RAG Audit — Issues

**Run:** `audit-20260827T102557885287Z-073047a3`  
**Production readiness:** **NOT READY** (fail-closed; final G8 result is published in the run artifacts).  
**Remediation progress:** 40 of 40 repository findings addressed. Closed with verified repository fixes: `ISSUE-001` – `ISSUE-005`, `ISSUE-006` – `ISSUE-016`, `ISSUE-018` – `ISSUE-025`, `ISSUE-027` – `ISSUE-031`, `ISSUE-033` – `ISSUE-036`, `ISSUE-038`. Qualified closures (repository-side done, an external or owner action remains — see the consolidated gate list below): `ISSUE-017`, `ISSUE-020`, `ISSUE-021`, `ISSUE-023`, `ISSUE-025`, `ISSUE-028`, `ISSUE-032`, `ISSUE-037`, `ISSUE-039`, `ISSUE-040`. Contained with an accepted Critical limitation: `ISSUE-026` (Git history not rewritten). No repository finding remains unaddressed.
**Scope:** Repository-proven static evidence plus network-denied isolated execution. No live external service or sensitive value was accessed or reproduced.

## Completed Issue Records

### ISSUE-008 — COMPLETE (repository implementation)

- **Problem:** Unsafe therapeutic output could pass through when the optional reviewer was disabled, unavailable, malformed, or failed. Deterministic checks did not cover diagnosis certainty, medication dosing, delusion reinforcement, dependency/coercion, treatment certainty, or shame/degradation.
- **Where it occurred:** `ResponseBuilder.apply_output_safety` and `_semantic_output_category`; the provider output-classification prompt; output-editor configuration in `Settings`, `.env.example`, and `render.yaml`.
- **Why it occurred:** Semantic review failures and unknown results were converted to `safe`, while the local output wall only covered leaks, ordinary harmful content, self-harm encouragement, code/domain restrictions, promotions, and helpline normalization.
- **Root cause:** A probabilistic external reviewer was treated as optional without an equivalent deterministic therapeutic-harm boundary or a fail-closed unavailable state.
- **Fix:** Added a deterministic therapeutic-harm taxonomy and bounded multilingual safety replacement; expanded semantic categories; made missing, malformed, unknown, and failed semantic review return `review_unavailable`; mapped that state to the bounded replacement; enabled the production output editor by default as defense in depth. Safe negated medication, non-diagnosis, reality-grounding, and anti-shame wording is explicitly preserved.
- **Files changed:** `app/chatbot/response_builder.py`, `app/llm/client.py`, `app/prompts/system_prompt.py`, `app/config/settings.py`, `.env.example`, `render.yaml`, `DEVELOPER_GUIDE.md`, `tests/test_reasoning_safety.py`, `issue.md`, `solution.md`.
- **Tests:** `python -m pytest -q tests/test_reasoning_safety.py` → 14 passed and 13 subtests passed; `python -m pytest -q tests/test_reasoning_safety.py tests/test_security.py tests/test_legacy_parity.py tests/test_upgrades.py` → 116 passed and 13 subtests passed; changed Python files compiled with `py_compile`.
- **Verification:** The original four synthetic harmful drafts are all replaced when output review raises. The end-to-end reviewer-failure test proves the replacement, not the unsafe draft, is archived and delivered. Safe-boundary counterexamples remain unchanged.
- **Remaining limitations:** Automated controls cannot establish clinical quality. A qualified mental-health safety reviewer must still approve wording/calibration before production, and live-provider behavior remains external to this repository verification.

### ISSUE-022 — COMPLETE (repository implementation)

- **Problem:** A public deployment could start without client or administrator authentication, and a configured client key became an administrator key when `ADMIN_API_KEY` was absent.
- **Where it occurred:** `Settings` had no production-auth requirement; `main.py` did not validate boundary credentials at startup; `ApiAuth.check_admin` fell back to ordinary client authentication; `render.yaml` did not declare fail-closed auth mode.
- **Why it occurred:** Local-development convenience (optional auth) was used as the only runtime mode, so production intent was documentation rather than enforceable configuration.
- **Root cause:** The application had no explicit production authentication invariant and no startup validation connecting deployment mode to separate credentials.
- **Fix:** Added `REQUIRE_API_AUTH`; startup now validates it before serving requests and requires distinct, non-empty `API_KEY` and `ADMIN_API_KEY` values. Document administration never falls back to the client key. Render explicitly enables fail-closed auth mode, while local development can explicitly leave it disabled.
- **Files changed:** `app/config/settings.py`, `app/security.py`, `main.py`, `.env.example`, `render.yaml`, `README.md`, `DEVELOPER_GUIDE.md`, `tests/test_spec_compliance.py`, `issue.md`, `solution.md`.
- **Tests:** Auth-focused spec run → 15 passed, 24 deselected, and 3 subtests passed; `tests/test_spec_compliance.py tests/test_api.py tests/test_security.py` → 98 passed and 3 subtests passed; startup subprocess verification proved invalid/equal production credentials fail import and distinct credentials succeed; changed Python files compiled with `py_compile`.
- **Verification:** A client key is rejected for document writes when no admin key exists. Production configuration cannot import/start with missing or equal credentials. The Render manifest enables the invariant.
- **Remaining limitations:** Credential generation, secure distribution, rotation, revocation, and live edge enforcement are operational controls outside this repository test. Shared keys are containment, not user-level authorization.

### ISSUE-001 — COMPLETE (repository implementation)

- **Problem:** A message longer than 4,000 characters was silently truncated, so risk-relevant wording after the retained prefix was never analyzed and the user was never told.
- **Where it occurred:** `app/utils.py::clean_message` performed the slice; `ChatbotService.handle` analyzed, generated from and persisted the truncated value; the `/chat` and `/chat/stream` routes passed oversized input straight through.
- **Why it occurred:** The 4,000-character bound existed only as a CPU/cost guard and was applied by quietly discarding the remainder, with no length error, marker, or tail inspection.
- **Root cause:** Truncation was used as input validation. A partially-read message was treated as if it were the user's complete message.
- **Fix:** Added `exceeds_message_limit` and a bounded multilingual `oversized_message_reply` in `app/utils.py`. `ChatbotService.handle` now refuses oversized input before analysis, safety assessment, generation, cache mutation or commit, returning a notice that states nothing was processed and asking for a shorter message. `/chat` and `/chat/stream` reject at the edge with HTTP 413 and the limit. `clean_message` keeps its cheap cap for already-accepted input, documented as CPU bounding only.
- **Files changed:** `app/utils.py`, `app/chatbot/chatbot_service.py`, `main.py`, `tests/test_hardening.py`, `tests/test_api.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction confirmed a 4,030-character message lost its `kill myself` suffix. Targeted run `python -m pytest -q tests/test_hardening.py -k "issue_001 or OversizedInput or oversized"` → 6 passed; `python -m pytest -q tests/test_hardening.py tests/test_api.py` → 68 passed and 2 subtests passed; full suite `python -m pytest -q tests --ignore=tests/test_mongo_integration.py` → 301 passed and 18 subtests passed; `py_compile` passed.
- **Verification:** The oversized message is refused whole with `rejected=message_too_long`, no turn is archived (`archive.count == 0`) and no context is cached, so no partial content reaches safety analysis or storage. Both HTTP chat routes return 413 with `max_chars`. `handle_stream` inherits the guard because it delegates to `handle`.
- **Remaining limitations:** The bound is refusal, not safety-aware segmentation; a user who writes a very long crisis message must resend a shorter one. The refusal wording is deliberately calm and non-escalating, and its clinical suitability still needs qualified mental-health reviewer sign-off (shared gate with ISSUE-008).

### ISSUE-002 — COMPLETE (repository implementation)

- **Problem:** Safety state and analyzer counters mutated before the authoritative commit, and rehydration never cleared process-local state when storage held none. A retry on the same worker could inherit escalation from a turn that never committed.
- **Where it occurred:** `ChatbotService.handle` (risk assessment, `set_safety_state`, `_analyze` counter bumps all ran before `_record_turn`); `ChatbotService._ensure_context_loaded` restored stored state but had no else-branch.
- **Why it occurred:** Derived in-memory state was treated as if it were part of the turn transaction, with no staging, rollback, or reset path.
- **Root cause:** Process-local derived state had no transactional boundary tied to the authoritative archive commit.
- **Fix:** Added `derived_snapshot`, `restore_derived` and `reset_derived` to `ContextCache`. `handle` snapshots derived state before analysis and restores it if anything up to and including `_record_turn` raises. `_ensure_context_loaded` now explicitly resets derived state when the archive holds no safety state, so storage is the only source of truth.
- **Files changed:** `app/cag/context_cache.py`, `app/chatbot/chatbot_service.py`, `tests/test_final_audit_remediation.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction showed populated crisis `safety_state` with zero archived turns after an injected `record_turn` failure; after the fix the same script shows empty state. Targeted run `-k Rollback` → 3 passed; full suite `python -m pytest -q tests --ignore=tests/test_mongo_integration.py` → 304 passed and 18 subtests passed.
- **Verification:** Three tests cover rollback after failure, retry-equals-fresh-instance decision parity, and rehydration clearing stale state. Nothing is archived on failure and no phantom state survives.
- **Remaining limitations:** Rollback is per-process. Under multiple workers a retry routed to a different worker relies on archive rehydration, which is correct but is the broader ISSUE-034 concern. Hard process termination mid-turn still leaves nothing committed, which is the intended fail-safe.

### ISSUE-003 — COMPLETE (repository implementation)

- **Problem:** Injection-classified input still reached the model, and the prompt assembled recent history, cross-session text, summary, memories and knowledge for that call. Containment depended on the model obeying instructions plus output filters.
- **Where it occurred:** `ChatbotService._respond` only relabelled the route as `REFUSAL` after generating; `ChatbotService._build_prompt` assembled full privileged context.
- **Why it occurred:** Injection was handled as a prompt-hardening concern (different instructions/wording) rather than as a boundary that must not invoke the model.
- **Root cause:** No deterministic no-model path existed for injection, so context minimization was never enforced server-side.
- **Fix:** Added a deterministic, language-matched injection refusal (`RefusalHandler.respond("injection", …)`, small varied pool) and short-circuited it in `_respond` immediately after the crisis check. No model call, no context assembly, no cache/knowledge lookup. Removed the now-dead post-generation `INJECTION → REFUSAL` relabel.
- **Files changed:** `app/safety/refusal.py`, `app/chatbot/chatbot_service.py`, `tests/test_security.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction showed 1 model call whose prompt contained the user's therapist name and city; after the fix it is 0 calls. Targeted run `-k "issue_003 or Injection"` → 9 passed; full suite → 305 passed and 18 subtests passed.
- **Verification:** Crisis still outranks injection (`test_crisis_takes_priority_over_injection` passes), repeated attempts still hold the boundary, multi-turn extraction is still refused, and the reply contains no prior-context values.
- **Remaining limitations:** Containment depends on injection classification accuracy; a message that evades the classifier still follows the normal generation path with labelled-untrusted context, which is the residual ISSUE-015 concern.

### ISSUE-004 — COMPLETE (repository implementation)

- **Problem:** Upload saved the file before indexing and left it behind when ingest failed; deletion removed the index entry first and then unlinked **every** file matching the sanitized basename anywhere under `knowledge/`.
- **Where it occurred:** `main.py::upload_document` (save then `refresh_documents` with no compensation) and `main.py::delete_document` (`rglob(safe)` loop).
- **Why it occurred:** Filesystem and index mutations were independent steps with no staging, compensation, or exact-path identity.
- **Root cause:** Document lifecycle had no transaction protocol and deletion resolved targets by basename pattern rather than by the indexed document's actual path.
- **Fix:** `KnowledgeCache` now records `relative_path` per document and exposes `document_path`, which returns the exact backing file (and refuses to guess when a legacy cache has ambiguous duplicates). Upload stages any previous version under an unindexed `.prev` name, then compensates on ingest failure by restoring the prior file and reconciling the index. Deletion resolves one exact path, unlinks that file first, then removes the index entry, reconciling via refresh if the index step fails.
- **Files changed:** `app/cag/knowledge_cache.py`, `main.py`, `tests/test_api.py`, `issue.md`, `solution.md`.
- **Tests:** Targeted run `-k issue_004` → 3 passed (failed-ingest rollback leaves no file and no `.prev`; failed re-upload restores the original content; delete removes only the exact file and spares a same-named document in another folder). Full suite → 308 passed and 18 subtests passed.
- **Verification:** After an injected `refresh_documents` failure the filesystem matches the pre-upload state, and a duplicate-basename document in a different knowledge type survives deletion of its twin.
- **Remaining limitations:** Documents are still keyed by basename in the index, so two same-named files cannot both be indexed — that identity defect is ISSUE-012 and is fixed separately. Rollback is best-effort on a crash between steps; the next forced refresh reconciles. Concurrent uploads of the same name across workers remain ISSUE-014/ISSUE-034.

### ISSUE-006 — COMPLETE (repository implementation; clinical review gate open)

- **Problem:** Self-harm phrase matching ignored negation, tense, quotation and subject, so benign or contextual disclosures received the full self-directed crisis protocol.
- **Where it occurred:** `Guardrails.decide` (step 1 crisis) and `Guardrails.assess_safety_level` (explicit self-harm branch).
- **Why it occurred:** Both paths tested raw phrase presence with no contextual parser, so `I would never kill myself` and `I want to kill myself` were indistinguishable.
- **Root cause:** The deterministic floor treated lexical presence of a phrase as evidence of present first-person intent.
- **Fix:** Added `contextual_self_harm_only`, which blanks out only provable non-current constructs (negation governing an intent verb, `would never`, past tense plus an explicit past marker, non-first-person attribution that cannot cross a clause boundary) and then re-runs plain, compact and immediate-danger detection on the remainder. De-escalation is refused when anything acute survives, when moderation independently flagged self-harm, or when the text is spaced/obfuscated. A defused disclosure returns `EMOTIONAL_DISTRESS` so the user stays supported rather than ignored.
- **Files changed:** `app/safety/guardrails.py`, `tests/test_hardening.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction showed five negated/historical/attributed messages all routed to crisis. Targeted run `-k SelfHarmContext` → 3 passed and 16 subtests passed; full suite → 311 passed and 34 subtests passed.
- **Verification:** Six step-down cases now resolve to `EMOTIONAL_DISTRESS` with a non-crisis route; ten must-escalate cases (present intent, past tense without a marker, `don't think I can stop myself`, `I never told anyone I want to…`, `I said I want to…`, `don't want to live`, spaced evasion, and a mixed attributed+first-person sentence) all remain crisis. A moderation-flagged message is never defused.
- **Remaining limitations:** MANUAL/CLINICAL GATE — a qualified mental-health reviewer must approve both the step-down target level and the resulting response wording. Bare quotation without attribution is intentionally left escalated. Coverage is English-centric; Hindi/Hinglish negated forms are not yet defused and therefore stay conservative (over-escalation, not under-escalation). Broader multilingual and euphemistic calibration remains ISSUE-031.

### ISSUE-007 — COMPLETE (repository implementation; clinical review gate open)

- **Problem:** When the semantic classifier errored, timed out, or returned malformed output, the reasoner silently fell back to current-message deterministic signals. The result was reported as an ordinary `deterministic` assessment with `uncertainty=0.0`, and multi-turn trajectory meaning was lost.
- **Where it occurred:** `ConversationRiskReasoner.assess` (bare `except Exception: raw = {}`, `source` left as `deterministic`); malformed output also produced an empty dict with no signal.
- **Why it occurred:** Failure was treated as equivalent to "semantic safety disabled", and no deterministic replacement existed for cumulative/evolving risk.
- **Root cause:** No explicit uncertainty state and no deterministic trajectory floor, so classifier loss silently reduced safety coverage.
- **Fix:** `assess` now distinguishes success, disabled, and attempted-but-unusable. The last case sets `source="deterministic_degraded"`, raises `uncertainty` to at least 0.6, and emits a redacted warning (failure type and counts only, never message content). Added `_apply_trajectory_floor`, which scans the recent user window for accumulating finality/withdrawal markers and per-turn deterministic distress. Two markers, or one marker plus two distress turns, escalate to `SELF_HARM_CONCERN` with `acute_now=False`, which routes to the calm `gentle_followup` check-in rather than the full emergency script. A single marker never escalates, preserving the ISSUE-006 calibration.
- **Files changed:** `app/safety/reasoner.py`, `tests/test_reasoning_safety.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction showed a give-away-possessions/farewell-letters sequence ending at `SAFE` with `uncertainty=0.0` while the classifier raised. Targeted run `-k issue_007` → 3 passed; full suite → 314 passed and 34 subtests passed.
- **Verification:** With the classifier failing, turn 1 (single marker) stays non-crisis, turn 2 reaches `SELF_HARM_CONCERN` with `source=deterministic_degraded`, `uncertainty≥0.6`, evidence `degraded_semantic_review`, and `acute_now=False`. A three-turn benign control stays `SAFE` while still recording degradation. Malformed (non-JSON) classifier output is also classified as degraded.
- **Remaining limitations:** MANUAL/CLINICAL GATE — the check-in threshold (two markers) and the check-in wording need qualified mental-health reviewer approval. Marker coverage is English-centric and finite; euphemism completeness cannot be proven and remains ISSUE-031. Operational alerting on the emitted warning is external (ISSUE-039).

### ISSUE-009 — COMPLETE (repository implementation)

- **Problem:** Model-generated rolling summaries were stored and fed back into later prompts without passing any output-safety validation, so a hallucinated, unsafe or adversarial summary could bias many subsequent turns.
- **Where it occurred:** `ChatbotService._refresh_summary` stored `client.generate(...)` output directly; `_build_prompt` reused it every turn.
- **Why it occurred:** Summaries were treated as internal plumbing rather than as untrusted model output, so they bypassed the walls a user-visible reply must clear.
- **Root cause:** Derived context had no validation, provenance, or contradiction gate before persistence and reuse.
- **Fix:** Added `ResponseBuilder.contains_unsafe_derived_text`, reusing the existing leak/secret/therapeutic-harm walls for derived text. `ChatbotService._validated_summary` screens every generated summary for those harms plus prompt injection, and rejects any summary asserting that risk has resolved while the authoritative safety state is still crisis-level. Rejected summaries are discarded (never stored or reused) and the deterministic excerpt of the user's own words is used instead, with a redacted warning. Added `summary_source` provenance to `ContextCache`, persisted in safety state and restored on rehydration.
- **Files changed:** `app/chatbot/response_builder.py`, `app/chatbot/chatbot_service.py`, `app/cag/context_cache.py`, `tests/test_final_audit_remediation.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction stored an injected summary containing `ignore all previous instructions`, a false bipolar diagnosis and a dosing instruction; after the fix it is rejected and replaced. Targeted run `-k DerivedSummary` → 3 passed; full suite → 317 passed and 34 subtests passed.
- **Verification:** The poisoned summary never reaches storage or the prompt; a safe summary is stored with `summary_source="model"`; provenance survives rehydration (a defect found and fixed during testing, where restore reset the source to `deterministic`); a resolution claim is rejected during an active crisis but accepted when no crisis is present.
- **Remaining limitations:** Contradiction detection is limited to unsafe risk-resolution claims, not general factual consistency against the transcript. Summary expiry/retention is deferred to ISSUE-017, and user-facing summary correction is a product feature that is not implemented. Only the deterministic fallback is guaranteed to be non-model text.

### ISSUE-010 — COMPLETE (repository implementation; external verification gate open)

- **Problem:** One deployment-wide emergency number was asserted to every user in crisis with no evidence it applied to their location, creating false confidence about available help.
- **Where it occurred:** `CrisisHandler._steps` and `respond_third_party` (and its model instructions), `ResponseBuilder.helpline_reply`, `ResponseBuilder.enforce_helpline_number` via `ChatbotService._enforce_reply_policy`; `EMERGENCY_NUMBER` in `render.yaml`.
- **Why it occurred:** The configured number was treated as universally correct; nothing distinguished "a number we know applies here" from "a number someone happened to configure".
- **Root cause:** No representation of resource applicability, so an unverified value was spoken with full authority.
- **Fix:** Added `EMERGENCY_LOCALE` and `Settings.emergency_contact_is_verified`. New `app/safety/emergency.py` resolves a single reference used by every call site: the number when a locale is declared human-verified, otherwise neutral multilingual wording ("your local emergency services"). The verified-number registry is deliberately **not** hardcoded, since emergency-resource correctness is a human validation responsibility. Render declares `EMERGENCY_LOCALE` as an unset secret so production defaults to the safe neutral wording until a human verifies.
- **Files changed:** `app/safety/emergency.py` (new), `app/config/settings.py`, `app/safety/crisis.py`, `app/chatbot/chatbot_service.py`, `.env.example`, `render.yaml`, `DEVELOPER_GUIDE.md`, `tests/test_legacy_parity.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction compared both modes end to end. Targeted run `-k "Emergency or Helpline"` → 12 passed; full suite → 321 passed and 34 subtests passed.
- **Verification:** With no locale declared, the helpline reply, crisis steps and third-party guidance contain no number and use neutral wording; with `EMERGENCY_LOCALE=IN` the number is named. Invented foreign hotlines (988, 1-800-273-8255, 116 123) are still replaced in both modes. The end-to-end helpline test now asserts the resolved reference rather than a hardcoded number.
- **Remaining limitations:** MANUAL/EXTERNAL GATE — no locale detection exists, so the operator must declare the served locale, and a qualified human must verify the number's correctness and coverage before setting `EMERGENCY_LOCALE`. Per-user geolocation, a multi-locale resource directory, and periodic re-verification of resources are not implemented and remain external acceptance work.

### ISSUE-011 — COMPLETE (repository implementation; clinical review gate open)

- **Problem:** Relational boundaries (exclusivity, emotional dependency, coercion, false authority, replacing professional care) existed only as prompt instructions. Server-side output control covered none of them, and there was no longitudinal dependency detector.
- **Where it occurred:** `app/prompts/system_prompt.py::build_instructions` (advice only); `ResponseBuilder.apply_output_safety` (the ISSUE-008 wall covered a narrow subset); no multi-turn indicator anywhere.
- **Why it occurred:** Boundary behaviour was delegated to model compliance, which is probabilistic and drifts, so nothing enforced it in the final output path.
- **Root cause:** No deterministic relational-boundary taxonomy and no cumulative dependency signal.
- **Fix:** Broadened the deterministic `dependency_or_coercion` rules to cover exclusivity/isolation from other support, replacement of professional care, claimed superiority over the user's real relationships, coercive commitments, false permanence/total reliance, and special-bond framing. Ordinary warmth is explicitly preserved. Added `Guardrails.expresses_dependency` for user-side exclusive-reliance disclosures, counted per conversation in `ContextCache`, and an escalation policy: `ResponseBuilder.append_relational_boundary` adds one warm nudge toward human/professional support on every third disclosure, only on the disclosure turn itself.
- **Files changed:** `app/chatbot/response_builder.py`, `app/safety/guardrails.py`, `app/chatbot/chatbot_service.py`, `tests/test_hardening.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction showed all six relational violations passing through unchanged. Targeted run `-k RelationalBoundary` → 4 passed and 20 subtests passed; full suite → 325 passed and 54 subtests passed.
- **Verification:** Seven relational-harm replies are now blocked while five ordinary warm/supportive replies (including "I'm here for you" and recommending a therapist) are preserved unchanged. Dependency disclosures are detected without firing on ordinary loneliness, and the boundary appears on the third disclosure only — not on subsequent ordinary turns, a repetition defect found and fixed during testing.
- **Remaining limitations:** MANUAL/CLINICAL GATE — the boundary wording, the every-third-disclosure cadence, and the step from nudge to stronger escalation all need qualified mental-health reviewer approval. Detection is pattern-based and English-centric; paraphrased dependency in Hindi/Hinglish is not yet counted. No cross-session dependency trend exists (counters are per conversation), and adversarial coverage breadth remains ISSUE-031.

### ISSUE-012 — COMPLETE (repository implementation)

- **Problem:** `KnowledgeCache` keyed documents by basename, so two supported files with the same filename in different folders collapsed into one entry. One document silently replaced the other and its content became unretrievable.
- **Where it occurred:** `KnowledgeCache._scan` (`found[path.name]`), `refresh` (`_doc_hashes`/`_doc_meta` keyed by basename), `process_document` metadata (`"document": path.name`), and basename-based removal.
- **Why it occurred:** The basename was treated as a unique document identity, which it is not for a recursive directory scan.
- **Root cause:** Document identity was not canonical.
- **Fix:** Keyed documents by canonical POSIX relative path everywhere (scan, hashes, metadata, section metadata, persisted payload), with `display_name` retained for presentation. Added `resolve_document`, which accepts a relative path or an unambiguous basename and returns `None` on collision, so `document_path` and `remove_document` refuse to guess. The delete route now preserves subdirectories while rejecting absolute paths and `..` components. Added `CACHE_VERSION = 2` plus `_migrate_payload`, which upgrades a legacy basename-keyed cache in place: unambiguous documents keep their preprocessed sections, colliding basenames are dropped so refresh re-keys both copies.
- **Files changed:** `app/cag/knowledge_cache.py`, `app/cag/document_processor.py`, `main.py`, `tests/test_cag.py`, `tests/test_api.py`, `tests/test_hardening.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction indexed 1 of 2 documents and lost the company pricing content. Targeted run `-k DocumentIdentity` → 5 passed; full suite → 330 passed and 54 subtests passed.
- **Verification:** Both `company/pricing.md` and `wellness/pricing.md` are indexed and both prices reach the context. An ambiguous basename resolves to `None`, is refused for deletion, and leaves both documents intact; the exact relative path removes exactly one. Real-cache migration preserved all 181 preprocessed sections and upgraded the payload to v2.
- **Additional defects found and fixed during verification:** (1) `refresh` treated a document as unchanged whenever its hash matched, even when the held section count disagreed with recorded metadata, so an inconsistent cache reported "unchanged" forever and silently served an incomplete corpus; it now reprocesses on inconsistency. (2) An initial reject-on-version-mismatch design destroyed preprocessed PDF sections that cannot be regenerated where the optional `fitz` dependency is missing, which is why migration replaced rejection.
- **Remaining limitations:** Identity is path-based, so moving or renaming a file is a delete plus add and its preprocessed sections are rebuilt; content-hash immutable IDs are not implemented. Document labels in prompts now show the relative path, which improves provenance but does not add user-visible citations (ISSUE-016). `cache/knowledge_cache.json` remains tracked in Git despite `cache/` being ignored, which is a maintainability wart related to ISSUE-035 rather than this fix. PDF ingestion still requires the optional `fitz` dependency.

### ISSUE-013 — COMPLETE (repository implementation)

- **Problem:** When the corpus exceeded the token budget and lexical search found nothing, context construction fell back to the first twenty cached sections, so the model received irrelevant material and could answer while appearing grounded.
- **Where it occurred:** `KnowledgeCache.build_context` (`if not picked: picked = self._sections[:20]`).
- **Why it occurred:** "No relevant knowledge" had no representation, so the code substituted arbitrary content rather than reporting absence.
- **Root cause:** Missing no-result semantics in retrieval.
- **Fix:** `build_context` returns `("", [])` on a lexical miss. `CAGEngine.lookup` already derives `knowledge_hit` from a non-empty context, so the existing uncertainty instruction ("nothing relevant is available … do not guess") now applies automatically. Knowledge-type filtering is unchanged on the narrowing path.
- **Files changed:** `app/cag/knowledge_cache.py`, `tests/test_cag.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction returned 2,145 characters of unrelated content with zero lexical hits. Targeted run `-k NoResultRetrieval` → 4 passed; full suite → 334 passed and 54 subtests passed.
- **Verification:** A disjoint query returns empty context and no sources, and the engine reports `knowledge_hit=False`. A matching query still returns content, and `knowledge_type="wellness"` still yields only `wellness/` sources.
- **Remaining limitations:** Retrieval is lexical, so a semantically relevant document with no shared vocabulary is still a miss — now an honest miss rather than a wrong answer. Synonym expansion mitigates but cannot eliminate this. Claim-level citation of retrieved support remains ISSUE-016.

### ISSUE-014 — COMPLETE (repository implementation)

- **Problem:** Cache persistence staged every write through one predictable `knowledge_cache.tmp` path, so concurrent workers could overwrite each other's partial bytes, fail the replace, or publish a cache that matched neither worker's index.
- **Where it occurred:** `KnowledgeCache.save` (`tmp = self._cache_path().with_suffix(".tmp")`), reached from `refresh` and `remove_document`; `render.yaml` runs two workers.
- **Why it occurred:** Atomic `replace` protects the final swap but not a shared staging filename, and nothing compared build freshness between writers.
- **Root cause:** Shared mutable staging path plus no version check on publish.
- **Fix:** `save` now stages through a unique `tempfile.mkstemp` file in the cache directory and publishes with `os.replace`. A build-version guard skips the write when the on-disk cache has a newer `built_at`, so an older worker cannot clobber a fresher build; `remove_document` bumps `built_at` so a deletion still wins against an older copy. The publish retries briefly on a transient Windows `PermissionError` and then yields with a warning, because the cache is rebuildable and the in-memory index is already correct.
- **Files changed:** `app/cag/knowledge_cache.py`, `tests/test_cag.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction produced 5 `PermissionError` failures from six concurrent writers sharing the staging name; after the fix repeated runs report 0 errors. Targeted run `-k ConcurrentCache` → 3 passed; full suite → 337 passed and 54 subtests passed.
- **Verification:** Six concurrent writers performing 40 saves each raise nothing and leave a parseable v2 cache with sections intact; no `.knowledge_cache-*` staging files or legacy `knowledge_cache.tmp` remain; a deliberately older build does not overwrite a newer published one.
- **Remaining limitations:** This is last-writer-wins with a freshness guard, not a distributed lock, so two workers can still rebuild the same corpus redundantly. Coordinated single-build election across workers is part of ISSUE-034. The guard compares timestamps, so severe clock skew between workers could misorder publishes.

### ISSUE-015 — COMPLETE (repository implementation)

- **Problem:** Long-term memory, cross-session digests, rolling summaries and retrieved documents were concatenated into the prompt as plain prose. Containment relied on sentence-level warnings, and two blocks (session summary, stored memory) carried no untrusted warning at all. Instruction-like stored text reached the model verbatim.
- **Where it occurred:** `app/prompts/system_prompt.py::build_model_input` (prose labels only) and `ChatbotService._build_prompt` (no content policy scan).
- **Why it occurred:** The trust boundary was expressed as advice to the model rather than as structure plus filtering, so it depended on the model choosing to honour it.
- **Root cause:** No structural data channel, no provenance/trust tiers, and no ingestion or retrieval policy scan for instruction-like content.
- **Fix:** Added `untrusted_block` in `system_prompt.py`, which fences every external block with an explicit trust tier (`PRIOR_SESSIONS`, `SESSION_SUMMARY`, `STORED_MEMORY`, `RECENT_TURNS`, `KNOWLEDGE_DOCUMENTS`) and neutralises `<<<`/`>>>` inside the content so stored text cannot forge a closing fence. Added `Guardrails.scrub_instruction_like`, which drops instruction-like sentences (sentence granularity, so legitimate text sharing a line survives). It is applied at document **ingestion** in `KnowledgeCache.refresh` and per request to the small bounded blocks (cross-session, summary), while instruction-like memory records and contradiction topics are filtered out. The current user turn stays outside every fence.
- **Files changed:** `app/prompts/system_prompt.py`, `app/safety/guardrails.py`, `app/cag/knowledge_cache.py`, `app/chatbot/chatbot_service.py`, `tests/test_security.py`, `tests/test_pipeline.py`, `tests/test_hardening.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction showed all four poison payloads present and the summary/memory blocks unlabelled. Targeted run `-k UntrustedContext` → 4 passed; full suite → 341 passed and 54 subtests passed.
- **Verification:** Every external block is fenced with a tier and the current turn is outside all fences; three injected payloads (memory, summary, cross-session) are absent from the assembled prompt while legitimate content (`Meera`, `exam pressure`, `work stress`) is retained; stored text cannot forge a boundary.
- **Additional issues found and fixed during verification:** (1) Line-granularity filtering discarded a legitimate sentence that shared a line with poison, so filtering moved to sentence granularity. (2) Scanning the full ~41k-character knowledge context on every request caused a measurable performance regression, so document scrubbing moved to ingestion (once per document change). (3) `SpamAndLoadTests` measured throughput against the shared repository archive and therefore depended on state accumulated by earlier tests; it now uses its own temporary archive. That order-dependence is the ISSUE-029 hermeticity defect.
- **Remaining limitations:** Filtering is pattern-based, so paraphrased or multilingual instruction text can still pass; the fence and tier labels then remain the only barrier and depend on model compliance. Least-context assembly is only partially addressed — blocks are bounded and instruction-scrubbed, but cross-session background is still included whenever available rather than being gated on demonstrated need. Ingestion scrubbing applies at refresh time, so documents cached before this change are only cleaned on their next reprocess.

### ISSUE-017 — MECHANISM COMPLETE (retention windows awaiting sign-off)

- **Problem:** Conversations, rolling summaries, inferred safety state, derived memory and feedback were persisted with no age-based expiry, retention schedule or minimization, so highly sensitive records could persist indefinitely.
- **Where it occurred:** `ChatArchive` / `ChatArchiveMongo` (messages, requests, sessions, safety state), `LongTermMemorySQLite` / `LongTermMemoryMongo`, `FeedbackStore` / `FeedbackStoreMongo`; no expiry path or TTL anywhere.
- **Why it occurred:** Deletion existed only as an explicit user action (session/account), so an abandoned account retained everything forever.
- **Root cause:** No retention policy model, no expiry mechanism, and no separation of retention windows by data class.
- **Fix:** Added `app/storage/retention.py` with a `RetentionPolicy` (per-class windows, `0` = never expire) and `run_retention`, which purges each store independently so one failing backend cannot stop the others and logs counts without record contents. Implemented `purge_expired` on all six stores (SQLite and Mongo) using existing timestamps, so no schema migration is required. Derived classes expire independently: summaries and safety state are cleared in place while the transcript is retained. Added `ChatArchive.claim_retention_run` / `ChatArchiveMongo.claim_retention_run`, a transactional compare-and-set so exactly one worker sweeps per interval. `main.py` triggers an opportunistic sweep behind a cheap in-process timer (never blocking a request) and exposes `python main.py --retention` for operators. Minimization: `ChatbotService._minimize_state` stops persisting free-text classifier observations about the user, keeping only short internal category markers.
- **Files changed:** `app/storage/retention.py` (new), `app/config/settings.py`, `app/storage/chat_archive.py`, `app/storage/chat_archive_mongo.py`, `app/memory/long_term_memory_sqlite.py`, `app/memory/long_term_memory_mongo.py`, `app/storage/feedback_store.py`, `app/storage/feedback_store_mongo.py`, `app/chatbot/chatbot_service.py`, `main.py`, `.env.example`, `render.yaml`, `DEVELOPER_GUIDE.md`, `tests/test_final_audit_remediation.py`, `issue.md`, `solution.md`.
- **Tests:** Targeted run `-k Retention` → 8 passed; full suite → 349 passed and 54 subtests passed; `python main.py --retention` returns `{}` with retention disabled, confirming the default is inert.
- **Verification:** Backdated records prove each window fires independently — a 400-day conversation is removed while a 10-day one is kept; a 60-day session loses its inferred safety state but keeps the user's words; expired memory is deleted while in-window feedback survives; a disabled policy removes nothing; the claim allows one sweep per interval and re-allows after it elapses; a deliberately broken memory store does not prevent archive expiry; free-text inference is dropped from persisted state while markers and scores remain; and the `main.py` sweep wiring actually deletes (tested against a temporary archive).
- **RETENTION WINDOWS: APPROVED as proposed.** The values below are signed off. `RETENTION_ENABLED` remains `false` by explicit instruction and must only be flipped by the owner; enabling it starts irreversible deletion.
  - `RETAIN_CONVERSATION_DAYS=365` — the user's own words are the record of record and support long-gap continuity, which the product depends on; a year covers seasonal/anniversary patterns without becoming an indefinite archive.
  - `RETAIN_SUMMARY_DAYS=90` — machine-derived and reconstructible from turns, and per ISSUE-009 it can be wrong; a shorter window limits how long a stale or mistaken recap can bias responses.
  - `RETAIN_SAFETY_STATE_DAYS=30` — the most sensitive class (inferred health-adjacent state). It exists for near-term continuity, so it should be the shortest; long-lived inferred risk labels carry the highest breach and mislabelling harm.
  - `RETAIN_MEMORY_DAYS=180` — inferred facts drive personalisation and are reinforced on use (the window measures time since last reinforcement), so unused inferences decay while active ones persist.
  - `RETAIN_FEEDBACK_DAYS=730` — largely operational product reports with lower sensitivity, useful across release cycles; still bounded rather than permanent.
- **Remaining limitations:** Sweeps are opportunistic (request-triggered or manual), so a completely idle deployment does not expire until traffic or a cron invocation occurs — no scheduler is included. Deletion is unverified erasure at the storage layer: backups, replicas and filesystem free space are out of scope (ISSUE-020/ISSUE-021). No deletion-evidence ledger or user-facing retention disclosure exists. Mongo purging uses explicit deletes rather than TTL indexes for parity with SQLite. Minimization covers free-text evidence only; scores, flags and hazard labels are still persisted because they drive safety continuity.

### ISSUE-018 — COMPLETE (repository implementation)

- **Problem:** Deleting a session removed only memory attributed exclusively to it. Records with no provenance (legacy/unattributed) were silently retained and kept influencing prompts, while the user was told the session was deleted.
- **Where it occurred:** `LongTermMemorySQLite.forget_session`, `LongTermMemoryMongo.forget_session`, `LongTermMemory.forget_session` (all returned `None` and kept unattributed records); `main.py::delete_session` reported only `{"status": "deleted"}`.
- **Why it occurred:** Absent provenance was treated as "cannot prove it belongs to this session, so keep using it", which resolves ambiguity in favour of retention — the opposite of what a deletion request implies.
- **Root cause:** No quarantine state, so the only options were keep-in-use or guess; and no reporting, so the outcome was invisible.
- **Fix:** Added `quarantined_at` to `UserMemory` as the single shared definition. On session deletion, unattributed records are quarantined (timestamped once, idempotent) instead of retained: they are excluded at every retrieval boundary (`retrieve` and `contradiction_topics`) in all three stores, so they can no longer reach a prompt. `forget_session` now returns `{"removed", "quarantined", "retained"}` and `DELETE /sessions/<id>` returns it as `derived_memory`, making the outcome explicit and verifiable. Schema migration adds the column via `ALTER TABLE` for existing databases; Mongo stores the same field.
- **Files changed:** `app/types.py`, `app/memory/long_term_memory.py`, `app/memory/long_term_memory_sqlite.py`, `app/memory/long_term_memory_mongo.py`, `main.py`, `tests/test_final_audit_remediation.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction showed an unattributed health-adjacent record surviving `forget_session` and still retrievable. Targeted run `-k "Quarantine or Retention or exclusive"` → 15 passed; full suite → 355 passed and 54 subtests passed.
- **Verification:** Deletion reports `{"removed": 1, "quarantined": 1, "retained": 0}`; the quarantined record is absent from both `retrieve` and `contradiction_topics`; quarantine is idempotent across repeated deletions (timestamp preserved); reinforced memory from another session is still correctly retained; account deletion still removes quarantined rows; and the JSON store reports the identical contract.
- **BOUNDARY AGREEMENT WITH ISSUE-017 (explicitly reconciled, not divergent):** both features now use one definition of "unattributed" — `UserMemory.sources == []`. That single flag drives all three behaviours:
  - **ISSUE-018 quarantine:** `sources == []` at session-deletion time ⇒ `quarantined_at` set ⇒ excluded from retrieval immediately.
  - **ISSUE-017 retention:** `purge_expired` deletes a record when `updated_at < cutoff` **or** `quarantined_at > 0 and quarantined_at < cutoff`, both using the **same approved 180-day memory window**. No second window and no new number was introduced, so nothing further needs sign-off.
  - **ISSUE-017 minimization:** unchanged by this fix. Minimization operates on persisted *safety state* (`evidence` free text), not on memory records, so the two passes do not overlap. Quarantined memory text is still stored until its window elapses — it is made unusable, not immediately erased.
  - Consequence worth noting: a quarantined record's retention clock runs from `quarantined_at`, so quarantining does not extend a record's life beyond the memory window, and `updated_at`-based expiry still applies independently.
- **Remaining limitations:** Provenance cannot be reconstructed for legacy records, so quarantine is the conservative endpoint rather than attribution — there is no operator review queue UI to adjudicate quarantined records, and with retention disabled they persist (unused) indefinitely. Quarantine is per-user-per-deletion; a user who never deletes a session keeps unattributed memory active. Deletion evidence is returned in the API response but not written to an auditable ledger.

### ISSUE-019 — COMPLETE (repository implementation)

- **Problem:** Account deletion tombstoned the principal and then deleted across archive, memory, feedback and cache stores with one `try/except`. A failure mid-saga returned a generic 503 with no record of which stores were already cleared, so neither the user nor an operator could tell what remained or what a retry would repeat.
- **Where it occurred:** `main.py::delete_account` (four sequential calls, single handler); no durable job state anywhere.
- **Why it occurred:** Cross-store deletion was written as a linear sequence rather than a resumable workflow, and backend-local transactions cannot span independent stores.
- **Root cause:** No durable per-step checkpointing, so progress was unobservable and retries were not convergent.
- **Fix:** Added a `deletion_jobs` table (SQLite) and collection (Mongo) with `start_deletion_job`, `record_deletion_step`, `finish_deletion_job` and `deletion_job`. `delete_account` now creates/loads the job, skips steps already marked completed, runs each store's deletion independently, records completion or failure per step, and returns a receipt. Partial failure returns 503 naming the pending steps while the identity stays revoked, so the idempotent endpoint converges on retry. A lost checkpoint only costs a repeated idempotent step. The archive purge does not remove the job row, so the audit trail outlives the data it describes.
- **Files changed:** `app/storage/chat_archive.py`, `app/storage/chat_archive_mongo.py`, `main.py`, `tests/test_final_audit_remediation.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction showed a feedback-store failure yielding `{"error": "account deletion failed"}` with no record of the completed archive/memory steps. Targeted run `-k AccountDeletionSaga` → 4 passed; full suite → 360 passed and 54 subtests passed.
- **Verification:** With the feedback store broken, the first call returns 503 with `pending: ["feedback"]` and a receipt showing `archive/memory/caches: completed`; after the store recovers, the second call returns 200 with every step `completed` and a non-zero `completed_at`. Step state survives `delete_user` for the same user, and resume skips completed work rather than repeating it.
- **BOUNDARY WITH ISSUE-018 — LEFT UNTOUCHED (no third definition introduced):** account deletion uses `profile.forget_user(user_id)`, which removes **all** of a user's memory records unconditionally, including quarantined ones. It never inspects `sources` or `quarantined_at`, so the ISSUE-018 unattributed boundary is not consulted, reinterpreted, or duplicated here. That is deliberate: session deletion must reason about attribution because only part of a user's data is in scope, whereas account deletion has no ambiguity to resolve. This is already covered by the existing ISSUE-018 test asserting account deletion removes quarantined rows, so the two features remain consistent by construction rather than by parallel logic.
- **Remaining limitations:** Convergence still depends on a retry occurring — there is no background reconciler that finishes an abandoned job, so a user who never retries can leave a job permanently incomplete (visible in `deletion_jobs`, which is the point). Deletion is unverified erasure at the storage layer only: backups, replicas and filesystem free space remain out of scope (ISSUE-020/ISSUE-021). The receipt is returned to the caller and stored per user but is not exported to an external audit log, and there is no operator endpoint listing incomplete jobs.

### ISSUE-020 — REPOSITORY-SIDE COMPLETE; ENCRYPTION IS AN EXTERNAL GATE

- **Problem:** Conversation text, summaries, memories, inferred safety state and feedback were stored as ordinary readable fields with no application-level protection, no classification of what is sensitive, and no repository evidence that platform encryption exists.
- **Where it occurred:** `ChatArchive` / `ChatArchiveMongo` schemas, `LongTermMemory*`, `FeedbackStore*`, the `data/` directory, and `render.yaml` (no encryption or key policy declared).
- **Why it occurred:** At-rest protection was assumed to be a platform property, so nothing in the repository classified sensitive fields, hardened local files, or required evidence that the assumption held.
- **Root cause:** No data classification, no locally-enforceable at-rest controls, and no explicit representation of an unverifiable external dependency.

**Repository-side (closed).**
- **Fix:** Added `app/storage/at_rest.py`: (1) `SENSITIVE_FIELDS`, an explicit sensitive/identifier/operational classification for all eight stored tables; (2) `harden_file_permissions`, applied by `ChatArchive`, `LongTermMemorySQLite` and `FeedbackStore` to each database file and its `-wal`/`-shm` sidecars at creation; (3) `storage_posture`, which reports locally-verified facts (classified tables, owner-only file count, whether hardening is even supported on this OS) separately from operator claims (encryption required/attested) and states `application_level_field_encryption: false` outright. Added `REQUIRE_ENCRYPTED_STORAGE` and `STORAGE_ENCRYPTION_ATTESTED`; `Settings.validate_storage_protection` runs at import so production cannot start while claiming to require encryption without recording who verified it. Posture is surfaced on the authenticated `/metrics` endpoint.
- **Deliberately NOT built:** application-level field encryption. `chat_messages.content` is projected in SQL via `substr()` for session titles and previews, and memory `text` is tokenised for lexical retrieval, so encrypting those fields would break existing features while leaving the key in the same process as the ciphertext. Rather than add an unwired crypto module, none was added — there is no inert encryption scaffolding in the codebase.
- **Files changed:** `app/storage/at_rest.py` (new), `app/config/settings.py`, `app/storage/chat_archive.py`, `app/storage/feedback_store.py`, `app/memory/long_term_memory_sqlite.py`, `main.py`, `.env.example`, `render.yaml`, `DEVELOPER_GUIDE.md`, `tests/test_final_audit_remediation.py`, `issue.md`, `solution.md`.
- **Tests:** Targeted run `-k AtRest` → 3 passed, 1 skipped, 7 subtests passed; subprocess check proves an unattested `REQUIRE_ENCRYPTED_STORAGE=true` configuration fails to import and an attested one starts; full suite → 363 passed, 1 skipped, 61 subtests passed.
- **Verification:** The classification test enumerates every table and column in both live SQLite databases and fails if any is unclassified, so a future sensitive column cannot be added silently. Posture reporting distinguishes facts from claims. Startup is fail-closed on the attestation.

**External gate (not closed, needs:**
- volume, database and backup encryption actually enabled and independently verified (Render disk and MongoDB Atlas), with evidence retained;
- key custody, rotation and recovery procedures, including who holds keys and how restore is tested;
- a product/security decision on whether field-level encryption for `content` and memory `text` is warranted, which would require schema changes and removal of the SQL `substr()` projections;
- operator/storage access review and least-privilege confirmation.
**)

- **Explicit inertness statement:** every control added by this issue is wired and exercised by tests, with one platform limitation: `harden_file_permissions` is a no-op on Windows (it returns `False` rather than pretending) and the owner-only file-mode test **skips on this Windows development host**, so POSIX file modes are implemented but unverified here. `storage_posture` reports `permission_hardening_supported: false` on such hosts so the gap is visible at runtime.
- **Remaining limitations:** Mongo deployments get no file-permission hardening because storage is remote; protection there depends entirely on the external gate. The attestation is a recorded claim, not a verification. No encryption-at-rest coverage exists for backups, replicas, or filesystem free space after deletion (shared with ISSUE-017/ISSUE-019/ISSUE-021).

### ISSUE-023 — COMPLETE (repository implementation; new value awaiting sign-off)

- **Problem:** A request without a valid identity was issued a fresh pseudonymous user ID *before* rate limiting, and the limiter keyed on that new principal. A client discarding its cookie obtained an unlimited number of fresh quotas.
- **Where it occurred:** `main._guard_request` (identity issued, then `_limiter.check(_client_identity())`); `_client_identity` returned `user:<new id>`; `IdentityManager.from_request` mints a principal when none is presented.
- **Why it occurred:** The limiter key was derived from an attacker-controllable value that the request itself created.
- **Root cause:** No pre-identity limit existed, so abuse containment depended on the caller choosing to retain an identity.
- **Fix:** Added a separate `_anon_limiter` keyed on a coarse network signal (`X-Forwarded-For` first hop, else `remote_addr`). When `principal.is_new` — i.e. the caller presented no usable identity — the request is charged to that network bucket before any work proceeds. Callers that retain their identity are unaffected and keep their per-identity limit. The network key is used only for limiting and is never stored.
- **Files changed:** `app/config/settings.py`, `main.py`, `tests/test_spec_compliance.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction showed 8/8 requests allowed against a 3/min limit. Targeted run → 14 passed; full suite → 365 passed, 1 skipped, 61 subtests passed.
- **Verification:** With a per-identity limit of 3 and a network cap of 6, ten churning clients get 6 allowed and 4 blocked. A single retained identity still hits its own limit of 2 and is not charged against the network bucket.
- **NEW VALUE AWAITING SIGN-OFF:** `ANON_RATE_LIMIT_MULTIPLIER = 5`. Rather than introduce a new absolute number, the network cap is derived as `RATE_LIMIT_PER_MINUTE × 5`, and it activates only when rate limiting is already enabled. Reasoning: shared NAT/corporate egress can legitimately carry several distinct users, so a 5× multiple blocks cookie-churn amplification while leaving headroom for genuine shared addresses. Set lower to harden, higher if legitimate shared-IP users are being blocked.
- **Remaining limitations:** The limiter remains per worker process, so the effective cap is multiplied by worker count (ISSUE-034). A distributed attacker with many source addresses is not contained by this control; it stops cheap single-host churn only. `X-Forwarded-For` is trusted as provided, so a spoofing-capable upstream can evade it — that depends on the edge proxy configuration (ISSUE-039).

### ISSUE-025 — COMPLETE (repository implementation; new values awaiting sign-off)

- **Problem:** Identity token payloads contained only version/user/session. Verification checked signature and ID shape but never time or revocation, so a copied token stayed valid indefinitely — the ten-year cookie age was only client transport metadata.
- **Where it occurred:** `IdentityManager._build` (payload without `iat`/`exp`), `IdentityManager.verify` (no time or revocation check), `MAX_AGE_SECONDS = 10 years`.
- **Why it occurred:** Identity was designed for permanence (never lose your history) with no counterbalancing bound, so theft had no natural end.
- **Root cause:** No token lifetime, no revocation mechanism, and no re-issuance path.
- **Fix:** Token payload v2 adds `iat`, `exp` and an epoch `e`. `verify` rejects expired tokens (with a 5-minute clock-skew allowance) and any token whose epoch is below the configured `IDENTITY_EPOCH`, giving bulk revocation without rotating the signing secret or tracking individual tokens. Sliding renewal: a token past half its life is flagged `needs_refresh` and `_set_identity_cookie` re-issues it, so active users are never cut off while abandoned tokens still expire. Migration: v1 tokens are still honoured (nobody is logged out by the upgrade) but are flagged for immediate re-issue as v2. `MAX_AGE_SECONDS` now tracks the token lifetime instead of outliving it.
- **Files changed:** `app/identity.py`, `app/config/settings.py`, `main.py`, `tests/test_final_audit_remediation.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction showed a payload of only `['s','u','v']` and verification accepting an unbounded token. Targeted run `-k IdentityLifetime` → 6 passed; full suite → 371 passed, 1 skipped, 61 subtests passed.
- **Verification:** v2 payload carries `iat`/`exp`/`e` with the configured TTL; an expired token is rejected under an advanced clock; bumping the epoch revokes an otherwise-valid token; a legacy v1 token is accepted and flagged for upgrade, and re-issuing produces v2; a token past half-life is renewed with a later expiry; cookie age equals token lifetime.
- **NEW VALUES AWAITING SIGN-OFF:** `IDENTITY_TTL_DAYS = 180` and `IDENTITY_EPOCH = 1`. Reasoning for 180 days: identity is an anonymous user's only route back to their own history, so a short TTL causes silent data loss, but sliding renewal means the window only ever applies to *inactive* tokens — an active user is refreshed indefinitely. 180 days bounds a stolen token to roughly one inactive season. Lower it to shorten theft exposure at the cost of losing dormant users' history sooner. `IDENTITY_EPOCH` stays at 1 until you need a mass revocation; incrementing it immediately invalidates every outstanding token.
- **Remaining limitations:** Revocation is all-or-nothing (epoch-wide); there is no per-token or per-user revocation list beyond the existing account tombstone. Tokens remain bearer credentials, so a stolen token is usable until it expires. No reauthentication step exists, because there are no user credentials to reauthenticate against.

### ISSUE-028 — REPOSITORY-SIDE COMPLETE; PROVIDER CONTRACTS ARE AN EXTERNAL GATE

- **Problem:** Current messages, transcripts, summaries, memories and inferred health-adjacent state could be assembled and sent to an external model provider with no user notice, no minimization control, and no record of what crossed the boundary.
- **Where it occurred:** `ChatbotService._build_prompt`, `ConversationRiskReasoner._semantic_call`, `ResponseBuilder` output review, all via `LLMClient`.
- **Why it occurred:** The provider was treated as an implementation detail rather than a trust boundary, so nothing disclosed it, bounded it, or observed it.
- **Root cause:** No privacy control plane around the external boundary.

**Repository-side (closed).**
- **Fix:** (1) `REQUIRE_PROVIDER_DISCLOSURE` + `PROVIDER_DISCLOSURE_ATTESTED` with `Settings.validate_provider_disclosure` at import, so production cannot start while claiming disclosure is required without recording who confirmed the notice. (2) A user-facing notice in `ui/index.html` stating that messages are processed by an external AI provider and that Soulene is not a crisis service. (3) `SEND_CROSS_SESSION_CONTEXT`, an active minimization control that stops prior-session background crossing the boundary at all. (4) `app/llm/transmission.py`, a content-free ledger recording call purpose and character counts (never text), wired into `LLMClient.generate` and surfaced on the authenticated `/metrics` endpoint alongside disclosure and minimization state. `store=False` was already set on provider calls and remains.
- **Files changed:** `app/llm/transmission.py` (new), `app/llm/client.py`, `app/config/settings.py`, `app/chatbot/chatbot_service.py`, `main.py`, `ui/index.html`, `.env.example`, `render.yaml`, `tests/test_final_audit_remediation.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction confirmed no consent, minimization or transmission controls existed. Targeted run `-k ProviderPrivacy` → 5 passed, 2 subtests; full suite → 376 passed, 1 skipped, 63 subtests passed.
- **Verification:** Disclosure validation fails closed and passes when attested; the ledger aggregates per purpose and its serialised snapshot contains no message content; purpose classification is asserted for all five call types; the minimization toggle is tested in **both** states and provably removes the prior-session marker from the assembled prompt; the UI notice text is asserted present.

**External gate (not closed, needs:**
- provider data-processing terms confirmed in writing: retention period, whether inputs train models, and sub-processor list;
- zero/limited-retention or enterprise privacy configuration enabled on the account, and evidence retained;
- data-residency/regional processing decision and legal review for the served jurisdictions;
- legal review of the user-facing notice wording and whether explicit opt-in consent is required rather than notice;
- a decision on whether `SEND_CROSS_SESSION_CONTEXT` should default to `false` in production, trading continuity for less data leaving the boundary.
**)

- **Explicit inertness statement:** every control here is active. The ledger records on real calls, the minimization toggle changes prompt assembly (tested both ways), the disclosure gate runs at import, and the UI notice renders. Nothing was added that is unwired. Note the ledger is **process-local and in-memory** — it is deliberately not persisted (persisting a transmission log adds another sensitive store) and resets on restart, so it is an observability aid, not an audit record of record.
- **Remaining limitations:** `store=False` and this ledger describe what *Soulene* sends; they cannot constrain what the provider does after receipt. Per-field redaction before transmission is not implemented — minimization is at block granularity (cross-session on/off), not PII-level scrubbing.

### ISSUE-029 — COMPLETE (repository implementation)

- **Problem:** Tests constructed the application from root-derived settings, so running the suite wrote to the working repository's real database, cache and knowledge paths. Results also depended on state accumulated by earlier tests.
- **Where it occurred:** `tests/test_api.py`, `tests/test_hardening.py`, `tests/test_spec_compliance.py` and others via `Settings.from_env()`, whose paths derive from the import-time `app.config.settings.PROJECT_ROOT`.
- **Why it occurred:** `PROJECT_ROOT` is resolved at import and no fixture redirected it, so "the app under test" and "the developer's working copy" were the same tree.
- **Root cause:** No suite-wide path containment before application import.
- **Fix:** Added `tests/conftest.py`, which pytest loads before any test module. It creates a temporary sandbox, copies the read-only `knowledge/` and `cache/` inputs plus `.env` into it (copies, never references in place), creates an empty `data/`, and rebinds `app.config.settings.PROJECT_ROOT` to the sandbox before any application module is imported. An autouse fixture asserts on every test that `Settings.from_env().root` is still the sandbox, so a test that escapes containment fails rather than silently writing to the repository. The sandbox is removed at interpreter exit.
- **Files changed:** `tests/conftest.py` (new), `tests/test_hardening.py`, `tests/test_final_audit_remediation.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction showed a single `test_api.py` test growing the repository archive from 110,366,720 to 110,370,816 bytes. Targeted run `-k Hermeticity` → 3 passed; full suite → 379 passed, 1 skipped, 63 subtests passed, with the repository archive byte-for-byte unchanged before and after.
- **Verification:** Settings paths (`data`, `knowledge`, `cache`) all resolve inside the sandbox and provably not to the repository equivalents; the knowledge corpus is a populated copy so document-dependent tests still work; the autouse guard fails any escaping test.
- **Related test-quality change:** `SpamAndLoadTests.test_rapid_repeated_identical_requests` asserted 100 requests complete within 10 seconds while taking ~8.4s standalone on this host, so it failed intermittently under full-suite load. The wall-clock bound was widened to 25s and documented as a smoke bound for pathological slowness rather than a benchmark; the meaningful assertion (repeated identical questions must be absorbed by the response cache, LLM calls < 60) remains strict. This is a flaky-assertion fix, not a masked regression: per-call cost was measured directly at ~70ms, consistent with expectations after the ISSUE-015 safety scans.
- **Remaining limitations:** Containment relies on rebinding one module global; a test that imports `app.config.settings` and re-derives `PROJECT_ROOT` itself, or that hardcodes an absolute path, would bypass the guard (the autouse assertion catches the former, not the latter). Root-level scripts (`test_all.py`, `test_audit.py`, `context_audit.py`, `build_cache.py`) are outside pytest discovery and remain non-hermetic — that fragmentation is ISSUE-033.

### ISSUE-031 — COMPLETE (repository implementation; clinical review gate open)

- **Problem:** Safety tests were example-driven. No suite enumerated the required dimensions, so a regression in an untested phrasing, language, evolution pattern or component-failure mode could pass the suite unnoticed.
- **Where it occurred:** `tests/test_upgrades.py`, `tests/test_reasoning_safety.py`, `tests/test_spec_compliance.py`, `tests/test_legacy_parity.py` — good individual coverage, no matrix.
- **Why it occurred:** Tests were added per fix rather than derived from a scenario matrix, so coverage gaps were invisible by construction.
- **Root cause:** No enumerated scenario matrix tied to named dimensions.
- **Fix:** Added `tests/test_safety_matrix.py`, which enumerates four dimensions as named subtests so a missing cell fails by name: (1) **language form** — explicit, timing, spaced, leetspeak, full-width Unicode, zero-width split, Hindi Devanagari, Hinglish Roman, euphemistic, hidden-distress must all reach the crisis floor, while negated / never / not-going-to / attributed / historical / used-to must step down to `EMOTIONAL_DISTRESS` and not to `SAFE`; (2) **risk evolution** — explicit disclosure routes to crisis, carried risk survives a calm follow-up, ordinary distress stays below crisis; (3) **component failure** — classifier raising, classifier returning malformed output, output reviewer raising, generation raising, and an all-components-broken case that must still route crisis deterministically; (4) **output harm** — all six therapeutic classes blocked with no model reviewer, plus four supportive replies asserted unchanged as false-positive guards.
- **Files changed:** `tests/test_safety_matrix.py` (new), `issue.md`, `solution.md`.
- **Tests:** Reproduction enumerated the named dimensions and confirmed no matrix existed. Targeted run → 13 passed, 26 subtests passed; full suite → 392 passed, 1 skipped, 89 subtests passed.
- **Verification:** The matrix passes against current behaviour, including the case where the risk classifier, output reviewer and generator all fail simultaneously and the deterministic floor must still produce a crisis route and a non-empty reply. All cases are synthetic; no real user content is used.
- **Remaining limitations:** MANUAL/CLINICAL GATE — a matrix proves the cells that were enumerated, not that the enumeration is complete. A qualified mental-health reviewer should approve which scenarios belong in the matrix and whether the expected outcome per cell is clinically right. Multilingual coverage is limited to Hindi/Hinglish crisis detection; the negation/attribution step-down logic remains English-only (so non-English contextual disclosures stay conservatively escalated). Dependency and delusion coverage is single-turn output blocking; longitudinal dependency remains the ISSUE-011 counter. Live-model behaviour is not exercised — every case uses fakes.

### ISSUE-034 — COMPLETE (repository implementation; capacity unmeasured)

- **Problem:** The deployment ran two Gunicorn workers while service singletons, per-session turn locks, rate-limit buckets, context/response caches and knowledge-cache state were all process-local, so behaviour depended on which worker served a request.
- **Where it occurred:** `render.yaml` and `Procfile` (`--workers 2`); `main._service/_feedback/_limiter/_anon_limiter`; `ChatbotService._turn_lock`; `ContextCache`, `ResponseCache`, `KnowledgeCache`.
- **Why it occurred:** In-process synchronisation was written for a single process, then deployed multi-process.
- **Root cause:** Declared topology did not match the concurrency model the code implements.
- **Reproduction finding worth recording:** safety continuity **already** survived across workers — a second service instance sharing the database saw carried crisis risk from the first, because state is rehydrated from the authoritative archive on every turn (reinforced by the ISSUE-002 fix). What genuinely did not span workers were turn locks, response caches and limiter buckets.
- **Fix:** Took the second option in the remediation — enforce compatible semantics instead of introducing a shared coordination backend (which would mean a new infrastructure dependency for a workload that does not need it). `render.yaml` and `Procfile` now declare `--workers 1 --threads 8`: threads share process memory, so turn locks, caches and limiter buckets all behave as designed, and an I/O-bound workload (model calls release the GIL) gets equivalent concurrency. Added `tests/test_deployment.py`, which fails if the worker count is raised above 1 or if the two entry points disagree — the invariant is enforced in CI rather than left as a comment.
- **Files changed:** `render.yaml`, `Procfile`, `tests/test_deployment.py` (new), `issue.md`, `solution.md`.
- **Tests:** Targeted run → 4 passed; full suite → 396 passed, 1 skipped, 89 subtests passed.
- **Verification:** The manifest invariant is asserted and both entry points must agree. Eight concurrent threads posting to one session produce exactly 16 messages with gapless unique sequence numbers 1–16 and no errors, proving in-process serialisation is real. Six concurrent distinct sessions each store exactly their own two messages, proving owner isolation under concurrency.
- **Remaining limitations:** Single-worker capacity is **unmeasured** — no load testing was performed, so the thread count is a reasoned choice, not a benchmarked one (capacity measurement belongs to ISSUE-039). Horizontal scaling is now explicitly blocked: adding workers requires moving turn locks, limiter buckets and cache invalidation to a shared store (for example Redis) first, and the deployment test will fail until that is done, which is the intended behaviour. A single worker is also a single point of failure for availability, traded against correctness; platform restart handles process death but in-flight turns are lost (they are uncommitted, so no partial data results).

### ISSUE-035 — COMPLETE (repository implementation; one-time migration needed)

- **Problem:** The deployment mounted only `data/`, while active `knowledge/` and `cache/` were sibling directories on ephemeral container storage. Uploaded documents and the built cache were lost on every redeploy, and the disk comment falsely claimed they were persisted.
- **Where it occurred:** `render.yaml` `disk.mountPath` and its comment; `Settings.knowledge_dir` (root-relative); `build_chatbot` hardcoding `settings.root / "cache"`.
- **Why it occurred:** Paths were root-relative constants while only one subdirectory was mounted, and nothing checked the two against each other.
- **Root cause:** No declared relationship between writable paths and durable storage.
- **Fix:** Added `CACHE_DIR` alongside the existing `KNOWLEDGE_DIR` and a `cache_path` property; `build_chatbot` now uses `settings.cache_path`. Added `PERSISTENT_ROOT` and `Settings.validate_persistence`, which runs at import and fails startup if `knowledge`, `cache` or `data` resolve outside the declared mount. Render sets `PERSISTENT_ROOT=/opt/render/project/src/data`, `KNOWLEDGE_DIR=data/knowledge`, `CACHE_DIR=data/cache`, and the disk comment now states that the mount is the only durable storage.
- **Files changed:** `app/config/settings.py`, `app/chatbot/chatbot_service.py`, `main.py`, `render.yaml`, `tests/test_deployment.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction showed `knowledge`/`cache` outside the mount with the manifest claiming persistence. Targeted run → 8 passed; full suite → 400 passed, 1 skipped, 89 subtests passed.
- **Verification:** Paths outside a declared mount raise with a message naming the offending path; local development with no mount declared is permitted; the manifest's `mountPath`, `PERSISTENT_ROOT`, `KNOWLEDGE_DIR` and `CACHE_DIR` are asserted mutually consistent, so a future edit that moves them out fails the suite; the CAG engine provably uses the configured cache path.
- **Remaining limitations:** **A one-time operator migration is required** on any existing deployment: current `knowledge/` and `cache/` contents must be copied into `data/knowledge` and `data/cache`, otherwise the first boot after this change starts with an empty corpus (it will rebuild from whatever documents are present in the new location). Local development keeps the old sibling layout by default, so the two environments differ in path shape — the validation only binds when `PERSISTENT_ROOT` is declared. Disk sizing and exhaustion behaviour remain ISSUE-039.

### ISSUE-039 — REPOSITORY-SIDE COMPLETE; MONITORING/RECOVERY IS AN EXTERNAL GATE

- **Problem:** Configuration defined basic logging and timeouts but no alerting, SLOs, backup/restore procedure, model cost budget, disk thresholds, or incident ownership. Failures would be detected late and operators had no documented recovery path.
- **Where it occurred:** `render.yaml` (resource/log settings only), application logging, and the absence of any operations documentation.
- **Why it occurred:** Operational concerns were left to the platform without recording what the platform must provide.
- **Root cause:** No operational controls in the repository and no runbook.

**Repository-side (closed).**
- **Fix:** Added `app/observability.py` with three active controls: (1) `DailyCallBudget`, a hard per-UTC-day cap on provider calls wired into `LLMClient.generate` — when exhausted it raises `BudgetExhausted`, which the existing generation error path converts into a deterministic reply, so spend is bounded without failing the user; (2) `Counters`, content-free operational counters incremented at the real decision points (`safety_classifier_unavailable`, `safety_degraded_escalations`, `output_blocked_<category>`, `model_budget_refusals`); (3) `disk_posture`, free-space reporting with a configurable low-space flag. All three are exposed on the authenticated `/metrics` endpoint under `operational`. Added `OPERATIONS.md`, a runbook naming what to alarm on, four incident procedures, backup/restore steps including the `sqlite3 .backup` caveat and a restore drill, the deployment invariants, and an explicit known-gaps section.
- **Files changed:** `app/observability.py` (new), `OPERATIONS.md` (new), `app/llm/client.py`, `app/config/settings.py`, `app/safety/reasoner.py`, `app/chatbot/response_builder.py`, `main.py`, `render.yaml`, `tests/test_deployment.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction confirmed no alerting, SLO or backup declarations existed. Targeted run → 16 passed; full suite → 408 passed, 1 skipped, 89 subtests passed.
- **Verification:** The budget refuses calls once exhausted, treats 0 as unlimited, resets across a simulated UTC day rollover, and an exhausted budget still returns a usable reply rather than surfacing an error. Counters are integer-only and JSON-serialisable, and a real degraded-classifier turn provably increments `safety_classifier_unavailable`. Disk posture reports true free space and trips `low_space` at an impossible threshold. The runbook is asserted to contain its watch list, backup section, worker invariant and known-gaps section.

**External gate (not closed, needs:**
- alert routing — the counters exist but nothing pages anyone; wire `/metrics` to a monitoring system with thresholds;
- SLOs and error budgets agreed (latency, availability, crisis-path success), which cannot be chosen without production traffic;
- automated backup schedule plus a *verified* restore drill on real infrastructure;
- load testing to establish the single-worker capacity envelope (also ISSUE-034's unmeasured residual) and a decision on `MODEL_DAILY_CALL_BUDGET`;
- named incident ownership and an on-call rotation;
- platform-level WAF/TLS/proxy configuration review.
**)

- **Explicit inertness statement:** the budget, counters and disk reporting are all active and exercised by tests — the budget genuinely blocks calls, the counters genuinely increment during real pipeline runs. `OPERATIONS.md` is **documentation, not automation**: it describes procedures a human performs, and it says so in its own opening line. No unwired alerting client, metrics exporter or scheduler was added.
- **NEW VALUE AWAITING SIGN-OFF:** `MODEL_DAILY_CALL_BUDGET`, shipped as `0` (unlimited) so it changes nothing until you choose a cap. It cannot be defaulted responsibly without knowing expected daily volume — too low silently degrades every user's replies to deterministic fallbacks, which is a safety-relevant downgrade, so `0` is the conservative default. `DISK_WARN_BELOW_MB=256` is a reporting threshold only (it triggers no action) against a 1 GB volume.
- **Remaining limitations:** Counters and the budget are in-process and reset on restart, so they are operational signals rather than billing or audit records. The budget counts calls, not tokens or currency, so it bounds volume rather than exact spend.

### ISSUE-005 — COMPLETE (repository implementation)

- **Problem:** `run_cli` called the chatbot service directly with an environment-derived or random session identity, bypassing HTTP identity verification, API/admin authentication, rate limiting and account-revocation checks. The trust assumption ("this is a local dev tool") was implicit and unenforced.
- **Where it occurred:** `main.py::run_cli`.
- **Why it occurred:** The CLI was written as a developer convenience against the service layer, below every request guard.
- **Root cause:** No enforced trust boundary distinguishing a local tool from a production surface.
- **Fix:** `run_cli` now refuses to start when the deployment indicates a shared/production surface — `STORAGE_BACKEND=mongo` (shared storage) or `REQUIRE_API_AUTH=true` (authenticated deployment) — printing each disqualifying reason and exiting with status 2. A deliberate local session can override with `SOULENE_ALLOW_UNSAFE_CLI=1`, which makes the bypass an explicit, auditable choice rather than a silent default.
- **Files changed:** `main.py`, `tests/test_deployment.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction confirmed the CLI performed no auth, rate-limit or revocation checks. Targeted run `-k Cli` → 3 passed (real subprocess invocations); full suite → 411 passed, 1 skipped, 89 subtests passed.
- **Verification:** With Mongo configured the CLI exits 2 and names shared production storage; with `REQUIRE_API_AUTH=true` it exits 2 and names authenticated access; with the override set it proceeds past the guard.
- **Remaining limitations:** This is a refusal guard, not authentication — the CLI still has no identity, rate limiting or revocation when it does run, so an overridden local session retains full access to whatever storage it is pointed at. The two signals used (Mongo backend, required auth) are proxies for "production"; a SQLite deployment exposed to untrusted users would not be caught.

### ISSUE-016 — COMPLETE (repository implementation; claim-level citation is a product gate)

- **Problem:** Cached sections carried source metadata internally, but nothing reached the user. `ChatResult.retrieved` was hardcoded to an empty list and the `/chat` response contained no attribution, so a knowledge-grounded answer and a synthesised one were indistinguishable.
- **Where it occurred:** `ChatbotService.handle` (`retrieved=[]`), `/chat` response payload; `CachedSection.rendered` labelled documents for the model only.
- **Why it occurred:** Provenance existed for prompt construction and was discarded at the response boundary.
- **Root cause:** No propagation of source identity out of the pipeline.
- **Fix:** Added `KnowledgeCache.source_provenance`, returning document id, display name, content version and update timestamp for each retrieved source. `handle` now populates `ChatResult.retrieved` from the lookup's sources, and `/chat` returns `grounded` plus `sources`. `ChatResult.retrieved` was retyped from `List[RetrievedChunk]` to `List[Dict[str, object]]` to carry provenance rather than chunk text (chunk text was never populated). An ungrounded reply reports `grounded: false` with an empty source list.
- **Files changed:** `app/cag/knowledge_cache.py`, `app/chatbot/chatbot_service.py`, `app/types.py`, `main.py`, `tests/test_cag.py`, `tests/test_api.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction showed `retrieved=[]` and no source mention while the engine knew two source documents. Targeted runs → 3 + 2 passed; full suite → 416 passed, 1 skipped, 89 subtests passed.
- **Verification:** Provenance carries id, display name, non-empty version and a positive timestamp; editing a document changes its version, so staleness is detectable; an unknown document still yields a stable shape with an empty version; the API exposes sources for a grounded reply and reports `grounded: false` with no sources otherwise.
- **Remaining limitations:** PRODUCT GATE — attribution is **per reply, not per claim**. The model is not required to cite which sentence came from which document, so a reply mixing grounded and synthesised content is attributed wholesale. Enforcing claim-level citation would need either a constrained output format or a post-hoc verification pass, both of which change response style and need a product decision. The UI does not yet display the returned sources; they are available on the API only.

### ISSUE-021 — Repository-side (closed) / External gate (not closed)

**Repository-side (closed).**

- **Problem:** Schemas and indexes were created inline at runtime with no recorded version, no migration contract, no backup/restore procedure and no orphan reconciliation, so a schema change or partial failure had no safe recovery path.
- **Where it occurred:** `ChatArchive._initialize` / `ChatArchiveMongo._ensure_indexes` (inline creation), feedback stores, `render.yaml` (no backup policy).
- **Why it occurred:** Idempotent create-if-missing was sufficient while the schema only ever grew, so nothing tracked revisions or detected inconsistency.
- **Root cause:** No schema version of record and no integrity reconciliation.
- **Fix:** Added `ChatArchive.SCHEMA_VERSION`, a `schema_version` table written on first access, and `assert_schema_supported`, which refuses to run against a database written by a newer release — the failure mode a rollback would otherwise hit silently. Added `find_orphans` and `reconcile_orphans`: orphaned messages/requests are detected, and reconciliation **restores the missing session parent** from the messages themselves rather than deleting rows, because the transcript is the authoritative record and deleting it would destroy user content. Stale requests whose turn no longer exists are removed, since they cannot be replayed. Both run at service startup, logging a warning only when something was actually repaired.
- **Files changed:** `app/storage/chat_archive.py`, `main.py`, `tests/test_final_audit_remediation.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction showed no `schema_version` table, 2 orphaned messages after a session row was lost, and no reconciliation API. Targeted run `-k SchemaAndIntegrity` → 5 passed; full suite → 421 passed, 1 skipped, 89 subtests passed.
- **Verification:** The version is recorded once and stable across calls; a database marked five versions ahead is refused with a message naming the mismatch; orphans are counted correctly; reconciliation restores the session and leaves both user messages intact; a healthy database reconciles to a no-op.
- **External gate (not closed, needs:** an automated backup schedule with retention at least as long as the longest configured retention window; a *verified* restore drill on real infrastructure (procedure is documented in `OPERATIONS.md`, but performing and evidencing it is operational); a reversible migration harness — this fix records and guards the version but does **not** provide up/down migration scripts, because there is no second version to migrate to yet; and equivalent version/reconciliation support for the Mongo backend, which currently has neither.**)
- **Remaining limitations:** Version guarding is SQLite-only. The migration contract is "refuse to run on an unknown future version", not "transform between versions" — the first real schema change will need a migration path added alongside a version bump. Reconciliation covers message/request/session parentage only, not derived memory or feedback consistency.

### ISSUE-024 — COMPLETE (repository implementation)

- **Problem:** Expired timestamps were removed only from the bucket being checked, and the global sweep deleted only buckets that were *already* empty. A key seen once and never revisited was never emptied, so it was retained forever.
- **Where it occurred:** `RateLimiter.check` — the `if len(self._hits) > 10000` block removed keys where `not v`.
- **Why it occurred:** Cleanup assumed buckets become empty on their own, but emptying only happens when that specific key is checked again.
- **Root cause:** Eviction depended on the very event (a revisit) that a one-shot identity never produces.
- **Fix:** Added `RateLimiter._evict`, which drops every key whose most recent hit has aged out of the window — not just already-empty ones — and enforces a `_MAX_KEYS` ceiling that removes least-recently-active keys so a churn attack cannot grow the table unboundedly even if buckets look live. Both thresholds are named constants rather than inline magic numbers.
- **Files changed:** `app/security.py`, `tests/test_spec_compliance.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction retained 12,001 buckets of which 12,000 were stale. Targeted run `-k issue_024` → 3 passed; full suite → 424 passed, 1 skipped, 89 subtests passed.
- **Verification:** After ageing all hits beyond the window, the table collapses to at most 2 keys; a key still inside its window keeps its count and is still correctly blocked at its limit (eviction does not hand out free quota); the key ceiling is enforced. The ceiling test lowers the thresholds on the instance rather than generating 50,000 real keys, which kept the suite fast after an initial version took 154 seconds.
- **Remaining limitations:** The limiter is still in-process, so memory is bounded per worker rather than globally; with the single-worker topology from ISSUE-034 that is now the whole picture. Eviction runs opportunistically on check, so a process that stops receiving traffic keeps its last table until the next request.

### ISSUE-027 — COMPLETE (repository implementation)

- **Problem:** No Content-Security-Policy, HSTS, frame, content-type or referrer headers were set, so the browser UI had no defence-in-depth against framing, content injection or referrer leakage.
- **Where it occurred:** `main.py` had only the identity-cookie `after_request` hook; `render.yaml` declared no header policy.
- **Why it occurred:** Headers were assumed to be an edge/proxy concern and were never set by the application.
- **Root cause:** No response-header baseline.
- **Fix:** Added a `_set_security_headers` hook setting a nonce-based CSP (`default-src 'self'`, per-request `script-src`/`style-src` nonces, `object-src 'none'`, `base-uri 'none'`, `form-action 'self'`, `frame-ancestors 'none'`), plus `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and a `Permissions-Policy` denying geolocation/microphone/camera. HSTS is sent only when the request is secure or secure cookies are configured, since sending it over plain HTTP is harmful. A fresh nonce is generated per request in `_guard_request`, passed to the template, and carried by both inline blocks. The UI's single inline `onclick` handler was converted to an `addEventListener` binding so the policy needs **no** `unsafe-inline`. Headers use `setdefault`, so an edge proxy can still override.
- **Files changed:** `main.py`, `ui/index.html`, `tests/test_deployment.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction showed all six headers absent from `/`. Targeted run `-k SecurityHeader` → 5 passed, 2 subtests; full suite → 429 passed, 1 skipped, 91 subtests passed.
- **Verification:** Headers are present on both a template route and an API route; the CSP contains neither `unsafe-inline` nor `unsafe-eval` and does include the hardening directives; the nonce in the policy matches the nonce on exactly the two inline blocks (so the UI actually works); the nonce differs between two requests; and no inline event handler remains in the template.
- **Remaining limitations:** The CSP protects the served page but cannot protect against a compromised edge that strips headers — verifying the deployed response is part of the ISSUE-039 external gate. HSTS depends on correct TLS termination detection (`request.is_secure` behind a proxy requires the platform to set forwarding headers). No CSP violation reporting endpoint is configured, so policy breakage would surface as a broken page rather than a report.

### ISSUE-030 — COMPLETE (repository implementation)

- **Problem:** `ResilienceTests.test_archive_failure_degrades_gracefully` patched `archive.record`, the legacy single-message helper, while the runtime commits through `archive.record_turn`. The injected failure was never reached, so the test passed while proving nothing about archive-failure behaviour — false confidence in a safety-critical partial-failure path.
- **Where it occurred:** `tests/test_security.py::ResilienceTests`; the real boundary is `ChatbotService._record_turn`.
- **Why it occurred:** The test predated the move to atomic turn commits and was never re-pointed at the new interface.
- **Root cause:** The test asserted on a method the production path no longer calls.
- **Fix:** Replaced it with two tests that patch `record_turn` and **assert the patched boundary was actually invoked**, so the test cannot silently stop exercising the failure again. They verify that a failed authoritative commit raises rather than returning a fabricated reply, that no message is persisted, that no derived safety state or cached context survives the failure (reusing the ISSUE-002 rollback invariant), and that a retry after recovery succeeds and stores exactly one turn.
- **Files changed:** `tests/test_security.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction confirmed the test patched `archive.record` while the runtime used `record_turn`. Targeted run → 5 passed; full suite → 430 passed, 1 skipped, 91 subtests passed.
- **Verification:** The new tests fail if `record_turn` stops being the commit boundary (the invocation assertion catches it), and they pin the no-partial-state guarantee.
- **Corrected claim worth recording:** the old test's name asserted *graceful degradation*, but the intended and actual behaviour is the opposite — a failed authoritative commit must surface so the HTTP layer returns 503 and the user is told their message was not saved. Silently degrading would mean claiming a message was stored when it was not.
- **Remaining limitations:** Failure injection is at the Python boundary, not the database layer, so it does not exercise real SQLite/Mongo faults (disk full, lock timeout, network partition). Those remain covered only by the opt-in Mongo integration suite (ISSUE-032).

### ISSUE-032 — REPOSITORY-SIDE COMPLETE; LIVE VALIDATION IS AN EXTERNAL GATE

- **Problem:** Mongo integration and live/staging smoke suites need credentials, networking, spawned processes and destructive database drops, so they cannot run in ordinary CI. The contracts they exercise (provider response shapes, backend interface parity) had no offline equivalent, so provider or backend regressions would only surface in a live environment.
- **Where it occurred:** `tests/test_mongo_integration.py`, `tests/smoke_live.py`, `tests/smoke_staging.py`.
- **Why it occurred:** The only tests for those boundaries were the live ones, so removing external dependencies meant losing the coverage entirely.
- **Root cause:** No contained substitute for externally-dependent contracts.

**Repository-side (closed).**
- **Fix:** Added `tests/test_provider_contract.py`, which pins the contracts offline using fakes that mimic the provider's surface shapes: normal text is stripped, a `None` output becomes `""` rather than `None`, provider exceptions surface as `LLMError`, the required request fields are sent with `store=False` (the ISSUE-028 retention control), budget exhaustion is distinguishable from a provider error, the moderation response shape is parsed into a `ModerationSignal`, and moderation failure fails open with the error recorded rather than raising. It also asserts **backend interface parity**: all 22 archive methods and all memory-store methods exist on both SQLite and Mongo implementations, so adding a method to one backend and not the other fails in CI instead of at runtime on the backend nobody tested.
- **Files changed:** `tests/test_provider_contract.py` (new), `issue.md`, `solution.md`.
- **Tests:** Reproduction confirmed all three suites need external resources and no offline contract test existed. Targeted run → 9 passed, 38 subtests; full suite → 439 passed, 1 skipped, 129 subtests passed.
- **Verification:** The parity subtests genuinely fail when a method is missing from either backend (that is how they are written — one subtest per method per backend). One of my own test expectations was wrong and was corrected rather than the code: `moderate` deliberately fails open, because moderation is one signal among several and the deterministic guardrail floor stays authoritative; asserting it should raise would have been asserting a safety regression.

**External gate (not closed, needs:**
- a disposable, network-isolated Mongo replica set in CI to run `test_mongo_integration.py`, including its destructive database drop, with an explicit allowlist so it can never target a real cluster;
- a staging environment plus credentials for `smoke_staging.py`, and a token budget for `smoke_live.py`;
- confirmation that the real provider's response shapes still match the fakes — a contract test proves Soulene handles a shape correctly, never that the provider still emits it, so this must be re-verified on provider API changes.
**)

- **Explicit inertness statement:** the contract tests are active and run in the default suite. The three live suites remain **excluded and unrun** — they are unchanged, still gated behind their own environment checks, and this fix does not make them runnable. Nothing was added that pretends to test a live dependency.
- **Remaining limitations:** Offline fakes cannot detect provider-side behaviour changes, real transaction semantics, replica-set failover, or network partitions. Interface parity checks method existence, not behavioural equivalence between the two backends.

### ISSUE-036 — COMPLETE (repository implementation)

- **Problem:** A shared `MongoClient` and the SQLite feedback connection were created lazily but never closed. No shutdown hook existed, so connections lingered until process exit, complicating graceful shutdown and rolling deploys.
- **Where it occurred:** `app/storage/mongo_client.py` (`reset_mongo` existed but was only used by tests), `FeedbackStore` (had `close` but nothing called it), `main.py` (no lifecycle hook).
- **Why it occurred:** Lazy module-level singletons had creation paths but no symmetric teardown.
- **Root cause:** No defined connection ownership or shutdown contract.
- **Fix:** Added `main.shutdown_resources`, which closes the feedback connection and resets the shared Mongo client, returns what it actually closed, is idempotent (a second call is a no-op rather than an error), and isolates failures so a broken close on one resource still lets the other run. Registered with `atexit`, which covers normal interpreter exit and Gunicorn worker termination on deploy/reload/scale-down.
- **Files changed:** `main.py`, `tests/test_deployment.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction confirmed no `atexit` registration, no teardown hook and `reset_mongo` unwired. Targeted run `-k Shutdown` → 4 passed; full suite → 443 passed, 1 skipped, 129 subtests passed.
- **Verification:** The feedback connection is closed exactly once even across repeated shutdown calls; Mongo reset succeeds even when no client was ever created (it no-ops safely); a resource whose `close` raises is reported as not-closed while the remaining cleanup still runs and the reference is still cleared.
- **Remaining limitations:** `atexit` does not run on `SIGKILL` or a hard container stop, so an ungraceful kill still leaves the OS to reclaim connections. Ownership remains module-global singletons rather than injected dependencies, so shutdown is a process-level concern rather than a per-component lifecycle. Graceful termination under real Gunicorn was not exercised — that would need a live server, which is part of the ISSUE-039 external gate.

### ISSUE-037 — REPOSITORY-SIDE COMPLETE; HASH-LOCKED ARTIFACTS ARE AN EXTERNAL GATE

- **Problem:** Direct dependencies were exactly version-pinned but had no artifact hashes and no transitive lock, and the build upgraded pip before installing. Identical source revisions could therefore install different transitive artifacts over time.
- **Where it occurred:** `requirements.txt` (9 pinned direct dependencies, no hashes); `render.yaml` `buildCommand` (`pip install --upgrade pip && pip install -r requirements.txt`).
- **Why it occurred:** Version pinning was treated as sufficient reproducibility; the resolver and the transitive set were left floating.
- **Root cause:** Reproducibility by version rather than by artifact, with an unpinned build toolchain.

**Repository-side (closed).**
- **Fix:** Added enforced dependency tests: every direct dependency must use `==` and no other comparator, none may point at a URL/VCS/local path (a supply-chain bypass), and the build command must not opportunistically upgrade pip. That last test **failed on the real manifest**, which is how the defect was fixed rather than merely described — `buildCommand` now pins `pip==25.0`. Documented the exact lock-generation procedure in `OPERATIONS.md`, and added a test that asserts any committed `requirements.lock` carries `--hash=sha256:` entries.
- **Files changed:** `render.yaml`, `OPERATIONS.md`, `tests/test_deployment.py`, `issue.md`, `solution.md`.
- **Tests:** Reproduction confirmed 9 pinned deps, zero hashes, no lock file. Targeted run → 3 passed, 1 skipped, 18 subtests; full suite → 446 passed, 2 skipped, 147 subtests passed.
- **Verification:** Pinning and URL-freedom are asserted per dependency as subtests; the build-command test demonstrably catches an unpinned toolchain.

**External gate (not closed, needs:**
- generate and review a hash-locked transitive lock (`pip-compile --generate-hashes`), commit it, and add `--require-hashes` to the build command — this requires package-index access and a human review of the resolved set, so it was **not** done here;
- an SBOM and a vulnerability-review process for the locked set;
- a trusted index/mirror policy, since the build currently resolves from the public index;
- artifact provenance verification for the two native-wheel dependencies (PyMuPDF, pandas).
**)

- **Explicit inertness statement:** no placeholder lock file was created. The lock-file test **skips** with an explicit message pointing at this gate, so the suite reports 2 skips (this one and the POSIX file-mode test from ISSUE-020) rather than silently passing an assertion about a file that does not exist. Fabricating hashes offline would have been worse than not having them.
- **Remaining limitations:** Pinned versions still allow a compromised or yanked artifact at the same version to be installed, which only hashes prevent. `pip==25.0` is itself a chosen pin that needs periodic review.

### ISSUE-026 — CONTAINED (accepted Critical limitation; history not rewritten)

- **Problem:** The runtime conversation database was tracked in Git, placing an application datastore inside version-control history and distributable clones.
- **Where it occurred:** `data/chat_archive.sqlite3` plus its `-wal` and `-shm` sidecars in the Git index; `.gitignore` ignored `data/` only prospectively.
- **Why it occurred:** The runtime data directory was committed before `data/` was ignored, and ignore rules never untrack already-tracked paths.
- **Root cause:** Runtime state was committed to source control, and no repository check prevented or detected tracked runtime data.
- **Fix (containment):** All three SQLite artifacts were removed from the Git index with `git rm --cached` while the local runtime database was preserved on disk. `data/` remains ignored, so the files cannot be re-added silently. A metadata-only regression test now fails if any of those paths become tracked again.
- **Files changed:** Git index entries for `data/chat_archive.sqlite3`, `data/chat_archive.sqlite3-wal`, `data/chat_archive.sqlite3-shm`; `tests/test_security.py`; `issue.md`; `solution.md`.
- **Tests:** `python -m pytest -q tests/test_security.py -k issue_026` → 1 passed (initially failed and revealed the two untracked-but-indexed sidecar files); `python -m pytest -q tests/test_security.py tests/test_data_lifecycle.py` → 55 passed; `py_compile` passed. No database content was opened or printed at any point.
- **Verification:** `git ls-files` returns nothing for all three paths, `git check-ignore` confirms the database is ignored, and the local file still exists for normal operation.
- **ACCEPTED REMAINING LIMITATION (Critical, permanent for this session):** One historical commit (reachable from tag `v1`) still contains these paths, so prior history, existing clones, forks, and backups may still hold conversation data. A history rewrite was explicitly **not** performed in this session by decision. Closing the exposure requires an authorized, owner-coordinated action outside this session: rewrite/purge across all refs and tags, force-update remotes, invalidate or re-clone every copy, verify backups, and complete any required exposure assessment and notification. Until then `ISSUE-026` must be treated as an unresolved Critical privacy exposure for release purposes, even though current and future commits are clean.

### ISSUE-038 — COMPLETE (repository implementation; two new values awaiting sign-off)

- **Problem:** The open, unauthenticated `/health` route called `get_service()`, so a platform probe on a cold worker could itself build the entire application — knowledge cache load, secret/storage validation and backend connection. Liveness and readiness were the same endpoint, so a degraded dependency looked identical to a dead process.
- **Where it occurred:** `main.py` — `health()` (`get_service().archive.healthcheck()`), `get_service()` lazy construction, `_warm_on_import()`.
- **Why it occurred:** One endpoint served two different questions ("is the process alive?" and "can it serve traffic?"), and construction was lazy with no explicit owner, so whichever caller arrived first paid for initialization — including a probe.
- **Root cause:** No separation between liveness and readiness, and no explicit initialization step, so initialization was a side effect of the first request on any path.
- **Reproduction (before the fix):** With `main._service = None` and a spy on `main.get_service`, `GET /health` returned **200 after invoking `get_service()` once** (full construction), and `GET /live` returned **404**.
- **Fix:**
  - **`GET /live` (new)** — liveness from process state alone: `{"status": "alive", "uptime_seconds": ...}`. It reads no settings that can fail, touches no backend, and never constructs the service, so it stays 200 while a dependency is degraded and therefore never drives a restart loop.
  - **`GET /health` is now readiness only** — `readiness_report()` *reads* `_service` and never constructs it. States: `initializing` (cold, inside `READINESS_STARTUP_GRACE_SECONDS`), `unavailable`/`startup_deadline_exceeded` (grace elapsed with nothing initialized), `unavailable`/`initialization_failed` (startup initialization raised — answered immediately rather than waiting out the grace), `unavailable`/`storage_failed` or `storage_timeout`, and `ok`. Non-ok is always 503, so readiness stays fail-closed.
  - **Bounded dependency probe** — `_bounded_probe()` runs `archive.healthcheck` on a daemon thread with a hard `READINESS_PROBE_TIMEOUT_SECONDS` deadline and reports `timeout`, so a wedged backend socket cannot hold the probe response open.
  - **Explicit initialization** — `initialize_service()` is the startup entry point (used by the gunicorn import warm-up); it returns success instead of raising, so a failed cold start leaves the process alive on `/live` while `/health` stays 503. `get_service()` now records attempts/failures in `_INIT_STATE` and only publishes `_service` after schema check and reconciliation succeed, so no caller can observe a half-initialized service. `python main.py` still calls `get_service()` directly and fails loudly.
  - **Redaction preserved** — dependency states are coarse (`ok`/`failed`/`timeout`/`pending`/`unknown`); exception types are logged, never returned, because the route is unauthenticated.
  - `_PROBE_PATHS = {"/health", "/live"}` drives both the `before_request` bypass and `_OPEN_PATHS`, so the two probes cannot drift apart on auth, identity minting or rate limiting.
- **New configuration (PROPOSED — needs sign-off):** `READINESS_STARTUP_GRACE_SECONDS=120` (must exceed real cold-start time: knowledge cache load plus Mongo connect; too low and the platform kills healthy-but-slow starts) and `READINESS_PROBE_TIMEOUT_SECONDS=5` (bounds the readiness response when storage wedges; too low and a briefly slow store reads as unavailable). Both defaults are deliberately generous so nothing is declared dead prematurely.
- **Files changed:** `main.py`; `app/config/settings.py`; `render.yaml`; `OPERATIONS.md`; `README.md`; `tests/test_health_probe.py` (new); `issue.md`; `solution.md`.
- **Tests:** `tests/test_health_probe.py` — 15 tests, all failing before the fix and passing after: liveness exists / never constructs / survives broken storage / open under auth; readiness never constructs, reports each of the four non-ok reasons, exposes coarse dependency states, hides exception detail and connection strings, and returns within the probe budget when storage hangs; `initialize_service()` reports failure without raising and records it. Full suite: `python -m pytest -q tests --ignore=tests/test_mongo_integration.py` → **461 passed, 2 skipped, 147 subtests** (was 446 + 15 new).
- **Verification:** The spy assertion is the direct inverse of the reproduction — `get_service` is invoked zero times by either probe, and `_service` is still `None` afterwards. The hang test asserts a wall-clock bound, so the deadline is proven to work rather than assumed.
- **Remaining limitations:** Readiness deliberately does **not** retry initialization, so a transient dependency failure during startup requires a restart to clear (the platform restarts on a failed health check, so this is the intended fail-closed path, but it does mean `initialization_failed` is sticky within a process). The bounded probe abandons a hung thread rather than cancelling it — Python cannot interrupt a blocking socket read — so repeated timeouts leak one daemon thread each until the backend recovers or the process restarts. Only storage is probed; model-provider reachability is deliberately not part of readiness because degraded model access has a designed fallback and must not remove the process from service. Render exposes a single `healthCheckPath`, so `/live` is only used by whatever external uptime monitor the operator points at it — that wiring is part of the ISSUE-039 external gate. The grace and timeout values are unmeasured proposals; real cold-start timing needs to be observed in a production-equivalent environment.

### ISSUE-040 — Repository-side (closed) / External gate (not closed)

**Repository-side (closed).**

- **Problem:** `render.yaml` set `autoDeploy: true` on `branch: main`, so any commit that landed on main was rebuilt and released to users with no mandatory test, safety, schema or dependency gate in between. `pytest.ini` existed but was linked to nothing.
- **Where it occurred:** `render.yaml` — `branch`/`autoDeploy`; `pytest.ini` — discovery configuration with no consumer.
- **Why it occurred:** Deployment was wired directly to a branch pointer rather than to a promotion decision about a tested commit, and no repository-side pipeline existed to be the gate.
- **Root cause:** Promotion had no gate and no explicit act — "merged" was the same event as "released".
- **Reproduction (before the fix):** `autoDeploy: true` in the manifest with no `.github/workflows/` present, i.e. nothing between a push to main and a production rebuild. Additionally, the suite could not have served as a gate: run from a clean checkout with no `.env` and the production safety configuration, it produced **5 failures** (`test_repeat_factual_question_costs_zero_llm_calls`, `test_simple_message_makes_no_knowledge_lookup`, `test_rapid_repeated_identical_requests`, `test_repeat_question_served_from_cache`, `test_issue_003_injection_never_reaches_the_model_with_context`). Its result depended on the untracked local `.env` (which sets `ENABLE_OUTPUT_SAFETY_CHECK=false`).
- **Fix:**
  - **Automatic promotion disabled** — `autoDeploy: false`, with the manifest stating the condition for re-enabling it and pointing at the checklist. `tests/test_deployment.py::PromotionGateTests` fails if it is flipped back.
  - **Repository-side gate added** — `.github/workflows/gate.yml` runs on every push and PR to `main` (the remote is GitHub, so this executes as committed; it is not inert). It installs pinned dependencies, asserts no `.env` leaked into the checkout, and runs the hermetic suite on the **production interpreter** (`3.12.7`, matched to `PYTHON_VERSION`) with the **production safety configuration**. Tests assert the workflow cannot pass while ignoring failures (`continue-on-error`, `|| true`) and that its Python version and safety flags equal the manifest's.
  - **Test-only dependencies separated and pinned** — `requirements-dev.txt` (`pytest==9.1.1`, exact-pinned per ISSUE-037) is used by CI and asserted absent from the production `buildCommand`.
  - **Suite made environment-independent (root cause of the unusable gate)** — `FakeLLMClient` now tags each `generate()` call with its purpose (`generate`/`review`/`summary`/`crisis`) and exposes `generations`. The five call-counting tests count reply-producing calls instead of every provider call, so their meaning ("a cache hit avoids generation", "an injection produces no generated reply") no longer depends on whether the output reviewer is enabled.
  - **`ENABLE_SEMANTIC_SAFETY=true` declared explicitly in `render.yaml`** instead of relying on the code default, so the safety configuration that ships is stated and comparable.
  - **Promotion procedure documented** — `OPERATIONS.md` §8: gate green for the exact commit, no regressed P0/P1, schema/restore-point check, dependency check, attestations still named, previous commit recorded as the rollback target, then post-promotion readiness and counter checks. It also states that a rollback does not revert data written by the new release.
- **Boundary note (explicit, per instruction):** this touched test expectations established while closing **ISSUE-003** (injection must not reach the model with context) and **ISSUE-008** (fail-closed output safety). No product behaviour changed. The reviewer still runs on **every** outbound reply including cached answers and canned refusals — that is ISSUE-008's intended wall and it was deliberately not weakened to make a cache-hit test cheaper. The ISSUE-003 assertion was strengthened rather than relaxed: it now asserts zero generation calls **and** that no call of any purpose carried the prior-turn details (`Dr Mehta`, `Pune`), which is the invariant the original total-call count was standing in for. Consequence worth recording: with the reviewer enabled, a response-cache hit still costs one provider call, so the cache saves generation cost, not all provider cost.
- **Files changed:** `render.yaml`; `.github/workflows/gate.yml` (new); `requirements-dev.txt` (new); `OPERATIONS.md`; `tests/test_deployment.py`; `tests/fake_llm.py`; `tests/test_api.py`; `tests/test_pipeline.py`; `tests/test_hardening.py`; `tests/test_security.py`; `issue.md`; `solution.md`.
- **Tests:** `tests/test_deployment.py::PromotionGateTests` — 8 tests (autoDeploy disabled, manifest points at the procedure, workflow exists and runs the suite, no failure-tolerating escape hatch, interpreter parity, safety-flag parity, dev dependencies pinned and excluded from the image, runbook documents the checklist). Determinism verified by running the full suite **twice**: with the developer `.env` → **469 passed, 2 skipped, 154 subtests**; and with `.env` moved aside plus the exact CI environment → **469 passed, 2 skipped, 155 subtests**. Before the fix the second configuration failed 5 tests.
- **External gate (not closed, needs):**
  1. **Branch protection on `main`** making `gate.yml` a *required* status check — a workflow can be bypassed by a direct push or an admin merge; only the platform setting makes it mandatory.
  2. **Immutable artifact promotion.** Render rebuilds from source at deploy time, so the released artifact is not the tested artifact (and without a hash-locked file, transitive dependencies can differ — shared with ISSUE-037). Closing this needs a built image promoted by digest.
  3. **Staged rollout and automated rollback.** No canary, no traffic-percentage stage, and no automatic rollback trigger; the documented rollback is a human promoting the previously recorded commit.
  4. **First CI execution.** The workflow is committed but has not run: this session made no push, so its green result on Python 3.12.7 is unverified — local verification ran on 3.14.7. The first push to GitHub is also the interpreter-parity evidence.
  5. **Migration gate.** Step 3 of the checklist is procedural; there is no automated pre-deploy schema/migration verification (shared with ISSUE-021).
- **Remaining limitations:** `autoDeploy: false` changes the owner's workflow — releases now require an explicit action in the Render dashboard (or a deploy hook). GitHub Actions versions are pinned by major tag (`actions/checkout@v4`, `actions/setup-python@v5`), not by commit SHA, so the action supply chain is still mutable; SHA pinning belongs with the ISSUE-037 hash-locking work. The gate proves the suite passes, not that the suite is sufficient — coverage adequacy remains ISSUE-031/033 territory. CI runs SQLite only; the Mongo integration path stays excluded because it needs a replica set (ISSUE-032).

### ISSUE-033 — COMPLETE (repository implementation)

- **Problem:** `pytest.ini` discovered only `tests/`, while four root-level scripts (`test_all.py`, `test_audit.py`, `context_audit.py`, `build_cache.py`) and two `tests/smoke_*.py` scripts each had their own ad-hoc invocation semantics. Nothing recorded which entry point was authoritative release evidence and which was a diagnostic, several were non-hermetic (wrote the working repository or hit the network), and a stale `Test_Report.md` sat in the tree readable as current results.
- **Where it occurred:** `pytest.ini`; `test_all.py`, `test_audit.py`, `context_audit.py`, `build_cache.py`; `tests/smoke_live.py`, `tests/smoke_staging.py`; `Test_Report.md`.
- **Why it occurred:** Test tooling accreted over time with no manifest, so discovery configuration and the loose scripts drifted apart and their trust/hermeticity status lived only in maintainers' heads.
- **Root cause:** No single source of truth for "what are all the entry points, which one gates a release, and which ones may touch real state."
- **Reproduction (before the fix):** `python -m pytest --collect-only -q .` aborted with `INTERNALERROR ... SystemExit: 0` — collecting root `test_all.py` executes it at import time and it calls `sys.exit()` — and then reported `no tests collected`, indistinguishable from a clean empty run. Separately, `test_audit.py` and `test_all.py` resolved `Settings.root` to the repository, so running them wrote the developer's real `data/chat_archive.sqlite3` (confirmed by the pre-existing archive mtime being the target of writes).
- **Fix:**
  - **`tests/lanes.py`** — the single manifest. Each entry point is a `Lane` recording its command, kind (`suite`/`diagnostic`/`operator`), whether it is hermetic, whether it gates a release, whether pytest may import it, and a mandatory human-readable reason. `AUTHORITATIVE_COMMAND` names the one command that counts as current evidence. Data-only, so it can be imported before the sandbox is bound.
  - **`tests/sandbox.py`** — the ISSUE-029 sandbox mechanics extracted into a reusable `activate_sandbox()` (create temp tree + copy read-only inputs + rebind `PROJECT_ROOT`). `tests/conftest.py` now calls it instead of duplicating the logic, so the suite and the diagnostics sandbox identically.
  - **Root `conftest.py`** — `collect_ignore` is *derived from the manifest* (`root_scripts_excluded_from_collection()`), so `pytest .` no longer imports a root script at collection and the ignore list cannot drift from `lanes.py`.
  - **`test_all.py` / `test_audit.py`** — now call `activate_sandbox()` before any `Settings` instance exists, so they can never write the working repository; verified by mtime before/after. Also reconfigured stdout `errors="replace"` because both printed check marks/arrows that raised `UnicodeEncodeError` on a Windows cp1252 console and made a fully-passing run exit non-zero.
  - **`context_audit.py`** — refuses to run without `SOULENE_ALLOW_LIVE_AUDIT=1` (guard runs before `requests` is imported), because it sends real traffic to a running server, spends budget, and writes `context_audit_results.json`. That output file is now `.gitignore`d.
  - **`tests/smoke_live.py` / `tests/smoke_staging.py`** — refuse without `SOULENE_ALLOW_LIVE_SMOKE=1`; they make real provider calls and, via `Settings.from_env()`, write the real `data/`.
  - **`Test_Report.md`** — a staleness banner (`NOT CURRENT TEST EVIDENCE`) now heads the file and points at the authoritative command.
  - **`DEVELOPER_GUIDE.md`** — the testing section now documents every lane, the one authoritative command, and the opt-in rule for non-hermetic lanes.
- **Boundary note (explicit):** this reuses the ISSUE-029 hermetic-sandbox boundary rather than introducing a second one — the sandbox logic moved into `tests/sandbox.py` and both `conftest.py` and the root scripts bind through it. No change to what "hermetic" means or to the autouse containment assertion.
- **Files changed:** `pytest.ini` (kept: still scopes the default run to `tests`); `conftest.py` (new, root); `tests/lanes.py` (new); `tests/sandbox.py` (new); `tests/conftest.py`; `tests/test_entry_points.py` (new); `test_all.py`; `test_audit.py`; `context_audit.py`; `tests/smoke_live.py`; `tests/smoke_staging.py`; `Test_Report.md`; `.gitignore`; `DEVELOPER_GUIDE.md`; `issue.md`; `solution.md`.
- **Tests:** `tests/test_entry_points.py` — 17 tests / 52 subtests: every discovered root/tests entry point is classified; the CI gate runs exactly the lanes marked `in_gate` and nothing marked out; no non-hermetic lane is ever in the gate; `pytest --collect-only .` now succeeds with >400 tests and no `INTERNALERROR`; the two diagnostics pass without mutating `data/`; every non-hermetic lane refuses without its opt-in and writes nothing when refused; `Test_Report.md` (if present) declares itself stale. Full suite: **486 passed, 2 skipped, 206 subtests** (was 469; +17).
- **Remaining limitations:** The manifest is enforced by pattern (`test_*.py`, `*_audit.py`, `build_*.py`, `tests/smoke_*.py`); an entry point with an unmatched name (e.g. `run_checks.py`) would not be forced into classification. The hermeticity check is behavioural (does `data/` change during a subprocess run), not a syscall sandbox, so a script writing outside both `data/` and the repo root would not be caught. `pytest.ini` still uses `testpaths = tests` rather than being folded into `pyproject.toml`; unifying build/test config into one file was out of scope. The diagnostics are proven to pass today but are not run in CI (they are diagnostics, not gates, by design).

## Executive Risk Summary

The audit retained **40 distinct findings**: 3 Critical, 25 High, 11 Medium, and 1 Low. The original P0 findings were `ISSUE-008`, `ISSUE-022`, and `ISSUE-026`; the first two now have verified repository remediations. `ISSUE-026` is contained for current/future commits but its historical exposure is an accepted, still-open Critical limitation and therefore remains a release blocker. Twenty-five P1 findings still require closure before production. Seven cross-control failure chains compound safety, privacy, security, retrieval, and deployment risk without collapsing their distinct root causes.

### Counts

- Temporal classification: `{"current-and-future": 19, "current-defect": 9, "future-risk": 12}`
- Severity: `{"critical": 3, "high": 25, "low": 1, "medium": 11}`
- Priority: `{"P0": 3, "P1": 25, "P2": 11, "P3": 1}`
- Primary domain: `{"architecture-correctness": 2, "data-database": 3, "dependency-supply-chain": 1, "deployment-operations": 5, "general-safety": 1, "input-output-fail-safe": 2, "memory-context": 1, "mental-health-safety": 5, "performance-reliability": 2, "privacy": 5, "rag-cag": 3, "security": 5, "testing-quality": 5}`
- Release blockers: 32 identifiers/classes (3 P0, 25 P1, plus four preserved test/validation blocker classes).

## Preserved Test and Validation Outcomes

- Catalog: **411** records; **295 eligible/executed exactly once**; **116 ineligible/not run**; terminal accounting is complete.
- Audit results: **243 pass**, **6 product-failure**, **42 environment-failure**, **4 inconclusive**, **116 skipped-ineligible**.
- Native statuses: **247 passed**, **6 failed**, **42 error**, **116 not-run**.
- The 42 environment failures are exactly one bounded **180-second `tests/test_hardening.py` batch timeout**. IDs: TST-131, TST-132, TST-133, TST-134, TST-135, TST-136, TST-137, TST-138, TST-139, TST-140, TST-141, TST-143, TST-144, TST-145, TST-146, TST-147, TST-148, TST-149, TST-150, TST-151, TST-154, TST-155, TST-156, TST-157, TST-158, TST-159, TST-160, TST-161, TST-162, TST-166, TST-167, TST-170, TST-171, TST-172, TST-173, TST-175, TST-176, TST-177, TST-178, TST-180, TST-181, TST-182. No per-test pass/fail inference is made.
- The six `tests/test_pipeline.py` product failures are:
- TST-248: AssertionError: 0 not greater than 0
- TST-251: AssertionError: False is not true
- TST-252: AssertionError: '449' not found in "Recent conversation:\nNo earlier conversation.\n\nKNOWLEDGE: nothing relevant is available for this factual question. Say you don't have that detail and suggest checking in the app — do not guess.\n\nUser just said:\nWhat is the Wellness plan price?"
- TST-253: AssertionError: False is not true
- TST-254: AssertionError: False is not true
- TST-263: AssertionError: 'never instructions' not found in "recent conversation:\nno earlier conversation.\n\nknowledge: nothing relevant is available for this factual question. say you don't have that detail and suggest checking in the app — do not guess.\n\nuser just said:\nwhat services do you offer?"
- Non-run classification: 111 helper/fixture support records (not standalone), three actual real-Mongo tests, and two live/staging scripts. No live model, staging HTTP, or real Mongo action was attempted.
- Property 5 remains **interrupted** with `^C`, exit code 1, no summary/counterexample, and no rerun.
- Property 4 remains **failed/unresolved** because the exact-case validator accepts alternate-case deliverable paths after case-folding; it was not rerun.
- Property 8 passed 240 generated examples. Property 9 failed once due a test-generator defect (an expected-valid conditional record omitted its mandatory condition); it was not repaired or rerun and is not represented as product behavior.

## Compounded Failure Chains

- CHAIN-001 (ISSUE-003, ISSUE-015, ISSUE-028, critical): Injection-class input can reach a model with prompt-labeled stored/retrieved context that also crosses an externally controlled privacy boundary.
- CHAIN-002 (ISSUE-004, ISSUE-012, ISSUE-014, ISSUE-034, ISSUE-035, critical): Non-unique document identity, non-atomic lifecycle operations, shared cache staging, worker-local state, and ephemeral paths can produce persistent knowledge divergence.
- CHAIN-003 (ISSUE-002, ISSUE-007, ISSUE-034, critical): Pre-commit local safety mutation, context-poor fallback, and multi-worker process isolation can make safety continuity depend on worker/failure routing.
- CHAIN-004 (ISSUE-008, ISSUE-011, ISSUE-031, critical): Fail-open output review, prompt-only relational boundaries, and incomplete scenario coverage can permit high-impact therapeutic harm regressions.
- CHAIN-005 (ISSUE-017, ISSUE-018, ISSUE-019, ISSUE-020, ISSUE-026, critical): Indefinite retention, incomplete deletion, non-transactional deletion, readable fields, and tracked runtime data compound sensitive-data exposure and irreversibility.
- CHAIN-006 (ISSUE-022, ISSUE-023, ISSUE-025, critical): Optional authentication, identity churn, and non-expiring principals combine into weak access and abuse containment.
- CHAIN-007 (ISSUE-013, ISSUE-029, high): Retrieval/no-result defects are test-observed, while the default suite lacks a universal hermetic path boundary.

## Verified Strengths and Effective Controls

- The 470-file frozen baseline and 470-record inventory reconcile exactly with one owner/disposition per file.
- Thirteen entry points, sixteen trace edges, seven subsystems, and twenty safety scenarios were reconciled before synthesis.
- Authoritative turn storage includes transaction/idempotency controls, owner-scoped reads, and durable state on successful commits.
- Deterministic crisis routing, response finalization, leak filtering, helpline normalization, and fake-model safety tests provide meaningful defense in depth.
- Direct dependencies are version-pinned, input/document bounds exist, and UI chat text uses textContent.
- The isolated test run attested path containment, Python-level egress denial, and unchanged protected files; 243 records passed.

## Coverage Proof

- Inventory: 470/470 baseline/inventory records; dispositions `{"content-reviewed": 89, "metadata-reviewed": 375, "structure-reviewed": 6}`; exactly one primary owner per file.
- Architecture: 13 entry points, 16 trace edges, 5 runtime-variant records, seven linked subsystems, and four explicitly unresolved external/runtime paths.
- Safety: 20 synthetic/redacted scenario records spanning language form, risk evolution, context sources, and component failures.
- Tests: 295/295 eligible records attempted once; test failures and non-runs remain visible rather than repaired.
- Evidence limitations are listed below; external behavior is not inferred as safe.

## Reviewed Domains Without a Primary Finding

- `maintainability` — No primary finding; reviewed through subsystem trace and secondary-domain evidence. Secondary references: ISSUE-016, ISSUE-021, ISSUE-024, ISSUE-033, ISSUE-035, ISSUE-036, ISSUE-037.

## Detailed Findings
## Current Defects

### ISSUE-001 — Silent message truncation can remove safety-critical suffixes

**Classification:** Domain `input-output-fail-safe`; temporal `current-defect`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** mental-health-safety, general-safety.

**Root cause / gap:** Input normalization truncates to 4,000 characters without rejecting the request or telling the user. There is no explicit length error, truncation marker, or safety-preserving tail inspection.

**Evidence:**
- `app/utils.py` — `clean_message` (repository-proven): The normalized string is sliced to the configured 4,000-character bound.
- `app/chatbot/chatbot_service.py` — `handle:87-181` (repository-proven): The truncated value is the value analyzed, generated from, and persisted.

**Affected components:** app/utils.py::clean_message; ChatbotService.handle; HTTP chat routes.

**Affected end-to-end flow:** TR-CHAT-2, TR-SAFE-1.

**Trigger conditions:**
- A message exceeds 4,000 characters
- Risk-relevant content occurs after the retained prefix

**Observed or projected impact:** The analyzed message can differ materially from user intent, allowing safety context or crisis language in the discarded suffix to be ignored.

**Existing controls:**
- Whitespace and Unicode normalization run before routing
- The retained prefix still passes deterministic and semantic safety

**Verification:** Call clean_message with a synthetic string longer than 4,000 characters and place a distinct marker after the boundary; compare the returned value.

---

### ISSUE-006 — Deterministic crisis floor over-escalates negated, quoted, and historical language

**Classification:** Domain `mental-health-safety`; temporal `current-defect`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** general-safety, input-output-fail-safe.

**Root cause / gap:** Self-harm phrase matching does not consistently distinguish subject, negation, quotation, or past versus present intent before selecting the crisis path. The deterministic floor can control the final route even when grammar indicates negation, quotation, history, or a different subject.

**Evidence:**
- `app/safety/guardrails.py` — `Guardrails.decide:307-367` (repository-proven): Regex-derived safety signals establish deterministic route decisions.
- `app/safety/guardrails.py` — `Guardrails.assess_safety_level:368+` (repository-proven): Matched self-harm forms map to concern/imminent levels without a general contextual parser.

**Affected components:** Guardrails.decide; Guardrails.assess_safety_level; ConversationRiskReasoner.

**Affected end-to-end flow:** TR-SAFE-1, TR-ROUTE-1.

**Trigger conditions:**
- Synthetic user denies current intent using a matched phrase
- User quotes another person
- User describes past resolved ideation

**Observed or projected impact:** Benign or contextual disclosures can receive urgent self-directed crisis handling, causing alarm, loss of trust, and reduced willingness to disclose accurately.

**Existing controls:**
- Semantic reasoner can add context when enabled
- Crisis handler uses empathetic language
- Third-party response path exists for some classifications

**Verification:** Evaluate synthetic examples such as a present denial, a quotation, a past-tense statement, and a third-party report through Guardrails in isolation.

**Mental-health safety detail:** Scenario `negated/quoted/historical/third-party self-harm language`; scope `single-turn and carried multi-turn context`; harm `false-positive and over-escalation harm`; path `normalization → guardrail regex → risk fusion → crisis route`; fail-safe gap: The deterministic floor lacks contextual disambiguation before urgent escalation.

---

### ISSUE-012 — Knowledge documents collide by basename

**Classification:** Domain `rag-cag`; temporal `current-defect`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** architecture-correctness, data-database.

**Root cause / gap:** KnowledgeCache._scan keys discovered documents by path.name rather than a unique relative path or content identity. The cache key cannot represent both same-named files.

**Evidence:**
- `app/cag/knowledge_cache.py` — `_scan:200-223` (repository-proven): The scan result is keyed by basename.

**Affected components:** KnowledgeCache._scan; KnowledgeCache.refresh; document APIs.

**Affected end-to-end flow:** TR-DOC-1, TR-DOC-2.

**Trigger conditions:**
- Two supported files in different subdirectories have the same basename

**Observed or projected impact:** One document can silently replace another in scan/index state, producing incomplete retrieval and ambiguous deletion.

**Existing controls:**
- Content hashes track changed files
- Supported-extension filtering

**Verification:** Create two synthetic same-named files under separate sandbox subdirectories and compare scan/document results.

---

### ISSUE-013 — Lexical retrieval miss injects arbitrary leading sections

**Classification:** Domain `rag-cag`; temporal `current-defect`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** input-output-fail-safe, mental-health-safety.

**Root cause / gap:** When lexical search finds no relevant section, context construction falls back to the first bounded set of cached sections instead of returning no support. No-result semantics are replaced by arbitrary fallback and no user-facing uncertainty guarantee exists.

**Evidence:**
- `app/cag/knowledge_cache.py` — `build_context:370+` (repository-proven): No-match behavior selects the leading cached sections.
- `app/cag/knowledge_cache.py` — `search_sections:330-369` (repository-proven): Ranking is lexical and can return no relevant match.

**Affected components:** KnowledgeCache.search_sections; KnowledgeCache.build_context; ChatbotService._lookup.

**Affected end-to-end flow:** TR-ROUTE-1, TR-PROMPT-1.

**Trigger conditions:**
- A query has no lexical overlap with indexed knowledge
- Knowledge cache is non-empty

**Observed or projected impact:** The model can receive irrelevant or wrong-category material and present an unsupported answer with apparent knowledge grounding.

**Existing controls:**
- Context is token bounded
- Prompt labels knowledge as untrusted
- Lexical matches are ranked when present

**Verification:** Build a synthetic cache with unrelated sections and query with disjoint tokens; inspect constructed context.

---

### ISSUE-018 — Session deletion can leave legacy or unattributed memory

**Classification:** Domain `privacy`; temporal `current-defect`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** data-database, memory-context.

**Root cause / gap:** Deletion intentionally preserves records that cannot be attributed to the selected session, including legacy memory without complete provenance. There is no conservative quarantine/deletion rule or user-visible disclosure for unattributed records.

**Evidence:**
- `main.py` — `delete_session:418-439` (repository-proven): Session deletion coordinates archive and secondary memory cleanup.
- `app/memory` — `forget_session/provenance paths` (repository-proven): Session cleanup depends on provenance and retains records that cannot be attributed safely.

**Affected components:** main.py::delete_session; LongTermMemory provenance; archive deletion.

**Affected end-to-end flow:** TR-DEL-1, TR-DERIVED-1.

**Trigger conditions:**
- A user deletes one session
- Memory created by legacy/unattributed paths contains facts from that session

**Observed or projected impact:** A deletion request can succeed while personal or health-related derived data from the session remains retrievable.

**Existing controls:**
- Source message IDs support deletion for attributed memory
- Account deletion has a broader forget-user path

**Verification:** In an isolated store, create synthetic legacy/unattributed memory, delete its source session, and query remaining memory.

**Security/privacy detail:** Source/actor: Incomplete deletion workflow; asset: Derived personal and mental-health memory; boundary: Deletion API across archive and memory stores; sensitive-data impact: Residual data after a user-scoped deletion

---

### ISSUE-026 — A conversation archive database is tracked in Git

**Classification:** Domain `privacy`; temporal `current-defect`; severity **Critical**; priority **P0**; confidence `confirmed`.

**Secondary domains:** security, data-database, mental-health-safety.

**Root cause / gap:** Git metadata identifies data/chat_archive.sqlite3 as tracked, placing a persistent application database within version-controlled repository history. Runtime authorization does not protect repository history, and ordinary deletion cannot purge existing clones.

**Evidence:**
- `data/chat_archive.sqlite3` — `Git tracked-file metadata` (repository-proven): The application database path is tracked; content was not opened.
- `.git` — `read-only ls-files/history metadata` (repository-proven): Version-control metadata confirms persistence risk without reproducing values.

**Affected components:** data/chat_archive.sqlite3; .git/index/history; ChatArchive.

**Affected end-to-end flow:** TR-COMMIT-1.

**Trigger conditions:**
- The tracked database contains or previously contained user conversations or derived state
- Repository clones, backups, or history are accessible

**Observed or projected impact:** Current or historical sensitive records may be distributed through repository clones and remain recoverable after working-tree deletion.

**Existing controls:**
- No database values were read or reproduced during audit
- Application owner checks protect runtime queries

**Verification:** Run read-only Git tracked-file metadata inspection; do not open the database or print content.

**Security/privacy detail:** Source/actor: Repository reader, clone recipient, or history compromise; asset: Tracked conversation archive; boundary: Runtime data directory to version-control distribution; sensitive-data impact: Potential conversation and inferred health-data exposure; values intentionally not inspected

---

### ISSUE-029 — Default tests are not hermetic and can mutate repository-selected paths

**Classification:** Domain `testing-quality`; temporal `current-defect`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** architecture-correctness, data-database.

**Root cause / gap:** Several tests construct the application from environment/root settings and exercise document/cache/data operations without a universal temporary-path fixture. No suite-wide sandbox fixture proves every resolved path is temporary before import/execution.

**Evidence:**
- `tests/test_api.py` — `make_app/ApiTests` (repository-proven): Application construction uses environment-selected settings and route tests can touch root-selected state.
- `tests/test_hardening.py` — `RecoveryTests.test_corrupt_cache_file_recovers` (repository-proven): The recovery test targets the configured root cache path.
- `tests/test_spec_compliance.py` — `service setup` (repository-proven): Service construction reads environment-selected paths.

**Affected components:** tests/test_api.py; tests/test_hardening.py; tests/test_spec_compliance.py.

**Affected end-to-end flow:** EP-PYTEST, TR-DOC-1, TR-DOC-2.

**Trigger conditions:**
- Tests run from the live repository
- Environment selects default data, cache, or knowledge paths

**Observed or projected impact:** Routine test execution can overwrite cache, knowledge, identity, or database artifacts and makes results dependent on local state.

**Existing controls:**
- Many unit tests use TemporaryDirectory
- FakeLLM avoids provider calls in several suites

**Verification:** Static test review; execute only after copying to a findings-local sandbox with synthetic settings.

**Test evidence/gaps:** Ledger IDs: none. Named gaps: Suite-wide path-containment assertion; Live-tree mutation guard.

---

### ISSUE-030 — Archive degradation test patches a method unused by runtime

**Classification:** Domain `testing-quality`; temporal `current-defect`; severity **Medium**; priority **P2**; confidence `confirmed`.

**Secondary domains:** performance-reliability, mental-health-safety.

**Root cause / gap:** A resilience test patches archive.record while ChatbotService commits through record_turn. The injected failure is attached to the wrong interface.

**Evidence:**
- `tests/test_security.py` — `ResilienceTests.test_archive_failure_degrades_gracefully` (repository-proven): The test patches archive.record.
- `app/chatbot/chatbot_service.py` — `_record_turn:219-234` (repository-proven): Runtime calls archive.record_turn.

**Affected components:** tests/test_security.py::ResilienceTests.test_archive_failure_degrades_gracefully; ChatbotService._record_turn.

**Affected end-to-end flow:** TR-COMMIT-1.

**Trigger conditions:**
- The test is interpreted as proving archive-failure degradation

**Observed or projected impact:** The test can pass without exercising the intended authoritative commit failure, creating false confidence in a safety-critical partial-failure path.

**Existing controls:**
- Other idempotency/archive tests exercise record_turn behavior

**Verification:** Inspect the patch target and runtime call graph; in a sandbox, assert the intended patch is invoked.

**Test evidence/gaps:** Ledger IDs: none. Named gaps: Real authoritative-commit failure injection.

---

### ISSUE-033 — Test entry points and historical outputs are fragmented outside default discovery

**Classification:** Domain `testing-quality`; temporal `current-defect`; severity **Low**; priority **P3**; confidence `confirmed`.

**Secondary domains:** maintainability.

**Root cause / gap:** pytest.ini discovers tests/, while root test_all.py, test_audit.py, context_audit.py, and smoke scripts have separate invocation semantics; historical reports can be stale and are not generated by one authoritative runner. There is no single manifest that classifies and runs or explicitly skips every test entry point.

**Evidence:**
- `pytest.ini` — `testpaths` (repository-proven): Default discovery is limited to tests/.
- `test_all.py` — `__main__` (repository-proven): Root script is a separate entry point.
- `context_audit.py` — `__main__` (repository-proven): Historical audit script performs its own network/write workflow.

**Affected components:** pytest.ini; test_all.py; test_audit.py; context_audit.py; historical reports.

**Affected end-to-end flow:** EP-PYTEST, EP-ROOT-ALL, EP-ROOT-AUDIT, EP-CONTEXT-AUDIT.

**Trigger conditions:**
- Engineers run only default pytest
- Historical result files are treated as current evidence

**Observed or projected impact:** Important checks can be omitted or outdated outputs can be mistaken for current quality evidence.

**Existing controls:**
- Separate scripts are visible in repository
- This audit catalogs them independently

**Verification:** Compare pytest discovery configuration with the generated catalog paths.

**Test evidence/gaps:** Ledger IDs: none. Named gaps: Unified all-entry-point test accounting.

## Future Risks

### ISSUE-005 — CLI bypasses HTTP identity, authorization, and abuse controls

**Classification:** Domain `security`; temporal `future-risk`; severity **Medium**; priority **P2**; confidence `confirmed`.

**Secondary domains:** deployment-operations.

**Root cause / gap:** The CLI invokes the shared service directly with an environment-derived or random session identity and does not pass through request guards. The trust assumption is implicit and unenforced.

**Evidence:**
- `main.py` — `run_cli:505-537` (repository-proven): The direct service path has no HTTP authentication, revocation, or rate-limit layer.

**Affected components:** main.py::run_cli; ChatbotService.handle.

**Affected end-to-end flow:** TR-CLI-1.

**Trigger conditions:**
- CLI is exposed beyond a trusted local administrator
- CLI storage points at shared production data

**Observed or projected impact:** A future operational wrapper or shell exposure could permit unthrottled model/storage use under weakly bound identities.

**Existing controls:**
- CLI is currently a local process entry point
- Non-empty input is required

**Verification:** Static trace only; do not expose or execute the CLI against live storage.

**Non-reproducibility limit:** Impact depends on a future deployment exposing the local CLI boundary.

**Security/privacy detail:** Source/actor: Untrusted local/process caller if the CLI is exposed; asset: Model quota and conversation storage; boundary: Local terminal to application service; sensitive-data impact: Potential access or creation under weak identity binding

---

### ISSUE-011 — Vulnerable-user dependency and false-authority risks lack deterministic boundaries

**Classification:** Domain `general-safety`; temporal `future-risk`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** mental-health-safety, privacy.

**Root cause / gap:** System prompts advise supportive behavior, but server-side output controls do not comprehensively prohibit exclusivity, emotional dependency, coercion, diagnosis, treatment authority, or replacement of professional care. Prompt instructions are not an enforceable final-output control and there is no longitudinal dependency detector.

**Evidence:**
- `app/prompts/system_prompt.py` — `build_instructions` (repository-proven): Behavioral boundaries are supplied to the model as instructions.
- `app/chatbot/response_builder.py` — `apply_output_safety:251-303` (repository-proven): Deterministic finalization has no complete dependency/coercion taxonomy.

**Affected components:** system_prompt; ResponseBuilder; ChatbotService.

**Affected end-to-end flow:** TR-PROMPT-1, TR-OUT-1.

**Trigger conditions:**
- Extended vulnerable-user conversation
- Model adopts an exclusive, authoritative, or coercive relational stance
- Output reviewer is unavailable or disabled

**Observed or projected impact:** At scale or after model/prompt drift, users may be encouraged to rely on the assistant in ways that worsen isolation or delay qualified care.

**Existing controls:**
- Prompt-level boundaries
- Crisis escalation
- Domain enforcement

**Verification:** A future-risk conclusion from static control coverage; live model behavior was not invoked.

**Non-reproducibility limit:** Present model behavior was not tested against a live external provider; the missing control is repository-proven.

**Mental-health safety detail:** Scenario `vulnerable user developing emotional dependency`; scope `multi-turn`; harm `cumulative privacy and boundary harm`; path `prompt → model → output filters`; fail-safe gap: No deterministic relational-boundary enforcement.

---

### ISSUE-016 — Knowledge provenance is not carried to user-visible responses

**Classification:** Domain `rag-cag`; temporal `future-risk`; severity **Medium**; priority **P2**; confidence `confirmed`.

**Secondary domains:** maintainability, mental-health-safety.

**Root cause / gap:** Cached sections retain source metadata internally, but normal response generation has no repository-proven citation or support-verification contract exposed to users. Internal provenance does not become a stable claim-to-source mapping or freshness indicator.

**Evidence:**
- `app/cag/knowledge_cache.py` — `CachedSection.rendered:83-90` (repository-proven): Sections carry/render metadata.
- `app/chatbot/chatbot_service.py` — `_generate:756-767` (repository-proven): Generated reply does not enforce citations.

**Affected components:** CachedSection; KnowledgeCache.build_context; ChatbotService._generate.

**Affected end-to-end flow:** TR-PROMPT-1, TR-RESP-1.

**Trigger conditions:**
- Knowledge-backed answer is wrong, stale, or contested
- Users need to verify mental-health or operational guidance

**Observed or projected impact:** Users and reviewers may be unable to distinguish grounded guidance from model synthesis or trace a claim to a maintained source.

**Existing controls:**
- Section metadata and hashes exist
- Prompt can receive rendered source information

**Verification:** Static trace; no live generated claims were tested.

**Non-reproducibility limit:** The future user-harm likelihood depends on generated claims; the missing citation contract is repository-proven.

---

### ISSUE-020 — Stored sensitive data lacks application-level encryption

**Classification:** Domain `privacy`; temporal `future-risk`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** data-database, security, mental-health-safety.

**Root cause / gap:** Conversation text, feedback, summaries, memories, and inferred safety state are stored as readable application fields; repository evidence does not establish field encryption or deployment-volume/database encryption controls. Application-level protection, key separation/rotation, and verified at-rest platform controls are absent from repository evidence.

**Evidence:**
- `app/storage/chat_archive.py` — `schema and record_turn` (repository-proven): Message and safety fields are persisted as ordinary database values.
- `app/storage/chat_archive_mongo.py` — `record_turn` (repository-proven): Mongo documents store ordinary application fields.
- `render.yaml` — `disk and Mongo configuration` (repository-proven): No encryption/key-management policy is declared.

**Affected components:** SQLite/Mongo archives; feedback stores; memory/profile stores; data directory.

**Affected end-to-end flow:** TR-COMMIT-1, TR-DERIVED-1.

**Trigger conditions:**
- Database file, backup, volume, Mongo collection, or operator credential is exposed

**Observed or projected impact:** Storage compromise can disclose highly sensitive personal and mental-health context in bulk.

**Existing controls:**
- Owner-scoped application queries
- Signed pseudonymous identities
- Platform controls may exist but are not repository-proven

**Verification:** Static schema/configuration review only; protected database contents were not opened or reproduced.

**Non-reproducibility limit:** No live infrastructure or protected database values were inspected; missing repository control evidence supports future risk only.

**Security/privacy detail:** Source/actor: Storage, backup, or privileged-operator compromise; asset: Conversation and derived health data; boundary: Application process to persistence backend; sensitive-data impact: Bulk plaintext-at-application-layer disclosure

**External validation needed:** Platform and managed-database encryption, backup, and access controls require independent deployment validation.

---

### ISSUE-021 — Schema evolution, backup, restore, and orphan cleanup are unsupported by repository evidence

**Classification:** Domain `data-database`; temporal `future-risk`; severity **Medium**; priority **P2**; confidence `confirmed`.

**Secondary domains:** deployment-operations, maintainability.

**Root cause / gap:** Backends create/upgrade structures in application code, but no versioned migration plan, backup/restore procedure, rollback rehearsal, or orphan-reconciliation job is present. There is no release-coupled schema version, reversible migration, backup evidence, restore acceptance test, or orphan inventory.

**Evidence:**
- `app/storage/chat_archive.py` — `initialization/schema methods` (repository-proven): Schema is managed inline rather than through a versioned migration set.
- `app/storage/chat_archive_mongo.py` — `_ensure_indexes:47-89` (repository-proven): Indexes are ensured at runtime without a broader migration/rollback contract.
- `render.yaml` — `service/disk configuration` (repository-proven): No backup or restore procedure is defined.

**Affected components:** ChatArchive; ChatArchiveMongo; feedback stores; mongo_client; deployment docs.

**Affected end-to-end flow:** TR-COMMIT-1, TR-DEL-1, TR-DEPLOY-1.

**Trigger conditions:**
- A release changes schemas/indexes
- A restore is required
- A partial migration or deletion leaves orphan records

**Observed or projected impact:** Future deployments can fail incompatibly, lose data, or retain orphan sensitive records without a tested recovery path.

**Existing controls:**
- SQLite initialization is transactional
- Mongo index creation exists
- JSON legacy migration helper exists

**Verification:** Static repository review; live backup and restore tests are outside the no-external-service boundary.

**Non-reproducibility limit:** The failure requires a future schema change or recovery event; the missing controls are repository-proven.

---

### ISSUE-027 — Browser security headers are not explicitly enforced

**Classification:** Domain `security`; temporal `future-risk`; severity **Medium**; priority **P2**; confidence `confirmed`.

**Secondary domains:** deployment-operations.

**Root cause / gap:** Flask responses and deployment configuration contain no repository-evident Content-Security-Policy, HSTS, frame-ancestor/X-Frame-Options, Referrer-Policy, or related response-header policy. No application or repository-declared platform header baseline exists.

**Evidence:**
- `main.py` — `response hooks/configuration` (repository-proven): No explicit security-header response hook is defined.
- `render.yaml` — `service configuration` (repository-proven): No header policy is declared.

**Affected components:** main.py Flask app; ui/index.html; render.yaml.

**Affected end-to-end flow:** TR-RESP-1, TR-DEPLOY-1.

**Trigger conditions:**
- The browser UI is publicly deployed
- A future template/script injection or framing attack is possible
- TLS termination does not inject equivalent headers

**Observed or projected impact:** Defense in depth against framing, mixed transport, content injection, and referrer leakage is reduced.

**Existing controls:**
- UI inserts chat text with textContent
- Cookies can be Secure/HttpOnly/SameSite

**Verification:** Static review only; platform-injected headers require external validation.

**Non-reproducibility limit:** The live edge was not contacted; missing repository evidence supports a future risk.

**Security/privacy detail:** Source/actor: Web attacker exploiting future browser-content or framing weakness; asset: User session/UI trust; boundary: HTTP response to browser; sensitive-data impact: Potential UI/session exposure if another defect is exploitable

**External validation needed:** Production edge/TLS header injection requires deployment validation.

---

### ISSUE-031 — Critical mental-health scenario families lack systematic regression coverage

**Classification:** Domain `testing-quality`; temporal `future-risk`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** mental-health-safety, general-safety.

**Root cause / gap:** Existing safety tests cover explicit phrases and selected emotions but do not form a complete matrix for negation, quotation, history, third-party context, euphemism/obfuscation, Unicode, evolving multi-turn state, reviewer failure, dependency, delusion, and geographic resources. Coverage is example-driven and does not enforce the required scenario/failure matrix end to end.

**Evidence:**
- `tests/test_upgrades.py` — `SafetyLevelTests and GuardrailTests` (repository-proven): Tests cover explicit phrases and selected classifications.
- `tests/test_reasoning_safety.py` — `safety tests` (repository-proven): Reasoner behavior has coverage but not every required language/failure/evolution dimension.
- `tests` — `catalog generated by this task` (repository-proven): No complete named scenario matrix was found.

**Affected components:** tests/test_reasoning_safety.py; tests/test_upgrades.py; tests/test_spec_compliance.py; tests/test_legacy_parity.py.

**Affected end-to-end flow:** TR-SAFE-1, TR-OUT-1.

**Trigger conditions:**
- Guardrails, prompts, models, or policies change
- A missed scenario reaches production

**Observed or projected impact:** Safety regressions can pass the suite despite foreseeable false positives, false negatives, and cumulative harms.

**Existing controls:**
- Explicit self-harm and imminent-risk tests
- Emotion/grief tests
- Some multi-turn reasoning tests
- Fake LLM support

**Verification:** Reconcile the generated test catalog against safety-scenarios.jsonl required dimensions.

**Non-reproducibility limit:** This is a repository-proven coverage gap whose user impact depends on a future regression or untested input.

**Test evidence/gaps:** Ledger IDs: none. Named gaps: Negated/quoted/historical/third-party crisis calibration; Obfuscated and multilingual risk; Dependency/delusion/diagnosis output; Locale-aware crisis resources; Pre-commit safety rollback.

---

### ISSUE-032 — Live/destructive integration tests have no contained offline substitute

**Classification:** Domain `testing-quality`; temporal `future-risk`; severity **Medium**; priority **P2**; confidence `confirmed`.

**Secondary domains:** deployment-operations, data-database.

**Root cause / gap:** Mongo integration and live/staging smoke suites require networking, credentials, processes, writes, or database drops and therefore cannot run under the audit boundary; equivalent contract tests are incomplete. No fully contained replica/provider contract harness supplies deterministic CI evidence.

**Evidence:**
- `tests/test_mongo_integration.py` — `RealMongoMultiWorkerTests` (repository-proven): Suite connects to a real replica set, spawns processes, writes, and drops a generated database.
- `tests/smoke_live.py` — `main` (repository-proven): Script invokes live model/storage behavior.
- `tests/smoke_staging.py` — `main` (repository-proven): Script contacts a staging HTTP endpoint.

**Affected components:** tests/test_mongo_integration.py; tests/smoke_live.py; tests/smoke_staging.py.

**Affected end-to-end flow:** EP-SMOKE-LIVE, EP-SMOKE-STAGING.

**Trigger conditions:**
- Provider, deployment, or Mongo semantics change
- CI omits opt-in suites

**Observed or projected impact:** Backend transaction, provider, and deployment regressions may be discovered only in live environments or not at all.

**Existing controls:**
- Opt-in integration scripts exist
- SQLite and fake-model unit coverage exists

**Verification:** Static classification only; these tests must remain ineligible without enforced egress denial and disposable services.

**Non-reproducibility limit:** Live services were intentionally not contacted.

**Test evidence/gaps:** Ledger IDs: none. Named gaps: Offline provider contract; Disposable Mongo transaction parity; Contained staging API contract.

---

### ISSUE-036 — Database clients and feedback connections lack an explicit shutdown lifecycle

**Classification:** Domain `performance-reliability`; temporal `future-risk`; severity **Medium**; priority **P2**; confidence `confirmed`.

**Secondary domains:** data-database, maintainability.

**Root cause / gap:** A shared MongoClient and SQLite feedback connection are initialized lazily, but no application shutdown hook closes them during worker termination or reload. No repository-proven production teardown hook or connection ownership contract exists.

**Evidence:**
- `app/storage/mongo_client.py` — `get_mongo_db/reset_mongo` (repository-proven): Client lifecycle is module-shared and reset is not registered as application shutdown.
- `main.py` — `application lifecycle` (repository-proven): No teardown hook closes shared clients/connections.

**Affected components:** app/storage/mongo_client.py; FeedbackStore; main.py lifecycle; Gunicorn.

**Affected end-to-end flow:** TR-DEPLOY-1.

**Trigger conditions:**
- Rolling deploy, worker recycle, test teardown, or process shutdown

**Observed or projected impact:** Connections and background resources may linger until process exit, complicating graceful shutdown, tests, and capacity planning.

**Existing controls:**
- Process exit eventually releases OS resources
- Mongo reset helper exists for tests

**Verification:** Static lifecycle trace; observing live connection cleanup is outside the audit boundary.

**Non-reproducibility limit:** The risk manifests during process lifecycle events not executed against live services.

---

### ISSUE-037 — Dependency installation is reproducible only by version, not artifact

**Classification:** Domain `dependency-supply-chain`; temporal `future-risk`; severity **Medium**; priority **P2**; confidence `confirmed`.

**Secondary domains:** maintainability, security.

**Root cause / gap:** Top-level dependencies are exactly version-pinned, but no hash-locked resolver output or vendored artifact set exists, and deployment upgrades pip then downloads from public indexes. No hashes, transitive lock, trusted mirror, SBOM, or verified-build policy is declared.

**Evidence:**
- `requirements.txt` — `all dependency declarations` (repository-proven): Direct versions are exact but artifact hashes/transitive resolution are absent.
- `render.yaml` — `buildCommand` (repository-proven): Build upgrades pip and installs from configured public indexes.

**Affected components:** requirements.txt; render.yaml buildCommand.

**Affected end-to-end flow:** TR-DEPLOY-1.

**Trigger conditions:**
- A package artifact/index is compromised, removed, or resolves transitive dependencies differently
- A rebuild occurs at a later date

**Observed or projected impact:** Identical source revisions may install different transitive artifacts or become exposed to index/supply-chain events.

**Existing controls:**
- Direct dependencies use exact versions
- Dependency list is small and explicit

**Verification:** Static review only; registries and advisory services were not queried.

**Non-reproducibility limit:** No package registry or advisory service was contacted; this is a control-gap future risk.

**External validation needed:** Current package advisories and artifact provenance require external validation.

---

### ISSUE-039 — Operational recovery, monitoring, and capacity controls are not repository-defined

**Classification:** Domain `deployment-operations`; temporal `future-risk`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** performance-reliability, data-database, mental-health-safety.

**Root cause / gap:** Repository configuration defines basic logs/timeouts but no alerting, SLOs, backup/restore runbooks, queue/backpressure limits, model cost budgets, disk thresholds, incident response, or tested capacity envelope. Controls are isolated defaults rather than a measured operational safety system.

**Evidence:**
- `render.yaml` — `service resource/log/time settings` (repository-proven): Basic worker/time settings exist without SLO, alert, backup, or capacity policy.
- `architecture/unresolved-paths` — `production platform/network` (inferred): No repository evidence resolves monitoring, backup, restore, proxy, or alerting controls.

**Affected components:** render.yaml; logging; deployment docs; storage/cache settings.

**Affected end-to-end flow:** TR-DEPLOY-1.

**Trigger conditions:**
- User/request/knowledge/storage volume grows
- Model or database latency rises
- Disk fills
- Provider outage or safety incident occurs

**Observed or projected impact:** Failures may be detected late, costs and latency can grow unpredictably, and operators may lack a safe recovery path during incidents affecting vulnerable users.

**Existing controls:**
- Gunicorn request timeout
- Application log levels
- Bounded in-process caches
- Health endpoint

**Verification:** Static review; live platform configuration was not accessed.

**Non-reproducibility limit:** Live operations configuration is outside repository evidence and external access was prohibited.

**External validation needed:** Platform monitoring, WAF, TLS, backups, and alerts require external validation.

---

### ISSUE-040 — Automatic deployment from main lacks an artifact-promotion gate

**Classification:** Domain `deployment-operations`; temporal `future-risk`; severity **Medium**; priority **P2**; confidence `confirmed`.

**Secondary domains:** testing-quality, dependency-supply-chain.

**Root cause / gap:** The manifest enables automatic deployment from main, while repository evidence does not define a mandatory test/security/safety gate or immutable promoted artifact. No repository-defined pre-deploy acceptance, staged canary, migration gate, or artifact provenance is required.

**Evidence:**
- `render.yaml` — `branch/autoDeploy` (repository-proven): Main branch changes deploy automatically.
- `pytest.ini` — `test configuration` (repository-proven): Test discovery exists but is not linked to deployment as a mandatory gate.

**Affected components:** render.yaml autoDeploy; branch main; test configuration.

**Affected end-to-end flow:** TR-DEPLOY-1.

**Trigger conditions:**
- A change reaches main with incomplete tests or configuration
- Dependency rebuild differs

**Observed or projected impact:** Untested safety, schema, or dependency changes can be rebuilt and released directly, increasing rollback and regression risk.

**Existing controls:**
- Version-pinned direct dependencies
- Platform health check
- Git history supports rollback of source

**Verification:** Static deployment-flow review; no deployment action was triggered.

**Non-reproducibility limit:** The failure requires a future release event; missing promotion controls are repository-proven.

## Current and Future

### ISSUE-002 — Failed first-turn commits can leave process-local safety mutations

**Classification:** Domain `architecture-correctness`; temporal `current-and-future`; severity **High**; priority **P1**; confidence `probable`.

**Secondary domains:** mental-health-safety, data-database, performance-reliability.

**Root cause / gap:** Safety state and analyzer counters mutate before the authoritative archive commit, while context rehydration does not clear process-local state when no stored state exists. The no-record rehydration path has no explicit reset/rollback of pre-commit process state.

**Evidence:**
- `app/chatbot/chatbot_service.py` — `handle:87-181` (repository-proven): Analysis and state mutation precede _record_turn.
- `app/chatbot/chatbot_service.py` — `_ensure_context_loaded:804-829` (inferred): Stored state is restored when present; no stored-state branch does not prove rollback of existing local state.

**Affected components:** ChatbotService.handle; ConversationRiskReasoner; Analyzer; ChatbotService._ensure_context_loaded.

**Affected end-to-end flow:** TR-SAFE-1, TR-COMMIT-1.

**Trigger conditions:**
- First turn for a new context
- Response analysis occurs
- record_turn fails before any authoritative state is stored
- Retry reaches the same worker

**Observed or projected impact:** A retry can inherit escalation, repetition, or de-escalation state from a turn that was never committed, changing the next safety decision.

**Existing controls:**
- Authoritative history is rehydrated before normal turns
- Archive failure prevents a user-visible response
- Persisted safety state is bundled with successful turn commits

**Verification:** In an isolated copy, inject an archive failure on a new context after analysis, retry on the same service instance, and compare local risk/counter state with a fresh instance.

---

### ISSUE-003 — Prompt-injection intent still reaches the model with privileged context

**Classification:** Domain `input-output-fail-safe`; temporal `current-and-future`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** security, privacy, memory-context.

**Root cause / gap:** Injection detection changes strategy and prompt wording but does not create a deterministic no-model boundary before recent history, summaries, memory, and knowledge are assembled. There is no server-side context minimization or deterministic refusal for injection-classified requests.

**Evidence:**
- `app/chatbot/chatbot_service.py` — `_respond:430-493` (repository-proven): Injection strategy can continue to generation.
- `app/chatbot/chatbot_service.py` — `_build_prompt:720-755` (repository-proven): Recent, cross-session, memory, and knowledge context are assembled for model generation.

**Affected components:** ChatbotService._respond; ChatbotService._build_prompt; system_prompt.

**Affected end-to-end flow:** TR-ROUTE-1, TR-PROMPT-1, TR-OUT-1.

**Trigger conditions:**
- Input matches an injection pattern
- Model generation remains available
- Conversation or retrieval context contains sensitive or steering content

**Observed or projected impact:** Adversarial input can influence an external model invocation that includes context the attacker should not control, relying on probabilistic instruction following and output filtering.

**Existing controls:**
- Prompt labels retrieved/history material as untrusted
- Leak regexes and output policy run before delivery
- Owner scoping limits cross-user context

**Verification:** Use a synthetic injection message with instrumented fake model input in a findings-local copy and inspect whether contextual sections are still present.

---

### ISSUE-004 — Document upload and deletion are not atomic across file and index state

**Classification:** Domain `architecture-correctness`; temporal `current-and-future`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** rag-cag, data-database, performance-reliability.

**Root cause / gap:** Filesystem changes and knowledge-cache refresh/removal occur as separate operations without rollback; deletion searches recursively by sanitized basename. No transaction, unique document identity, compensating rollback, or one-to-one file/index commit exists.

**Evidence:**
- `main.py` — `upload_document:314-352` (repository-proven): The uploaded file is saved before cache refresh; refresh failure does not remove the saved file.
- `main.py` — `delete_document:354-372` (repository-proven): Deletion uses recursive matching by sanitized name and coordinates cache/file removal without a transaction.

**Affected components:** main.py::upload_document; main.py::delete_document; KnowledgeCache.refresh; KnowledgeCache.remove_document.

**Affected end-to-end flow:** TR-DOC-1, TR-DOC-2.

**Trigger conditions:**
- File save succeeds and refresh fails
- In-memory removal succeeds and unlink fails
- Multiple documents share the same basename in different directories

**Observed or projected impact:** Users can observe files that are not indexed, indexes that no longer match files, or deletion of every same-named document rather than one selected object.

**Existing controls:**
- Extension allowlist
- basename sanitization
- upload size limit
- Refresh hashes changed documents

**Verification:** In an isolated synthetic knowledge tree, create duplicate basenames and inject refresh/unlink failures while comparing filesystem and index state.

---

### ISSUE-007 — Ambiguous and evolving risk can fall back to a context-poor deterministic floor

**Classification:** Domain `mental-health-safety`; temporal `current-and-future`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** input-output-fail-safe, performance-reliability.

**Root cause / gap:** Semantic risk reasoning failures are intentionally caught and replaced by deterministic current-message signals, which do not preserve all implicit or cumulative multi-turn meaning. The fallback does not implement equivalent multi-turn trajectory analysis or an uncertainty-to-safe-check-in policy.

**Evidence:**
- `app/safety/reasoner.py` — `ConversationRiskReasoner.assess:105-137` (repository-proven): Semantic errors fall back to deterministic assessment.
- `app/safety/reasoner.py` — `_signals:273+` (repository-proven): Fallback features are lexical/regex-derived rather than a complete conversational state model.

**Affected components:** ConversationRiskReasoner.assess; Guardrails; ChatbotService._analyze.

**Affected end-to-end flow:** TR-SAFE-1.

**Trigger conditions:**
- Semantic classifier is disabled, unavailable, times out, or returns malformed output
- Risk is implicit, euphemistic, obfuscated, or emerges across turns

**Observed or projected impact:** A vulnerable user can be under-escalated when no single message crosses regex thresholds even though the conversation trajectory indicates acute risk.

**Existing controls:**
- Deterministic floor remains available
- Recent history and persisted state are supplied to semantic reasoning
- Explicit phrases still trigger crisis

**Verification:** With a fake semantic client that raises or returns malformed data, evaluate a synthetic sequence whose risk is only apparent cumulatively.

**Mental-health safety detail:** Scenario `implicit/euphemistic cumulative distress under classifier failure`; scope `multi-turn`; harm `false-negative, under-escalation, cumulative harm`; path `history/state → semantic reasoner → exception fallback → deterministic floor`; fail-safe gap: Failure removes the richer context signal without equivalent conservative handling.

---

### ISSUE-008 — Model-output safety fails open and omits major therapeutic harm classes

**Classification:** Domain `mental-health-safety`; temporal `current-and-future`; severity **Critical**; priority **P0**; confidence `confirmed`.

**Secondary domains:** general-safety, input-output-fail-safe, deployment-operations.

**Root cause / gap:** The optional semantic output reviewer returns control to deterministic filters on error and is disabled in the production manifest; deterministic rules focus on leaks, code/domain, helplines, and promotion rather than the full mental-health harm taxonomy. No deterministic policy wall covers all specified therapeutic harms, and reviewer failure is permissive rather than conservative.

**Evidence:**
- `app/chatbot/response_builder.py` — `apply_output_safety:251-303` (repository-proven): Finalization applies deterministic filters and conditionally invokes semantic review.
- `app/chatbot/response_builder.py` — `_semantic_output_category:304+` (repository-proven): Semantic review exceptions do not prove safe output and fall through.
- `render.yaml` — `ENABLE_OUTPUT_SAFETY_CHECK` (repository-proven): The deployment manifest disables optional model output review for latency.

**Affected components:** ResponseBuilder.apply_output_safety; ResponseBuilder._semantic_output_category; render.yaml.

**Affected end-to-end flow:** TR-OUT-1, TR-DEPLOY-1.

**Trigger conditions:**
- Model emits diagnosis, treatment certainty, delusion reinforcement, dependency/coercion, shame, broad medical advice, or unsafe therapeutic claims
- Semantic output review is disabled or fails

**Observed or projected impact:** Unsafe authoritative-sounding mental-health output can be delivered after passing narrow deterministic checks.

**Existing controls:**
- Leak scrubbing
- No-code/domain enforcement
- Helpline normalization
- Medical promotion filter
- Input moderation and crisis routing

**Verification:** Use synthetic harmful replies for each omitted category with the reviewer disabled and with a reviewer that raises; inspect the final response in an isolated harness.

**Mental-health safety detail:** Scenario `unsafe generated therapeutic/relational content`; scope `single and multi-turn`; harm `false-negative and cumulative boundary harm`; path `model/cache output → deterministic filters → optional semantic reviewer → final response`; fail-safe gap: Reviewer absence/failure permits output not covered by narrow deterministic rules.

---

### ISSUE-009 — Rolling model summaries are persisted and reused without output safety validation

**Classification:** Domain `mental-health-safety`; temporal `current-and-future`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** memory-context, privacy.

**Root cause / gap:** Summary generation uses model output as derived context and stores/reuses it without routing the summary through the response safety validator or factual consistency checks. There is no summary-specific safety, provenance, contradiction, or user-correction gate before persistence and reuse.

**Evidence:**
- `app/chatbot/chatbot_service.py` — `_refresh_summary:552-626` (repository-proven): Generated summary text is stored as derived context.
- `app/chatbot/chatbot_service.py` — `_build_prompt:720-755` (repository-proven): Stored summary contributes to later model prompts.

**Affected components:** ChatbotService._refresh_summary; ContextCache; ChatbotService._build_prompt.

**Affected end-to-end flow:** TR-DERIVED-1, TR-PROMPT-1.

**Trigger conditions:**
- Summary refresh invokes the model
- The model misstates risk, identity, diagnosis, or user intent
- Later turns consume the summary

**Observed or projected impact:** A hallucinated or unsafe summary can silently bias future safety decisions and responses across many turns.

**Existing controls:**
- Summaries are bounded
- Authoritative archive remains separate
- Pending secondary work can retry

**Verification:** Instrument the fake model to return an unsafe or contradictory synthetic summary, then inspect stored summary and a later built prompt.

**Mental-health safety detail:** Scenario `stale or adversarial rolling summary`; scope `multi-turn`; harm `cumulative under/over-escalation and privacy harm`; path `committed turns → summary model → derived storage → later prompt`; fail-safe gap: Derived safety-relevant context bypasses output validation.

---

### ISSUE-010 — Emergency resource selection assumes one configured number without locale validation

**Classification:** Domain `mental-health-safety`; temporal `current-and-future`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** deployment-operations, input-output-fail-safe.

**Root cause / gap:** Crisis response uses a deployment-wide emergency number and has no verified user locale, resource directory, or fallback wording proving geographic applicability. No locale acquisition, resource verification, neutral fallback, or regular resource-review evidence exists.

**Evidence:**
- `app/safety/crisis.py` — `CrisisHandler.respond:90-122` (repository-proven): Crisis messaging uses configured emergency guidance.
- `render.yaml` — `EMERGENCY_NUMBER` (repository-proven): One deployment-wide number is supplied.

**Affected components:** CrisisHandler; ResponseBuilder.enforce_helpline_number; render.yaml.

**Affected end-to-end flow:** TR-ROUTE-1, TR-OUT-1.

**Trigger conditions:**
- A user in crisis is outside the configured emergency-number jurisdiction
- The configured number is unavailable for the user's location

**Observed or projected impact:** Urgent guidance can send a vulnerable user to an inapplicable resource and create false confidence about available help.

**Existing controls:**
- Crisis responses encourage immediate human help
- A number is centralized in configuration
- Output normalization can prevent conflicting numbers

**Verification:** Static configuration review; live dialing or external resource validation is prohibited.

**Mental-health safety detail:** Scenario `acute crisis outside configured jurisdiction`; scope `single-turn`; harm `under-escalation through unusable resource`; path `crisis route → configured number → output finalizer`; fail-safe gap: Resource applicability is not established.

**External validation needed:** Current emergency-resource coverage and jurisdictional correctness require human/external validation.

---

### ISSUE-014 — Knowledge cache persistence uses a shared fixed temporary filename

**Classification:** Domain `data-database`; temporal `current-and-future`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** performance-reliability, deployment-operations.

**Root cause / gap:** KnowledgeCache.save writes through one predictable .tmp path without inter-process locking or unique staging names. Atomic replacement does not serialize the shared staging path or cross-process state.

**Evidence:**
- `app/cag/knowledge_cache.py` — `save:177-199` (repository-proven): Persistence uses a fixed temporary path before replace.
- `render.yaml` — `startCommand` (repository-proven): Deployment starts two worker processes.

**Affected components:** KnowledgeCache.save; KnowledgeCache.refresh.

**Affected end-to-end flow:** TR-DOC-2, TR-DEPLOY-1.

**Trigger conditions:**
- Two workers save or refresh the same cache concurrently
- A worker terminates during replacement

**Observed or projected impact:** Concurrent writers can overwrite staging bytes, fail replacement, or persist a cache that does not correspond to either worker's index state.

**Existing controls:**
- Final replacement is atomic on supported filesystems
- Cache load can recover from some corruption

**Verification:** In an isolated copy only, coordinate two processes writing distinct synthetic cache states and compare outcomes.

---

### ISSUE-015 — Memory and retrieved text are only prompt-labeled as untrusted

**Classification:** Domain `memory-context`; temporal `current-and-future`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** security, mental-health-safety, general-safety.

**Root cause / gap:** Long-term memories, cross-session snippets, summaries, and knowledge are concatenated into model context; containment relies primarily on textual prompt instructions. There is no structural separation, content policy scan, provenance-based trust tier, or deterministic exclusion of instruction-like context.

**Evidence:**
- `app/chatbot/chatbot_service.py` — `_cross_session_context:652-703` (repository-proven): Cross-session text is selected for prompt use.
- `app/chatbot/chatbot_service.py` — `_build_prompt:720-755` (repository-proven): Memory, summaries, history, and knowledge are assembled into the model prompt.

**Affected components:** ChatbotService._cross_session_context; ChatbotService._build_prompt; system_prompt.

**Affected end-to-end flow:** TR-PROMPT-1.

**Trigger conditions:**
- Stored or retrieved content contains instructions or adversarial text
- The model follows data-plane instructions over policy

**Observed or projected impact:** Poisoned context can steer output, expose adjacent context, or alter safety behavior on later turns.

**Existing controls:**
- Owner scoping
- Context budgets
- Prompt labels context as untrusted
- Final output checks

**Verification:** Store synthetic instruction-like memory/knowledge in a sandbox and inspect the generated prompt and fake-model behavior.

---

### ISSUE-017 — Sensitive conversation and inferred-state records have no retention or expiry policy

**Classification:** Domain `privacy`; temporal `current-and-future`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** data-database, mental-health-safety.

**Root cause / gap:** Archives, summaries, safety state, memories, profiles, and feedback are persisted without repository-evident age-based expiry, retention schedule, or minimization policy. No data-class retention periods, expiry worker, minimization review, or deletion evidence ledger exists.

**Evidence:**
- `app/storage/chat_archive.py` — `ChatArchive schema and CRUD` (repository-proven): Conversation and safety records have no age-based expiry path.
- `app/storage/chat_archive_mongo.py` — `ChatArchiveMongo indexes/CRUD` (repository-proven): No TTL index or retention policy is established.
- `app/memory` — `memory implementations` (repository-proven): Derived memory lifecycle lacks a general expiry contract.

**Affected components:** ChatArchive; ChatArchiveMongo; LongTermMemory; ContextCache summaries; FeedbackStore.

**Affected end-to-end flow:** TR-COMMIT-1, TR-DERIVED-1, TR-DEL-1.

**Trigger conditions:**
- Users accumulate conversations and derived mental-health state
- Account deletion is not requested or cannot complete

**Observed or projected impact:** Highly sensitive records can persist indefinitely, increasing breach impact and privacy harm beyond the original support purpose.

**Existing controls:**
- User/session deletion routes
- Owner-scoped reads
- Bounded process caches

**Verification:** Create synthetic records with old timestamps in isolated backends and inspect whether normal lifecycle operations expire them.

**Security/privacy detail:** Source/actor: Data breach, operator over-retention, or abandoned account; asset: Conversation, feedback, summaries, memories, inferred safety state; boundary: Application to persistent storage; sensitive-data impact: Indefinite exposure of health-related and personal data

---

### ISSUE-019 — Account deletion is a multi-store saga without complete atomic rollback

**Classification:** Domain `data-database`; temporal `current-and-future`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** privacy, performance-reliability.

**Root cause / gap:** Account deletion tombstones the principal and then deletes authoritative and secondary records across independently failing stores. No cross-store transaction, durable deletion job state, compensation plan, or completion receipt spans every store.

**Evidence:**
- `main.py` — `delete_account:440-462` (repository-proven): Deletion coordinates multiple stores and can return failure after partial progress.
- `app/storage/chat_archive.py` — `delete_user` (repository-proven): Archive transaction cannot atomically include separate feedback/memory stores.

**Affected components:** main.py::delete_account; ChatArchive.delete_user; memory/profile deletion; FeedbackStore.

**Affected end-to-end flow:** TR-DEL-1.

**Trigger conditions:**
- A secondary archive, memory, feedback, or profile delete fails after earlier steps succeed

**Observed or projected impact:** The user can be blocked by the tombstone while some data remains, requiring retries or operator recovery and complicating deletion assurance.

**Existing controls:**
- Tombstone prevents continued use
- 503 signals partial failure
- Retry remains possible
- Backend-local transactions

**Verification:** Inject synthetic failures at each deletion step in isolated storage and verify durable job state, retry convergence, and residual records.

---

### ISSUE-022 — Production can start with API and admin authentication disabled

**Classification:** Domain `security`; temporal `current-and-future`; severity **Critical**; priority **P0**; confidence `confirmed`.

**Secondary domains:** deployment-operations, rag-cag.

**Root cause / gap:** Authentication keys are optional, empty values disable checks, document administration falls back to normal authentication, and deployment configuration does not enforce non-empty values at startup. Production mode does not fail closed when required boundary credentials are missing.

**Evidence:**
- `app/security.py` — `ApiAuth.enabled/check/check_admin` (repository-proven): Empty keys disable authentication and admin checks can fall back to normal auth.
- `main.py` — `_guard_request:137-175` (repository-proven): Route guards honor optional authentication.
- `render.yaml` — `API_KEY and ADMIN_API_KEY env declarations` (repository-proven): Keys are dashboard-supplied but no startup assertion is declared.

**Affected components:** ApiAuth; main._guard_request; document routes; render.yaml.

**Affected end-to-end flow:** TR-HTTP-1, TR-DOC-1, TR-DEPLOY-1.

**Trigger conditions:**
- API_KEY is absent or empty
- ADMIN_API_KEY is absent or empty
- Service is reachable by untrusted clients

**Observed or projected impact:** Unauthenticated callers can consume model/storage resources and, when both controls are absent, administer the knowledge base.

**Existing controls:**
- Shared-key constant-time comparison when configured
- Admin-key support
- Signed pseudonymous identities

**Verification:** Start an isolated configuration with empty synthetic keys and inspect guard outcomes; do not bind a live server.

**Security/privacy detail:** Source/actor: Unauthenticated internet client or deployment misconfiguration; asset: Model quota, conversations, metrics, document administration; boundary: Public network to Flask routes; sensitive-data impact: Unauthorized creation/access paths and possible knowledge poisoning

---

### ISSUE-023 — Anonymous identity churn can evade rate limits

**Classification:** Domain `security`; temporal `current-and-future`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** performance-reliability.

**Root cause / gap:** A request without a valid identity is issued a fresh pseudonymous user ID before rate-limit keying, so clients that discard cookies or headers can obtain new buckets. No pre-identity network/credential bucket or durable abuse signal constrains identity creation.

**Evidence:**
- `main.py` — `_client_identity:128-136` (repository-proven): Rate-limit identity is derived from the request principal.
- `app/identity.py` — `from_request` (repository-proven): A missing token causes a new random principal to be issued.
- `app/security.py` — `RateLimiter.check` (repository-proven): Buckets are keyed only by the provided key.

**Affected components:** main._client_identity; IdentityManager.from_request; RateLimiter.check.

**Affected end-to-end flow:** TR-HTTP-1.

**Trigger conditions:**
- Caller omits/discards identity cookie and header between requests
- Rate limiting is enabled

**Observed or projected impact:** Automated clients can multiply request allowance, increasing denial-of-wallet, abuse, and availability risk.

**Existing controls:**
- Per-identity sliding-window limiter
- Optional API authentication can provide a stable credential when enabled

**Verification:** Call request-boundary helpers with repeated synthetic requests that retain no identity and compare generated keys/buckets.

**Security/privacy detail:** Source/actor: Anonymous automated client; asset: Availability and model-provider quota; boundary: Network request to process-local limiter; sensitive-data impact: Indirect; abuse can degrade service for vulnerable users

---

### ISSUE-024 — Rate-limiter cleanup cannot remove stale non-empty buckets

**Classification:** Domain `performance-reliability`; temporal `current-and-future`; severity **Medium**; priority **P2**; confidence `confirmed`.

**Secondary domains:** security, maintainability.

**Root cause / gap:** Expired timestamps are removed only from the bucket being checked; global cleanup removes only already-empty buckets, so one-time identities remain non-empty forever unless revisited. Global cleanup does not evaluate timestamp age for idle non-empty buckets.

**Evidence:**
- `app/security.py` — `RateLimiter.check` (repository-proven): Only the active bucket is expired; threshold cleanup tests whether other deques are empty without aging them.

**Affected components:** RateLimiter._hits; RateLimiter.check.

**Affected end-to-end flow:** TR-HTTP-1.

**Trigger conditions:**
- More than 10,000 unique identities each make one request and never return

**Observed or projected impact:** Long-running workers can accumulate unbounded key dictionaries and waste memory under accidental or malicious identity churn.

**Existing controls:**
- A 10,000-key cleanup threshold exists
- Per-bucket timestamps use a bounded one-minute window

**Verification:** Use a synthetic clock or aged deques in an isolated unit harness and trigger cleanup from a different key.

---

### ISSUE-025 — Signed identity tokens have no intrinsic expiry or revocation

**Classification:** Domain `security`; temporal `current-and-future`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** privacy.

**Root cause / gap:** Identity payloads contain version and IDs but no issued-at, expiry, key identifier, or revocation epoch; header tokens are not constrained by cookie max-age. No server-enforced token lifetime, rotation key ID, session revocation list, or reauthentication mechanism exists.

**Evidence:**
- `app/identity.py` — `IdentityManager._build` (repository-proven): Payload contains only version, user ID, and session ID.
- `app/identity.py` — `IdentityManager.verify` (repository-proven): Verification checks signature/version/ID shape but not time or revocation.
- `app/identity.py` — `MAX_AGE_SECONDS` (repository-proven): Cookie age is client transport metadata, not token expiry.

**Affected components:** IdentityManager._build; IdentityManager.verify; IdentityManager.from_request.

**Affected end-to-end flow:** TR-HTTP-1, TR-DEL-1.

**Trigger conditions:**
- A token is copied or stolen
- Identity secret remains valid
- Token is replayed through the identity header

**Observed or projected impact:** A stolen bearer-like identity can remain valid for years or beyond user-side cookie deletion, enabling continued access to owner-scoped records.

**Existing controls:**
- HMAC signature
- Strong random IDs
- Secure cookie can be enabled
- Account tombstones can block known users

**Verification:** Issue a synthetic token, advance an isolated clock beyond cookie age, and verify that token parsing has no time check.

**Security/privacy detail:** Source/actor: Token thief or replaying client; asset: Owner-scoped sessions and conversation data; boundary: Client-provided identity header/cookie to server principal; sensitive-data impact: Long-lived unauthorized access to personal and health-related records

---

### ISSUE-028 — Sensitive context is transmitted to an external model without a repository-evident privacy control plane

**Classification:** Domain `privacy`; temporal `current-and-future`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** mental-health-safety, memory-context.

**Root cause / gap:** Current messages, recent transcripts, summaries, memories, inferred health state, and knowledge can be assembled for provider calls; no consent, per-field minimization, provider retention configuration, or data-processing policy is enforced in code/config. There is no repository-evident consent/notice, data classification filter, minimum-necessary selection, or provider-side retention assurance.

**Evidence:**
- `app/chatbot/chatbot_service.py` — `_build_prompt:720-755` (repository-proven): Multiple user-context sources are combined for model input.
- `app/safety/reasoner.py` — `_semantic_call:138-272` (repository-proven): Safety reasoning can send bounded transcript content to a model.
- `app/llm/client.py` — `generation/moderation methods` (repository-proven): Provider APIs are the external processing boundary.

**Affected components:** LLMClient; ChatbotService._build_prompt; ConversationRiskReasoner; ResponseBuilder.

**Affected end-to-end flow:** TR-SAFE-1, TR-PROMPT-1, TR-OUT-1.

**Trigger conditions:**
- Model generation or semantic safety is enabled
- Conversation contains personal or health-related information

**Observed or projected impact:** Sensitive user data crosses an external trust boundary with scope and downstream retention not controlled by repository logic.

**Existing controls:**
- Owner scoping before context assembly
- Context budgets
- No message-body logging observed
- Provider key is environment-managed

**Verification:** Static trace only; no external provider call or user data inspection was performed.

**Security/privacy detail:** Source/actor: External processor policy, compromise, or over-collection; asset: Conversation, memory, summary, and inferred health context; boundary: Application to model provider; sensitive-data impact: Disclosure of health-related and personal data to a third party

**External validation needed:** Provider retention, training, region, and contractual controls require external validation.

---

### ISSUE-034 — Two-worker deployment fragments process-local correctness and abuse state

**Classification:** Domain `deployment-operations`; temporal `current-and-future`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** architecture-correctness, performance-reliability, security, memory-context, rag-cag, mental-health-safety.

**Root cause / gap:** Gunicorn starts two processes while service singletons, turn locks, rate buckets, context/response caches, risk counters, and document refresh state are process-local. Process-local synchronization and invalidation cannot coordinate the declared multi-process topology.

**Evidence:**
- `render.yaml` — `startCommand` (repository-proven): Deployment declares two workers and four threads each.
- `main.py` — `module singletons` (repository-proven): Service, feedback, auth, and limiter instances are process-local.
- `app/chatbot/chatbot_service.py` — `_turn_lock:189-193` (repository-proven): Turn locks are held only in one service process.
- `app/cag` — `cache classes` (repository-proven): Context, response, and knowledge in-memory state is per process.

**Affected components:** render.yaml; main._service/_feedback/_limiter; ChatbotService._turn_lock; ContextCache; ResponseCache; KnowledgeCache.

**Affected end-to-end flow:** TR-DEPLOY-1, TR-CHAT-2, TR-DOC-2.

**Trigger conditions:**
- Requests for one user/session reach different workers
- Concurrent distinct request IDs target one session
- Document or cache state changes in one worker

**Observed or projected impact:** Workers can generate against stale history, apply inconsistent safety/rate decisions, serve stale documents, duplicate external calls, or lose cache/state continuity.

**Existing controls:**
- Authoritative turns are transactionally stored
- Request-id idempotency
- Owner-scoped archive rehydration
- Thread locks within one process

**Verification:** In a disposable isolated multi-process harness, route concurrent synthetic sessions/doc updates across workers and compare authoritative versus local state.

---

### ISSUE-035 — Deployment persists data/ but leaves active knowledge and cache paths ephemeral

**Classification:** Domain `deployment-operations`; temporal `current-and-future`; severity **High**; priority **P1**; confidence `confirmed`.

**Secondary domains:** rag-cag, performance-reliability, maintainability.

**Root cause / gap:** The manifest mounts only data/ although comments claim uploaded knowledge and built cache persistence; active knowledge/ and cache/ paths are separate repository directories. Mount layout and comments do not match active path layout; no startup reconciliation guarantees restoration.

**Evidence:**
- `render.yaml` — `disk.mountPath` (repository-proven): Only /opt/render/project/src/data is mounted.
- `render.yaml` — `disk comment` (repository-proven): Comment claims knowledge/cache persistence despite the mount path.
- `app/config/settings.py` — `knowledge_dir/cache_dir` (repository-proven): Knowledge and cache use distinct paths.

**Affected components:** render.yaml disk; Settings knowledge/cache paths; document routes; KnowledgeCache.

**Affected end-to-end flow:** TR-DOC-1, TR-DOC-2, TR-DEPLOY-1.

**Trigger conditions:**
- Document upload or cache build occurs in production
- Worker/container restarts or rolling deploys

**Observed or projected impact:** Uploaded documents and built cache can disappear across deploys, while workers may temporarily disagree about available knowledge.

**Existing controls:**
- data/ volume persists configured database/profile data
- Knowledge can be rebuilt from present files

**Verification:** Resolve configured paths statically and compare them with the mounted subtree; no live deployment access is needed.

---

### ISSUE-038 — Health checks can initialize the complete service and external backends

**Classification:** Domain `deployment-operations`; temporal `current-and-future`; severity **Medium**; priority **P2**; confidence `confirmed`.

**Secondary domains:** performance-reliability, architecture-correctness.

**Root cause / gap:** The open /health route calls get_service and archive readiness, so a probe can trigger lazy service construction, cache loading, secret/storage requirements, and backend connectivity. No cheap liveness endpoint, staged readiness state, startup budget, or dependency-specific diagnostics are separated.

**Evidence:**
- `main.py` — `health:193-203` (repository-proven): Health obtains the service and checks archive readiness.
- `main.py` — `get_service:62-75` (repository-proven): Lazy service construction initializes application components.

**Affected components:** main.health; main.get_service; build_chatbot; archive.healthcheck.

**Affected end-to-end flow:** TR-HEALTH-1.

**Trigger conditions:**
- Worker starts cold
- Health probe arrives before initialization
- Mongo/cache/model configuration is unavailable

**Observed or projected impact:** Liveness and readiness are conflated; probes can cause side effects, slow startup, or restart loops when optional/degraded dependencies fail.

**Existing controls:**
- Failures return bounded 503 without exception details
- Health is intentionally unauthenticated for platform use

**Verification:** Import in a sanitized findings-local copy with warm-up disabled and instrument constructors; do not contact external services.

## Evidence and Validation Limitations

- No live model, staging HTTP endpoint, package registry, advisory service, or Mongo replica set was contacted.
- External provider behavior, retention, regional controls, production TLS/WAF/headers, backups, monitoring, and Mongo deployment semantics require external validation.
- The 42 timed-out hardening tests have no native per-test result; they remain environment failures, not assumed product failures or passes.
- Property 5 was interrupted once with ^C and exit code 1 without summary/counterexample and was not rerun.
- Property 4's exact-case validator failure remains unresolved and forces fail-closed readiness.
- Metadata/structure review intentionally did not reproduce live secrets, user records, or database contents.
- Property 9 remaining validation is a test-defect result: AssertionError: valid({'conclusion': 'conditionally-ready', 'integrity_ok': True, 'p0': [], 'p1': ['P1-5'], ...}) returned False at test_property_9.py:54 because the generated conditionally-ready record had no pre-production condition.

## Readiness Decision

**NOT READY.** Reconsideration requires closure of every P0/P1 issue and all preserved test/validation blocker classes, plus the evidence listed in `solution.md`. Final effective readiness remains fail-closed if G8 detects any protected mismatch, unauthorized output, dangling reference, coverage failure, or redaction failure.
