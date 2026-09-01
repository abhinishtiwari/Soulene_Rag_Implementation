# Soulene RAG Audit — Remediation Plan

**Run:** `audit-20260827T102557885287Z-073047a3`  
**Current decision:** **NOT READY**. Repository remediation is in progress; implemented solutions and verification are recorded below. External production controls and qualified safety review remain separate acceptance requirements.

## Implemented Solutions

### SOLUTION-008 → ISSUE-008 — IMPLEMENTED AND VERIFIED

The outgoing-response boundary now has two independent layers. A local deterministic policy wall blocks diagnosis certainty, medication dosing, delusion reinforcement, dependency/coercion, treatment certainty, and shame/degradation even when no model reviewer is available. When semantic review is enabled, missing methods, exceptions, malformed JSON, empty results, and unknown categories produce a fail-closed `review_unavailable` state and a bounded multilingual safety response. The optional editing pass is enabled by default and in the production manifest, but all of its output is still revalidated.

Verification retained in `tests/test_reasoning_safety.py` covers six harmful category examples, four safe counterexamples, exception failure, malformed/empty/unknown reviewer results, and end-to-end archive equality. Targeted and related regression runs passed (116 tests plus 13 subtests), compilation passed, and the original four-input reproduction now blocks every draft. Remaining acceptance is qualified human review of safety wording/calibration and production-equivalent provider observation; these are not represented as automated clinical approval.

### SOLUTION-022 → ISSUE-022 — IMPLEMENTED AND VERIFIED

Production authentication is now an explicit runtime invariant. `REQUIRE_API_AUTH=true` makes settings validation require separate, non-empty, distinct client and administrator keys, and `main.py` performs that validation during import before the process can serve requests. `ApiAuth.check_admin` no longer grants administrator access through the ordinary client key. Render enables the invariant; local development remains explicit with the switch disabled by default.

Verification covers missing client credentials, missing administrator credentials, equal credentials, valid distinct credentials, client-only document-write rejection, Flask endpoint behavior, and actual subprocess imports under invalid and valid production environments. The auth-focused run passed 15 tests plus 3 subtests; related API/security regression passed 98 tests plus 3 subtests; compilation passed. Operational credential generation, storage, rotation, and live-edge validation remain production acceptance work.

### SOLUTION-001 → ISSUE-001 — IMPLEMENTED AND VERIFIED

Oversized messages are now rejected before analysis instead of truncated. `exceeds_message_limit` detects the condition, `oversized_message_reply` returns a bounded multilingual notice stating that nothing was processed, `ChatbotService.handle` refuses before any safety assessment, generation, cache mutation or commit, and both chat routes reject at the edge with HTTP 413 plus the limit. `clean_message` retains its cheap cap solely to bound CPU for already-accepted input.

Verification: the pre-fix reproduction showed a crisis suffix silently dropped at the 4,000-character boundary; after the fix the message is refused whole, nothing is archived and no context is cached. Targeted run 6 passed, related HTTP/hardening run 68 passed plus 2 subtests, full suite 301 passed plus 18 subtests, compilation passed. The chosen policy is disclosed refusal rather than segmentation; clinical suitability of the refusal wording remains a qualified-reviewer gate.

### SOLUTION-002 → ISSUE-002 — IMPLEMENTED AND VERIFIED

Derived safety state is now staged and committed or rolled back with the authoritative turn, and absent contexts are explicitly reset during rehydration. `ContextCache` gained `derived_snapshot`, `restore_derived` and `reset_derived`; `handle` restores the snapshot if any step through `_record_turn` raises; `_ensure_context_loaded` clears derived state when the archive has none.

Verification: the pre-fix reproduction left crisis-level `safety_state` behind with zero archived turns; post-fix it is empty. Three targeted tests passed (rollback, retry-vs-fresh parity, rehydration reset) and the full suite passed 304 tests plus 18 subtests. Cross-worker retry parity remains covered by ISSUE-034 rather than this fix.

### SOLUTION-003 → ISSUE-003 — IMPLEMENTED AND VERIFIED

Injection-classified requests now take a deterministic no-model path. `RefusalHandler` gained a language-matched injection refusal and `_respond` returns it immediately after the crisis check, so no history, cross-session text, summary, memory or knowledge is assembled and no provider call occurs. Context minimization is therefore enforced in code rather than by prompt instructions.

Verification: the pre-fix reproduction sent one model call containing the user's therapist name and city; post-fix zero model calls occur for the same input. Nine targeted injection tests pass, including crisis-outranks-injection and repeated-attempt boundary tests, and the full suite passed 305 tests plus 18 subtests. Residual risk is classifier evasion, tracked under ISSUE-015.

### SOLUTION-004 → ISSUE-004 — IMPLEMENTED AND VERIFIED

Document operations now use a staged protocol with compensating actions and exact-path deletion. `KnowledgeCache` records each document's `relative_path` and resolves it through `document_path`, which declines ambiguous legacy matches rather than guessing. Upload sets aside any previous version under an unindexed `.prev` name and, if ingest fails, restores the prior file and reconciles the index before returning an error that states the upload was rolled back. Deletion targets one exact file, removes it before the index entry, and reconciles by refresh if the index update fails.

Verification: three targeted tests cover rollback of a new upload, restoration of a replaced document's original content, and deletion sparing a same-named document in another folder. Full suite passed 308 tests plus 18 subtests. Stable document IDs remain partially deferred: identity is still basename-keyed in the index, which is closed separately by SOLUTION-012.

### SOLUTION-006 → ISSUE-006 — IMPLEMENTED AND VERIFIED (clinical sign-off still required)

Deterministic context handling now distinguishes negation, tense and subject before the crisis floor fires. `Guardrails.contextual_self_harm_only` defuses only tight, provable templates — negation directly governing an intent verb, `would never`, past-tense wording accompanied by an explicit past marker, and non-first-person attribution whose gap cannot cross a clause boundary — then re-runs plain, compact and immediate-danger detection on the defused text. If anything acute survives, or the message was flagged by moderation, or the wording is spaced/obfuscated, the conservative crisis route is kept. A defused disclosure steps down to `EMOTIONAL_DISTRESS`, not `SAFE`, so the user still receives attentive support.

Verification: 16 calibration cases pass, split between six that must step down and ten that must stay escalated. Development of the regression suite caught a genuine false negative in the first implementation (an attribution gap swallowing `... but I want to kill myself`), which was fixed by forbidding clause-boundary crossing. Full suite passed 311 tests plus 34 subtests. Calibration of the step-down target level and of the resulting wording remains a qualified mental-health reviewer gate.

### SOLUTION-007 → ISSUE-007 — IMPLEMENTED AND VERIFIED (clinical sign-off still required)

Classifier loss is now an explicit state with a deterministic replacement signal. `assess` separates success, disabled and attempted-but-unusable; the last sets `source="deterministic_degraded"`, `uncertainty≥0.6`, and a redacted warning carrying only the failure type and evidence counts. `_apply_trajectory_floor` supplies the missing multi-turn signal deterministically: accumulating finality/withdrawal markers plus per-turn deterministic distress escalate to `SELF_HARM_CONCERN` with `acute_now=False`, which selects the calm check-in path rather than the emergency script.

Verification: the pre-fix reproduction ended a farewell-letters/giving-away-possessions sequence at `SAFE` with `uncertainty=0.0`; post-fix the second marker triggers a check-in with the degraded state visible, a benign three-turn control stays `SAFE`, and malformed classifier output is also treated as degraded. Three targeted tests pass and the full suite passed 314 tests plus 34 subtests. Threshold and wording calibration remain a qualified mental-health reviewer gate; alerting on the emitted warning is operational (ISSUE-039).

### SOLUTION-009 → ISSUE-009 — IMPLEMENTED AND VERIFIED

Summaries are now handled as untrusted derived data. `ResponseBuilder.contains_unsafe_derived_text` reuses the existing leak, secret and therapeutic-harm walls, and `ChatbotService._validated_summary` adds prompt-injection screening plus a contradiction rule that refuses any summary claiming risk has resolved while the authoritative state is crisis-level. Rejected summaries are discarded and replaced by the deterministic excerpt of the user's own words, with a redacted warning. `summary_source` provenance was added to `ContextCache`, persisted with safety state and restored on rehydration.

Verification: the pre-fix reproduction stored an adversarial summary containing an injection directive, a false diagnosis and a dosing instruction; post-fix it is rejected and never enters a prompt. Three targeted tests pass; the full suite passed 317 tests plus 34 subtests. Testing exposed and fixed a provenance bug where rehydration reset model-derived summaries to `deterministic`. General factual-contradiction detection, retention/expiry (ISSUE-017) and user-facing correction remain out of scope.

### SOLUTION-010 → ISSUE-010 — IMPLEMENTED AND VERIFIED (locale verification remains external)

Emergency wording is now conditional on declared applicability. `EMERGENCY_LOCALE` plus `Settings.emergency_contact_is_verified` gate whether a number may be spoken, and `app/safety/emergency.py` resolves one reference shared by crisis steps, third-party guidance, the helpline reply and foreign-hotline rewriting. When the locale is unknown, all paths use neutral multilingual "local emergency services" wording. The verified-number registry is intentionally left to configuration and human review rather than hardcoded, and Render ships with the locale unset so production starts in the safe neutral mode.

Verification: 12 targeted tests cover both modes across the resolver, crisis steps, helpline reply and hotline rewriting; the full suite passed 321 tests plus 34 subtests. The pre-existing end-to-end helpline test was updated to assert the resolved reference, since the intended contract changed. Locale detection, a multi-locale directory and periodic resource re-verification remain external/manual acceptance gates.

### SOLUTION-011 → ISSUE-011 — IMPLEMENTED AND VERIFIED (clinical sign-off still required)

Relational boundaries are now enforceable rather than advisory. The deterministic output wall covers exclusivity, replacement of professional care, claimed superiority over real relationships, coercive commitments, false permanence and special-bond framing, while ordinary warmth is preserved. `Guardrails.expresses_dependency` supplies the multi-turn indicator, counted per conversation, and the escalation policy adds one warm nudge toward human/professional support on every third disclosure — on the disclosure turn only.

Verification: seven relational-harm replies are blocked and five benign supportive replies pass unchanged; dependency disclosures are detected without misreading ordinary loneliness; the boundary fires on the third disclosure and not on following ordinary turns (a repetition defect caught in testing). Four targeted tests with 20 subtests pass; full suite 325 tests plus 54 subtests. Wording, cadence and further escalation steps remain a qualified mental-health reviewer gate; multilingual paraphrase and cross-session trends are not covered.

### SOLUTION-012 → ISSUE-012 — IMPLEMENTED AND VERIFIED

Documents are now keyed by canonical relative path throughout `_scan`, `refresh`, `doc_hashes`, `doc_meta` and section metadata, so same-named files in different folders are distinct documents. `resolve_document` accepts a relative path or an unambiguous basename and returns `None` for a colliding basename, so lookup and deletion never guess; the delete route preserves the subdirectory while rejecting traversal components. Legacy v1 payloads are migrated in place with collision detection — unique basenames keep their preprocessed sections, colliding ones are dropped for reprocessing — rather than discarded.

Two additional defects were found and fixed while verifying: `refresh` reported "unchanged" whenever hashes matched even if the stored sections did not match recorded metadata, so a damaged cache could never self-heal; and an initial reject-on-version-mismatch approach destroyed preprocessed PDF content that cannot be regenerated where the optional `fitz` dependency is absent, which is why migration replaced rejection. Five targeted identity tests plus a self-healing test pass, migration retained all 181 real sections, and the full suite passed 330 tests plus 54 subtests. Three pre-existing tests were updated because document identity intentionally changed.

### SOLUTION-013 → ISSUE-013 — IMPLEMENTED AND VERIFIED

`build_context` now returns an explicit empty no-result on a lexical miss instead of substituting the first twenty cached sections. Because `CAGEngine.lookup` derives `knowledge_hit` from a non-empty context, the existing uncertainty path takes over automatically and the prompt instructs the model to say it does not have the detail rather than guess. Knowledge-type filtering is preserved on the narrowing path.

Verification: the reproduction injected 2,145 characters of unrelated sunflower/tractor content for a disjoint query; it now returns nothing, while a matching query still retrieves context and type filtering still constrains sources. Four targeted tests pass and the full suite passed 334 tests plus 54 subtests. Claim-level citations remain ISSUE-016.

### SOLUTION-014 → ISSUE-014 — IMPLEMENTED AND VERIFIED

Persistence now uses a unique `mkstemp` staging file per writer plus atomic `os.replace`, eliminating the shared `knowledge_cache.tmp` collision. A build-version check refuses to overwrite a cache whose `built_at` is newer, and `remove_document` bumps `built_at` so deletions remain authoritative. A transient Windows replace conflict is retried briefly and then yielded with a warning rather than failing a rebuild, since the cache is a rebuildable artifact and the in-memory index is already correct.

Verification: six concurrent writers doing 40 saves each went from 5 `PermissionError` failures to 0 across repeated runs, no staging files leak, and an older build cannot clobber a newer one. Three targeted tests pass and the full suite passed 337 tests plus 54 subtests. This is last-writer-wins with a freshness guard rather than a distributed lock; single-build election across workers remains part of SOLUTION-034.

### SOLUTION-015 → ISSUE-015 — IMPLEMENTED AND VERIFIED

External context now travels in structured channels with provenance tiers instead of prose labels. `untrusted_block` fences prior sessions, session summaries, stored memory, recent turns and knowledge documents, strips fence markers from content so data cannot escape its channel, and leaves the current user turn outside every fence. `Guardrails.scrub_instruction_like` removes instruction-like sentences and is applied as an ingestion policy in `KnowledgeCache.refresh` plus a retrieval policy on the small bounded blocks; instruction-like memory records and contradiction topics are dropped.

Verification: three injected payloads disappear from the assembled prompt while legitimate context is retained, tiers and fences are present, and forged boundaries are neutralised. Four targeted tests pass and the full suite passed 341 tests plus 54 subtests. Three follow-on defects were found and fixed during verification: coarse line-granularity filtering discarding legitimate text, a performance regression from per-request scanning of the whole knowledge corpus (moved to ingestion), and a throughput test that depended on the shared repository archive (now hermetic). Residual risk is paraphrased/multilingual instruction text, where the structural fence remains the only barrier; least-context assembly is only partially addressed.

### SOLUTION-017 → ISSUE-017 — MECHANISM IMPLEMENTED AND VERIFIED; WINDOWS AWAIT SIGN-OFF

Retention is now enforceable by data class. `app/storage/retention.py` defines `RetentionPolicy` (per-class windows, `0` = never expire) and `run_retention`, which purges each store independently and logs counts without record contents. All six stores across both backends implement `purge_expired` using existing timestamps, so no migration is needed. Summaries and inferred safety state are cleared in place on shorter clocks than the transcript, so derived inferences die before the words the user wrote. A transactional `claim_retention_run` ensures exactly one worker sweeps per interval; `main.py` triggers sweeps opportunistically behind a cheap timer and offers `python main.py --retention`. Minimization stops persisting free-text classifier observations about the user.

Verification: eight targeted tests cover per-class expiry with backdated records, derived-state-before-transcript ordering, memory/feedback windows, a disabled policy being inert, single-claim-per-interval, partial-failure isolation, evidence minimization, and the real `main.py` sweep path. Full suite passed 349 tests plus 54 subtests.

**The window values are proposals requiring sign-off**, at the same tier as the clinical wording gates: 365d conversation, 90d summary, 30d safety state, 180d memory, 730d feedback. Reasoning is recorded in `issue.md`. `RETENTION_ENABLED` ships `false`, so nothing is deleted until approved. Remaining gaps: no scheduler for idle deployments, no deletion-evidence ledger, no user-facing disclosure, and no coverage of backups/replicas (ISSUE-020/021).

### SOLUTION-018 → ISSUE-018 — IMPLEMENTED AND VERIFIED

Unattributed derived memory is now quarantined on session deletion rather than silently retained. `quarantined_at` lives on `UserMemory` as one shared definition; quarantined records are excluded from `retrieve` and `contradiction_topics` in the SQLite, Mongo and JSON stores, so they cannot reach a prompt. `forget_session` returns `{removed, quarantined, retained}` and `DELETE /sessions/<id>` surfaces it as `derived_memory`, making the outcome explicit and verifiable instead of implied.

Boundary reconciled with SOLUTION-017: "unattributed" means `sources == []` in both features. Retention deletes a memory when `updated_at < cutoff` **or** `quarantined_at > 0 and quarantined_at < cutoff`, using the same approved 180-day memory window, so no second policy or new value was introduced. Minimization is unaffected because it applies to persisted safety-state free text, not memory records.

Verification: 15 targeted tests including quarantine reporting, retrieval and contradiction exclusion, idempotent quarantine timestamps, retained cross-session reinforcement, account-deletion coverage, JSON-store parity, and an explicit test that the retention window expires quarantined records. Full suite passed 355 tests plus 54 subtests. Remaining gaps: no operator review queue for quarantined records and no auditable deletion ledger.

### SOLUTION-019 → ISSUE-019 — IMPLEMENTED AND VERIFIED

Account deletion is now a durable, checkpointed, idempotent workflow. A `deletion_jobs` table/collection records per-store step state; `delete_account` loads it, skips completed steps, runs archive → memory → feedback → caches independently, records each outcome, and returns a receipt. Partial failure returns 503 naming the pending steps with the identity still revoked, so retrying the idempotent endpoint converges. The job row outlives the user's data so the audit trail remains.

Boundary note: this fix **did not touch** the ISSUE-018 unattributed/quarantine boundary. Account deletion calls `forget_user`, which removes all memory unconditionally including quarantined records, so it never inspects `sources` or `quarantined_at`. No third definition was introduced.

Verification: four targeted tests cover step recording and resume, receipt completion, job survival across `delete_user`, and end-to-end convergence through the HTTP endpoint after an injected feedback-store failure. Full suite passed 360 tests plus 54 subtests. Remaining gaps: no background reconciler for abandoned jobs, no operator listing of incomplete jobs, and no coverage of backups/replicas (SOLUTION-020/021).

### SOLUTION-020 → ISSUE-020 — REPOSITORY-SIDE IMPLEMENTED AND VERIFIED; ENCRYPTION IS AN EXTERNAL GATE

**Repository-side (closed).** Added `app/storage/at_rest.py` with an explicit field classification for every stored table, owner-only permission hardening applied to each SQLite file and its WAL sidecars as they are created, and a `storage_posture` report that separates locally-verified facts from operator claims. `REQUIRE_ENCRYPTED_STORAGE` + `STORAGE_ENCRYPTION_ATTESTED` make production fail startup unless someone records that disk/database/backup encryption was verified. Posture is exposed on the authenticated `/metrics` endpoint, and `application_level_field_encryption: false` is reported explicitly so the absence is visible rather than assumed.

Application-level field encryption was deliberately **not** implemented: the archive projects message content in SQL (`substr(content, ...)` for titles/previews) and memory retrieval tokenises stored text, so encrypting those fields would break existing features while leaving keys in the same process as the data. No unwired crypto engine was added.

**External gate (not closed, needs:** actual volume/database/backup encryption enabled and independently verified; key custody, rotation and recovery procedures; confirmation that Mongo Atlas encryption-at-rest and backup encryption are active; and a decision on whether field-level encryption plus schema changes are warranted for `content`/`text`. Owner-only file modes are POSIX-only and were **not** verified on this Windows development host — that test skips there.**)

Verification: four targeted tests (one skipped on Windows) cover classification-vs-live-schema reconciliation across both databases, fail-closed attestation, posture reporting, and POSIX file modes; a subprocess check proves startup refuses an unattested production configuration and starts with one. Full suite passed 363 tests, 1 skipped, 61 subtests.

### SOLUTION-023 → ISSUE-023 — IMPLEMENTED AND VERIFIED (multiplier awaiting sign-off)

Identity issuance is now limited before it can create a quota. A separate `_anon_limiter` keyed on a coarse network signal charges every request that arrives without a usable identity, so discarding a cookie no longer mints a fresh allowance, while callers that retain their identity keep their per-principal limit untouched. The network key is used only for limiting and never stored.

Verification: the reproduction allowed 8/8 requests against a 3/min limit; post-fix, ten churning clients get 6 allowed and 4 blocked at a cap of 6, and a retained identity still hits its own limit of 2. Full suite passed 365 tests, 1 skipped, 61 subtests. New value `ANON_RATE_LIMIT_MULTIPLIER=5` is derived from the already-approved per-identity limit and awaits sign-off. Residual: per-process limiter (SOLUTION-034), distributed source addresses, and `X-Forwarded-For` trust at the edge (SOLUTION-039).

### SOLUTION-025 → ISSUE-025 — IMPLEMENTED AND VERIFIED (TTL and epoch awaiting sign-off)

Tokens are now time-bounded and revocable. Payload v2 carries `iat`, `exp` and a revocation epoch; `verify` enforces both with a clock-skew allowance. Sliding renewal re-issues a token past half its life so active users never expire, while abandoned tokens do. Legacy v1 tokens are honoured once and upgraded, so the change logs nobody out. Cookie age now matches token lifetime.

Verification: six targeted tests cover payload contents, expiry rejection under an advanced clock, epoch revocation, v1 acceptance plus upgrade, sliding renewal, and cookie age. Full suite passed 371 tests, 1 skipped, 61 subtests. New values `IDENTITY_TTL_DAYS=180` and `IDENTITY_EPOCH=1` await sign-off. Residual: epoch revocation is all-or-nothing and tokens remain bearer credentials until expiry.

### SOLUTION-028 → ISSUE-028 — REPOSITORY-SIDE IMPLEMENTED AND VERIFIED; PROVIDER CONTRACTS ARE AN EXTERNAL GATE

**Repository-side (closed).** A fail-closed disclosure attestation (`REQUIRE_PROVIDER_DISCLOSURE` / `PROVIDER_DISCLOSURE_ATTESTED`) validated at import; a user-facing notice in the UI stating that messages are processed by an external AI provider and that Soulene is not a crisis service; `SEND_CROSS_SESSION_CONTEXT`, an active minimization control tested in both states; and a content-free `TransmissionLedger` recording call purpose and sizes only, wired into `LLMClient.generate` and surfaced on authenticated `/metrics`. Five targeted tests pass; full suite 376 passed, 1 skipped, 63 subtests.

**External gate (not closed, needs:** written provider data-processing terms covering retention, training use and sub-processors; zero/limited-retention configuration enabled with evidence; data-residency and legal review for served jurisdictions; legal review of the notice wording and whether opt-in consent is required; and a decision on whether cross-session context should default off in production.**)

The ledger is process-local and in-memory by design — persisting it would create another sensitive store — so it is observability, not an audit record of record. Per-field PII redaction before transmission is not implemented.

### SOLUTION-029 → ISSUE-029 — IMPLEMENTED AND VERIFIED

`tests/conftest.py` establishes a mandatory sandbox before pytest imports any test module: read-only inputs are copied, `data/` is fresh, and `app.config.settings.PROJECT_ROOT` is rebound to the sandbox. An autouse fixture re-asserts containment on every test, so path escape fails loudly.

Verification: the reproduction grew the repository archive by 4,096 bytes from one test; after the fix the full suite (379 passed, 1 skipped, 63 subtests) leaves it byte-for-byte identical. Three targeted tests assert sandbox-relative paths and that the knowledge corpus is a populated copy. A separately documented flaky wall-clock assertion in `SpamAndLoadTests` was widened with reasoning; its cache-effectiveness invariant stays strict. Root-level scripts remain outside pytest discovery (SOLUTION-033).

### SOLUTION-031 → ISSUE-031 — IMPLEMENTED AND VERIFIED (matrix scope needs clinical review)

`tests/test_safety_matrix.py` enumerates four dimensions as named subtests: language form (10 must-escalate including obfuscation and two languages, 6 must-step-down), risk evolution (escalation, carried risk, ordinary distress), component failure (classifier error, malformed classifier output, reviewer error, generation error, and all-broken still routing crisis), and output harm (6 classes blocked, 4 supportive replies preserved). 13 tests, 26 subtests; full suite 392 passed, 1 skipped, 89 subtests.

A matrix proves enumerated cells, not completeness — the scenario list and the expected outcome per cell need qualified mental-health reviewer approval. Step-down logic is English-only, so non-English contextual disclosures stay conservatively escalated. No live-model behaviour is exercised.

### SOLUTION-034 → ISSUE-034 — IMPLEMENTED AND VERIFIED (single-worker semantics enforced)

Of the two options in the remediation, the second was taken: enforce compatible semantics rather than add a shared coordination backend. `render.yaml` and `Procfile` now declare `--workers 1 --threads 8`, which makes every process-local mechanism (turn locks, limiter buckets, context/response caches, knowledge-cache state) correct as designed while keeping equivalent concurrency for an I/O-bound workload. `tests/test_deployment.py` fails if the worker count is raised or the two entry points disagree, so the invariant is enforced rather than documented.

Verification: reproduction confirmed safety continuity already survived across workers via archive rehydration, while locks and caches did not. Four tests cover the manifest invariant, entry-point agreement, eight concurrent threads on one session producing 16 gapless sequence numbers, and six concurrent sessions staying isolated. Full suite 396 passed, 1 skipped, 89 subtests. Capacity of a single worker is unmeasured (SOLUTION-039), and horizontal scaling now requires shared coordination first.

### SOLUTION-035 → ISSUE-035 — IMPLEMENTED AND VERIFIED

Knowledge and cache locations are now configurable (`KNOWLEDGE_DIR`, `CACHE_DIR`) and Render places both inside the mounted disk. `PERSISTENT_ROOT` plus `Settings.validate_persistence` make startup fail if any writable path sits outside the declared mount, so the defect cannot silently return. `build_chatbot` uses `settings.cache_path` instead of a hardcoded sibling directory, and the misleading disk comment was corrected.

Verification: reproduction showed both paths outside the mount while the manifest claimed persistence. Four targeted tests cover rejection of outside paths, permitted local development with no mount, manifest agreement between `mountPath`/`PERSISTENT_ROOT`/`KNOWLEDGE_DIR`/`CACHE_DIR`, and the CAG engine honouring the configured cache path. Full suite 400 passed, 1 skipped, 89 subtests. Not covered: existing deployments need a one-time copy of current knowledge/cache into the mount, and disk sizing/exhaustion is SOLUTION-039.

### SOLUTION-039 → ISSUE-039 — REPOSITORY-SIDE IMPLEMENTED AND VERIFIED; MONITORING/RECOVERY IS AN EXTERNAL GATE

**Repository-side (closed).** `app/observability.py` adds an enforced daily provider-call budget (wired into `LLMClient.generate`, degrading to deterministic replies when exhausted), content-free operational counters incremented at real decision points, and disk free-space reporting — all surfaced on authenticated `/metrics`. `OPERATIONS.md` documents the watch list, incident procedures, backup/restore including a restore drill, deployment invariants and known gaps. 16 targeted tests; full suite 408 passed, 1 skipped, 89 subtests.

**External gate (not closed, needs:** alert routing from `/metrics` to a paging system; agreed SLOs and error budgets; automated backups plus a verified restore drill on real infrastructure; load testing to set the capacity envelope and choose `MODEL_DAILY_CALL_BUDGET`; named incident ownership; platform WAF/TLS/proxy review.**)

`OPERATIONS.md` is documentation, not automation, and states so. Counters and budget are in-process and reset on restart. New value `MODEL_DAILY_CALL_BUDGET` ships at `0` (unlimited) because too low a cap degrades every reply to a deterministic fallback — a safety-relevant downgrade — so it awaits sign-off.

### SOLUTION-005 → ISSUE-005 — IMPLEMENTED AND VERIFIED

`run_cli` refuses to start against shared production storage (`STORAGE_BACKEND=mongo`) or an authenticated deployment (`REQUIRE_API_AUTH=true`), naming each reason and exiting 2. `SOULENE_ALLOW_UNSAFE_CLI=1` makes the bypass an explicit choice. Three subprocess tests verify both refusals and the override; full suite 411 passed, 1 skipped, 89 subtests. It remains a refusal guard rather than authentication — an overridden session still has no identity or rate limiting.

### SOLUTION-016 → ISSUE-016 — IMPLEMENTED AND VERIFIED (claim-level citation remains a product gate)

`KnowledgeCache.source_provenance` returns document id, display name, content version and update time; `ChatbotService.handle` populates `ChatResult.retrieved` from the lookup instead of returning an empty list, and `/chat` exposes `grounded` plus `sources`. An ungrounded reply reports `grounded: false` with no sources, so a synthesised answer cannot be mistaken for a sourced one.

Verification: reproduction showed the engine knew its sources while the result and API exposed none. Five targeted tests cover provenance shape, version change on document edit, unknown-document handling, and both grounded and ungrounded API responses. Full suite 416 passed, 1 skipped, 89 subtests. Attribution is per reply, not per claim — enforcing claim-level citation from model output is a product decision and is not implemented.

### SOLUTION-021 → ISSUE-021 — REPOSITORY-SIDE IMPLEMENTED AND VERIFIED (backup/restore + migration harness are an external gate)

**Repository-side (closed).** `SCHEMA_VERSION` plus a `schema_version` table give a version of record, and `assert_schema_supported` refuses a database written by a newer release — the exact failure a rollback would hit silently. `find_orphans` / `reconcile_orphans` detect rows whose session parent is missing and restore the parent from the messages rather than deleting content, removing only unreplayable stale requests. Both run at startup and log only when a repair occurred. Five targeted tests (`tests/test_final_audit_remediation.py::SchemaAndIntegrityTests`); full suite 510 passed, 2 skipped, 612 subtests (count current as of the 2026-09-01 session, which added the load-resilience suite).

**External gate (not closed, needs:** automated backups with retention at least as long as the longest retention window; a verified restore drill on real infrastructure (procedure documented in `OPERATIONS.md`); a reversible migration harness — the version is recorded and guarded but no up/down scripts exist, as there is no second version yet; and equivalent version/reconciliation support for Mongo, which has neither.**)

### SOLUTION-024 → ISSUE-024 — IMPLEMENTED AND VERIFIED

`RateLimiter._evict` now ages *all* sampled buckets by their most recent hit instead of only removing already-empty ones, and a `_MAX_KEYS` ceiling drops least-recently-active keys so churn cannot grow the table without bound. Reproduction retained 12,000 stale buckets; post-fix 1 remains. Three targeted tests cover eviction, live-bucket survival, and the ceiling; full suite 424 passed, 1 skipped, 89 subtests. Still per-process and unbounded across workers only in the sense that each worker keeps its own table (ISSUE-034 fixes the topology to one worker).

### SOLUTION-027 → ISSUE-027 — IMPLEMENTED AND VERIFIED

An `after_request` hook sets a nonce-based CSP plus `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, and HSTS only over TLS. The policy uses neither `unsafe-inline` nor `unsafe-eval`: a fresh nonce is generated per request, injected into the template, and carried by both inline blocks, and the UI's one inline `onclick` was converted to an event listener so no relaxation is needed.

Verification: reproduction showed all six headers absent. Five targeted tests confirm the headers on both a UI and an API route, the absence of unsafe directives, that the page nonce matches the policy nonce on both blocks, that the nonce differs per request, and that no inline handler remains. Full suite 429 passed, 1 skipped, 91 subtests. Edge/platform headers still require deployment validation (SOLUTION-039).

### SOLUTION-030 → ISSUE-030 — IMPLEMENTED AND VERIFIED

The resilience test now patches `record_turn`, the boundary the runtime actually commits through, and asserts the injected failure was reached. It verifies that a failed authoritative commit raises rather than returning a fabricated reply, that nothing is persisted, that no derived safety state or cached context survives (the ISSUE-002 invariant), and that a retry after recovery succeeds and stores exactly one turn. Five targeted tests pass; full suite 430 passed, 1 skipped, 91 subtests.

Correcting the test also corrected its claim: the old test asserted graceful degradation, but the intended behaviour is a surfaced 503 — the HTTP layer converts the exception, so a user is never told a message was saved when it was not.

### SOLUTION-032 → ISSUE-032 — REPOSITORY-SIDE IMPLEMENTED AND VERIFIED; LIVE VALIDATION IS AN EXTERNAL GATE

**Repository-side (closed).** `tests/test_provider_contract.py` pins provider response-shape handling offline (text stripping, `None` output, error mapping, required fields with `store=False`, budget vs provider error, moderation parsing, moderation failing open) plus backend interface parity across all archive and memory methods for both SQLite and Mongo. 9 tests, 38 subtests; full suite 439 passed, 1 skipped, 129 subtests. A wrong expectation of mine was corrected in the test, not the code: `moderate` fails open by design because the deterministic floor stays authoritative.

**External gate (not closed, needs:** a disposable network-isolated Mongo replica set in CI with a destructive-operation allowlist; a staging environment and credentials for the staging smoke; a token budget for the live smoke; and re-verification that real provider response shapes still match the fakes whenever the provider API changes.**)

The three live suites remain excluded and unrun and were not modified. Contract tests prove Soulene handles a shape correctly, never that the provider still emits it.

### SOLUTION-036 → ISSUE-036 — IMPLEMENTED AND VERIFIED

`main.shutdown_resources` closes the SQLite feedback connection and the shared MongoClient, is idempotent, isolates failures so one broken close cannot skip the rest, and is registered with `atexit` so it runs on normal exit and Gunicorn worker termination. Four targeted tests cover single-close, idempotency, mongo reset when never connected, and failure isolation; full suite 443 passed, 1 skipped, 129 subtests. `atexit` does not run on `SIGKILL`, and connection ownership is still module-global rather than injected.

### SOLUTION-037 → ISSUE-037 — REPOSITORY-SIDE IMPLEMENTED AND VERIFIED; HASH LOCKING IS AN EXTERNAL GATE

**Repository-side (closed).** Enforced tests require exact `==` pinning for every direct dependency, forbid URL/VCS/local sources, and forbid an opportunistic `pip install --upgrade pip` in the build. That last test failed against the real manifest and the build command now pins `pip==25.0`. The lock-generation procedure is documented in `OPERATIONS.md`, and a test asserts any committed lock file carries `--hash=sha256:` entries. 3 tests plus 18 subtests; full suite 446 passed, 2 skipped, 147 subtests.

**External gate (not closed, needs:** generate, review and commit a hash-locked transitive lock and add `--require-hashes` to the build (requires index access and human review); an SBOM and vulnerability review; a trusted index/mirror policy; artifact provenance for the native-wheel dependencies.**)

No placeholder lock file was created — the lock test skips with a message pointing at this gate rather than asserting about a file that does not exist. Fabricating hashes offline would be worse than having none.

### SOLUTION-026 → ISSUE-026 — CONTAINMENT IMPLEMENTED; DURABLE HISTORY REMEDIATION DEFERRED AND ACCEPTED

The containment half of this remediation is implemented and verified: `data/chat_archive.sqlite3` and its `-wal`/`-shm` sidecars are untracked, `data/` stays ignored, the working database is intact, and a metadata-only regression test prevents silent re-tracking. That test found two additional indexed sidecar files that the original finding did not enumerate. No database contents were read.

The durable half — purge history safely, verify all clones/backups, rotate affected identifiers, and notify as required — was **explicitly not performed in this session**. It is recorded as an accepted Critical limitation and an external/manual acceptance gate requiring repository-owner authorization, coordinated force-updates across all refs and tags including `v1`, clone/backup invalidation, and exposure assessment. Readiness must continue to treat `ISSUE-026` as unresolved until that authorized work is completed and evidenced.

## One-to-One Mapping Contract

Exactly forty remediation records follow. `SOLUTION-NNN` maps only to `ISSUE-NNN`; every issue has exactly one solution and no solution is dangling or systemic/unmapped.

## Phased Roadmap and Dependency Gates

1. **Release blockers (P0):** SOLUTION-008, SOLUTION-022, SOLUTION-026. Contain exposure immediately; do not release.
2. **Pre-production controls (P1):** SOLUTION-001, SOLUTION-002, SOLUTION-003, SOLUTION-004, SOLUTION-006, SOLUTION-007, SOLUTION-009, SOLUTION-010, SOLUTION-011, SOLUTION-012, SOLUTION-013, SOLUTION-014, SOLUTION-015, SOLUTION-017, SOLUTION-018, SOLUTION-019, SOLUTION-020, SOLUTION-023, SOLUTION-025, SOLUTION-028, SOLUTION-029, SOLUTION-031, SOLUTION-034, SOLUTION-035, SOLUTION-039. Complete after P0 containment and before readiness reconsideration.
3. **Planned hardening (P2):** SOLUTION-005, SOLUTION-016, SOLUTION-021, SOLUTION-024, SOLUTION-027, SOLUTION-030, SOLUTION-032, SOLUTION-036, SOLUTION-037, SOLUTION-038, SOLUTION-040. Schedule after core safety/security/data gates while preserving compatibility and migration evidence.
4. **Backlog improvement (P3):** SOLUTION-033. Complete with test-governance modernization.

Cross-cutting order: exposure containment → identity/safety boundary → data lifecycle and storage consistency → distributed state and deployment paths → hermetic regression evidence → external validation → staged production acceptance. Property 4 and Property 5 require conclusive follow-up in a separately authorized validation run; this report does not overwrite their recorded outcomes.

## Acceptance Gates for Readiness Reconsideration

- Issue-specific automated and manual acceptance evidence for every P0/P1 remediation.
- Passing exact-case allowlist and ledger-order property results with retained output.
- Passing or explicitly adjudicated native results for the 48 repository-test blockers.
- External validation records for production identity, encryption, provider privacy, emergency resources, network edge, Mongo, monitoring, backup, and restore controls.

## Detailed Remediations
## P0 — Immediate Release Blockers

### SOLUTION-008 → ISSUE-008 — Model-output safety fails open and omits major therapeutic harm classes

**Priority / dependency gate:** P0 / `release-blocker`.

**Immediate containment:** Enable the output reviewer, restrict generative mental-health responses to reviewed categories, and replace uncertain output with a bounded safe response.

**Durable remediation:** Add deterministic category-specific blockers plus a bounded fail-closed reviewer path; require adversarial regression evidence before production.

**Intended outcome:** Remove the control gap for model-output safety fails open and omits major therapeutic harm classes while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** ResponseBuilder.apply_output_safety; ResponseBuilder._semantic_output_category; render.yaml.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-008 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Use synthetic harmful replies for each omitted category with the reviewer disabled and with a reviewer that raises; inspect the final response in an isolated harness.
- Add a regression test linked to ISSUE-008 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-OUT-1, TR-DEPLOY-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Mental-health recommendations:**
- Test explicit and contextual single-turn language with calibrated urgency.
- Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.
- Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.
- Test model empty/adversarial/failure output through final response control.
- Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-022 → ISSUE-022 — Production can start with API and admin authentication disabled

**Priority / dependency gate:** P0 / `release-blocker`.

**Immediate containment:** Refuse public/production startup when either user API or separate administrator authorization is absent.

**Durable remediation:** Define production mode that refuses startup unless separate API/admin credentials or stronger identity-aware authorization are configured and rotated.

**Intended outcome:** Remove the control gap for production can start with api and admin authentication disabled while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** ApiAuth; main._guard_request; document routes; render.yaml.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-022 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Start an isolated configuration with empty synthetic keys and inspect guard outcomes; do not bind a live server.
- Add a regression test linked to ISSUE-022 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-HTTP-1, TR-DOC-1, TR-DEPLOY-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Security/privacy owner reviews threat model, sensitive-data lifecycle, access, and incident implications.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Security/privacy recommendations:**
- Prevention: enforce least privilege, least context, and server-side authorization/data minimization.
- Detection: add redacted correlated telemetry and anomaly/integrity alerts.
- Response: document containment, investigation, notification, and recovery ownership.
- Data lifecycle: define collection purpose, retention, deletion proof, backup, and migration handling.
- Secret rotation: rotate affected credentials/keys when applicable; otherwise record a reviewed not-applicable rationale.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-026 → ISSUE-026 — A conversation archive database is tracked in Git

**Priority / dependency gate:** P0 / `release-blocker`.

**Immediate containment:** Immediately restrict repository and clone access, stop tracking the runtime database, preserve incident evidence, and begin exposure assessment without opening records unnecessarily.

**Durable remediation:** Immediately restrict repository access and stop tracking runtime data; assess exposure, purge history safely, rotate affected secrets/identifiers, notify as required, and verify all clones/backups.

**Intended outcome:** Remove the control gap for a conversation archive database is tracked in git while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** data/chat_archive.sqlite3; .git/index/history; ChatArchive.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-026 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Run read-only Git tracked-file metadata inspection; do not open the database or print content.
- Add a regression test linked to ISSUE-026 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-COMMIT-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.
- Security/privacy owner reviews threat model, sensitive-data lifecycle, access, and incident implications.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Mental-health recommendations:**
- Test explicit and contextual single-turn language with calibrated urgency.
- Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.
- Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.
- Test model empty/adversarial/failure output through final response control.
- Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.

**Security/privacy recommendations:**
- Prevention: enforce least privilege, least context, and server-side authorization/data minimization.
- Detection: add redacted correlated telemetry and anomaly/integrity alerts.
- Response: document containment, investigation, notification, and recovery ownership.
- Data lifecycle: define collection purpose, retention, deletion proof, backup, and migration handling.
- Secret rotation: rotate affected credentials/keys when applicable; otherwise record a reviewed not-applicable rationale.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

## P1 — Required Before Production

### SOLUTION-001 → ISSUE-001 — Silent message truncation can remove safety-critical suffixes

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Reject messages above the supported bound before analysis and tell the user that no content was processed.

**Durable remediation:** Reject oversized messages with a bounded user-visible response or apply a safety-aware, disclosed segmentation policy before analysis.

**Intended outcome:** Remove the control gap for silent message truncation can remove safety-critical suffixes while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** app/utils.py::clean_message; ChatbotService.handle; HTTP chat routes.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-001 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Call clean_message with a synthetic string longer than 4,000 characters and place a distinct marker after the boundary; compare the returned value.
- Add a regression test linked to ISSUE-001 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-CHAT-2, TR-SAFE-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Mental-health recommendations:**
- Test explicit and contextual single-turn language with calibrated urgency.
- Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.
- Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.
- Test model empty/adversarial/failure output through final response control.
- Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-002 → ISSUE-002 — Failed first-turn commits can leave process-local safety mutations

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Route retries for failed first-turn commits to a fresh service context and monitor archive failures until state rollback is proven.

**Durable remediation:** Stage safety-state changes and commit or rollback them with the authoritative turn; explicitly reset absent contexts during rehydration.

**Intended outcome:** Remove the control gap for failed first-turn commits can leave process-local safety mutations while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** ChatbotService.handle; ConversationRiskReasoner; Analyzer; ChatbotService._ensure_context_loaded.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-002 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- In an isolated copy, inject an archive failure on a new context after analysis, retry on the same service instance, and compare local risk/counter state with a fresh instance.
- Add a regression test linked to ISSUE-002 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-SAFE-1, TR-COMMIT-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Mental-health recommendations:**
- Test explicit and contextual single-turn language with calibrated urgency.
- Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.
- Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.
- Test model empty/adversarial/failure output through final response control.
- Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-003 → ISSUE-003 — Prompt-injection intent still reaches the model with privileged context

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** For injection-classified requests, suppress stored/retrieved context and avoid a model call unless a least-context policy explicitly permits it.

**Durable remediation:** Introduce a deterministic injection response or a least-context generation path and enforce context-specific authorization outside prompts.

**Intended outcome:** Remove the control gap for prompt-injection intent still reaches the model with privileged context while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** ChatbotService._respond; ChatbotService._build_prompt; system_prompt.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-003 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Use a synthetic injection message with instrumented fake model input in a findings-local copy and inspect whether contextual sections are still present.
- Add a regression test linked to ISSUE-003 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-ROUTE-1, TR-PROMPT-1, TR-OUT-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Security/privacy owner reviews threat model, sensitive-data lifecycle, access, and incident implications.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Security/privacy recommendations:**
- Prevention: enforce least privilege, least context, and server-side authorization/data minimization.
- Detection: add redacted correlated telemetry and anomaly/integrity alerts.
- Response: document containment, investigation, notification, and recovery ownership.
- Data lifecycle: define collection purpose, retention, deletion proof, backup, and migration handling.
- Secret rotation: rotate affected credentials/keys when applicable; otherwise record a reviewed not-applicable rationale.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-004 → ISSUE-004 — Document upload and deletion are not atomic across file and index state

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Suspend duplicate-basename document operations and require operator reconciliation after any refresh or unlink failure.

**Durable remediation:** Use stable document IDs and a staged transaction protocol with compensating actions, idempotent recovery, and exact-path deletion.

**Intended outcome:** Remove the control gap for document upload and deletion are not atomic across file and index state while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** main.py::upload_document; main.py::delete_document; KnowledgeCache.refresh; KnowledgeCache.remove_document.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-004 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- In an isolated synthetic knowledge tree, create duplicate basenames and inject refresh/unlink failures while comparing filesystem and index state.
- Add a regression test linked to ISSUE-004 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-DOC-1, TR-DOC-2

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-006 → ISSUE-006 — Deterministic crisis floor over-escalates negated, quoted, and historical language

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Use a calm clarification response for negated, quoted, historical, or third-party forms instead of automatically asserting imminent self-risk.

**Durable remediation:** Add deterministic context handling for negation, quotation, tense, and subject; require calibrated follow-up when context is ambiguous.

**Intended outcome:** Remove the control gap for deterministic crisis floor over-escalates negated, quoted, and historical language while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** Guardrails.decide; Guardrails.assess_safety_level; ConversationRiskReasoner.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-006 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Evaluate synthetic examples such as a present denial, a quotation, a past-tense statement, and a third-party report through Guardrails in isolation.
- Add a regression test linked to ISSUE-006 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-SAFE-1, TR-ROUTE-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Mental-health recommendations:**
- Test explicit and contextual single-turn language with calibrated urgency.
- Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.
- Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.
- Test model empty/adversarial/failure output through final response control.
- Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-007 → ISSUE-007 — Ambiguous and evolving risk can fall back to a context-poor deterministic floor

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** On semantic-classifier failure, select a conservative safety check-in and emit a redacted operational alert.

**Durable remediation:** Implement a deterministic trajectory floor and explicit uncertainty state that selects a safe check-in/escalation response on classifier failure.

**Intended outcome:** Remove the control gap for ambiguous and evolving risk can fall back to a context-poor deterministic floor while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** ConversationRiskReasoner.assess; Guardrails; ChatbotService._analyze.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-007 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- With a fake semantic client that raises or returns malformed data, evaluate a synthetic sequence whose risk is only apparent cumulatively.
- Add a regression test linked to ISSUE-007 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-SAFE-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Mental-health recommendations:**
- Test explicit and contextual single-turn language with calibrated urgency.
- Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.
- Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.
- Test model empty/adversarial/failure output through final response control.
- Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-009 → ISSUE-009 — Rolling model summaries are persisted and reused without output safety validation

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Stop reusing newly generated summaries for safety-relevant context until they pass validation; fall back to authoritative recent turns.

**Durable remediation:** Treat summaries as untrusted derived data with validation, provenance, contradiction detection, expiry, and user-correction support.

**Intended outcome:** Remove the control gap for rolling model summaries are persisted and reused without output safety validation while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** ChatbotService._refresh_summary; ContextCache; ChatbotService._build_prompt.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-009 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Instrument the fake model to return an unsafe or contradictory synthetic summary, then inspect stored summary and a later built prompt.
- Add a regression test linked to ISSUE-009 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-DERIVED-1, TR-PROMPT-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.
- Security/privacy owner reviews threat model, sensitive-data lifecycle, access, and incident implications.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Mental-health recommendations:**
- Test explicit and contextual single-turn language with calibrated urgency.
- Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.
- Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.
- Test model empty/adversarial/failure output through final response control.
- Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.

**Security/privacy recommendations:**
- Prevention: enforce least privilege, least context, and server-side authorization/data minimization.
- Detection: add redacted correlated telemetry and anomaly/integrity alerts.
- Response: document containment, investigation, notification, and recovery ownership.
- Data lifecycle: define collection purpose, retention, deletion proof, backup, and migration handling.
- Secret rotation: rotate affected credentials/keys when applicable; otherwise record a reviewed not-applicable rationale.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-010 → ISSUE-010 — Emergency resource selection assumes one configured number without locale validation

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** When locale is unknown, use neutral local-emergency-services wording and require human review of configured resources.

**Durable remediation:** Use locale-aware verified resources when available and neutral 'local emergency services' wording plus regular human review when locale is unknown.

**Intended outcome:** Remove the control gap for emergency resource selection assumes one configured number without locale validation while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** CrisisHandler; ResponseBuilder.enforce_helpline_number; render.yaml.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-010 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Static configuration review; live dialing or external resource validation is prohibited.
- Add a regression test linked to ISSUE-010 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-ROUTE-1, TR-OUT-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Mental-health recommendations:**
- Test explicit and contextual single-turn language with calibrated urgency.
- Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.
- Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.
- Test model empty/adversarial/failure output through final response control.
- Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-011 → ISSUE-011 — Vulnerable-user dependency and false-authority risks lack deterministic boundaries

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Add reviewed response blocks for exclusivity, dependency, coercion, diagnosis, and replacement-of-care language before broad release.

**Durable remediation:** Define enforceable relational-boundary rules, multi-turn dependency indicators, escalation policy, and reviewed adversarial tests.

**Intended outcome:** Remove the control gap for vulnerable-user dependency and false-authority risks lack deterministic boundaries while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** system_prompt; ResponseBuilder; ChatbotService.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-011 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- A future-risk conclusion from static control coverage; live model behavior was not invoked.
- Add a regression test linked to ISSUE-011 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-PROMPT-1, TR-OUT-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.
- Security/privacy owner reviews threat model, sensitive-data lifecycle, access, and incident implications.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Mental-health recommendations:**
- Test explicit and contextual single-turn language with calibrated urgency.
- Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.
- Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.
- Test model empty/adversarial/failure output through final response control.
- Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.

**Security/privacy recommendations:**
- Prevention: enforce least privilege, least context, and server-side authorization/data minimization.
- Detection: add redacted correlated telemetry and anomaly/integrity alerts.
- Response: document containment, investigation, notification, and recovery ownership.
- Data lifecycle: define collection purpose, retention, deletion proof, backup, and migration handling.
- Secret rotation: rotate affected credentials/keys when applicable; otherwise record a reviewed not-applicable rationale.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-012 → ISSUE-012 — Knowledge documents collide by basename

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Disallow same-basename uploads across directories and inventory existing collisions before further indexing.

**Durable remediation:** Key documents by canonical relative path or immutable document ID and migrate existing cache metadata with collision detection.

**Intended outcome:** Remove the control gap for knowledge documents collide by basename while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** KnowledgeCache._scan; KnowledgeCache.refresh; document APIs.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-012 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Create two synthetic same-named files under separate sandbox subdirectories and compare scan/document results.
- Add a regression test linked to ISSUE-012 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-DOC-1, TR-DOC-2

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-013 → ISSUE-013 — Lexical retrieval miss injects arbitrary leading sections

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Return an explicit no-knowledge result on lexical miss and require uncertainty language rather than arbitrary fallback sections.

**Durable remediation:** Return an explicit no-result state, preserve knowledge type, and require uncertainty/citation behavior when support is absent.

**Intended outcome:** Remove the control gap for lexical retrieval miss injects arbitrary leading sections while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** KnowledgeCache.search_sections; KnowledgeCache.build_context; ChatbotService._lookup.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-013 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Build a synthetic cache with unrelated sections and query with disjoint tokens; inspect constructed context.
- Add a regression test linked to ISSUE-013 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-ROUTE-1, TR-PROMPT-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Mental-health recommendations:**
- Test explicit and contextual single-turn language with calibrated urgency.
- Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.
- Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.
- Test model empty/adversarial/failure output through final response control.
- Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-014 → ISSUE-014 — Knowledge cache persistence uses a shared fixed temporary filename

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Serialize cache writes to one worker or disable shared file writes until inter-process coordination is available.

**Durable remediation:** Use unique temporary files plus an inter-process lock/version check, or move shared cache state to a concurrency-safe store.

**Intended outcome:** Remove the control gap for knowledge cache persistence uses a shared fixed temporary filename while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** KnowledgeCache.save; KnowledgeCache.refresh.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-014 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- In an isolated copy only, coordinate two processes writing distinct synthetic cache states and compare outcomes.
- Add a regression test linked to ISSUE-014 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-DOC-2, TR-DEPLOY-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-015 → ISSUE-015 — Memory and retrieved text are only prompt-labeled as untrusted

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Exclude instruction-like memory and knowledge from prompts and minimize cross-session context pending structural containment.

**Durable remediation:** Apply ingestion and retrieval safety policies, structured data channels, provenance/trust tiers, and least-context assembly.

**Intended outcome:** Remove the control gap for memory and retrieved text are only prompt-labeled as untrusted while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** ChatbotService._cross_session_context; ChatbotService._build_prompt; system_prompt.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-015 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Store synthetic instruction-like memory/knowledge in a sandbox and inspect the generated prompt and fake-model behavior.
- Add a regression test linked to ISSUE-015 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-PROMPT-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.
- Security/privacy owner reviews threat model, sensitive-data lifecycle, access, and incident implications.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Mental-health recommendations:**
- Test explicit and contextual single-turn language with calibrated urgency.
- Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.
- Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.
- Test model empty/adversarial/failure output through final response control.
- Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.

**Security/privacy recommendations:**
- Prevention: enforce least privilege, least context, and server-side authorization/data minimization.
- Detection: add redacted correlated telemetry and anomaly/integrity alerts.
- Response: document containment, investigation, notification, and recovery ownership.
- Data lifecycle: define collection purpose, retention, deletion proof, backup, and migration handling.
- Secret rotation: rotate affected credentials/keys when applicable; otherwise record a reviewed not-applicable rationale.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-017 → ISSUE-017 — Sensitive conversation and inferred-state records have no retention or expiry policy

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Freeze unnecessary derived-data collection and publish interim deletion/retention handling for existing sensitive records.

**Durable remediation:** Define retention by data class, implement enforceable expiry and deletion proofs, and minimize derived health attributes.

**Intended outcome:** Remove the control gap for sensitive conversation and inferred-state records have no retention or expiry policy while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** ChatArchive; ChatArchiveMongo; LongTermMemory; ContextCache summaries; FeedbackStore.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-017 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Create synthetic records with old timestamps in isolated backends and inspect whether normal lifecycle operations expire them.
- Add a regression test linked to ISSUE-017 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-COMMIT-1, TR-DERIVED-1, TR-DEL-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.
- Security/privacy owner reviews threat model, sensitive-data lifecycle, access, and incident implications.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Mental-health recommendations:**
- Test explicit and contextual single-turn language with calibrated urgency.
- Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.
- Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.
- Test model empty/adversarial/failure output through final response control.
- Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.

**Security/privacy recommendations:**
- Prevention: enforce least privilege, least context, and server-side authorization/data minimization.
- Detection: add redacted correlated telemetry and anomaly/integrity alerts.
- Response: document containment, investigation, notification, and recovery ownership.
- Data lifecycle: define collection purpose, retention, deletion proof, backup, and migration handling.
- Secret rotation: rotate affected credentials/keys when applicable; otherwise record a reviewed not-applicable rationale.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-018 → ISSUE-018 — Session deletion can leave legacy or unattributed memory

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Disclose incomplete session-deletion semantics and route legacy/unattributed records to a quarantine review queue.

**Durable remediation:** Migrate provenance, quarantine ambiguous legacy records, and make deletion outcomes explicit and verifiable to the user.

**Intended outcome:** Remove the control gap for session deletion can leave legacy or unattributed memory while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** main.py::delete_session; LongTermMemory provenance; archive deletion.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-018 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- In an isolated store, create synthetic legacy/unattributed memory, delete its source session, and query remaining memory.
- Add a regression test linked to ISSUE-018 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-DEL-1, TR-DERIVED-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Security/privacy owner reviews threat model, sensitive-data lifecycle, access, and incident implications.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Security/privacy recommendations:**
- Prevention: enforce least privilege, least context, and server-side authorization/data minimization.
- Detection: add redacted correlated telemetry and anomaly/integrity alerts.
- Response: document containment, investigation, notification, and recovery ownership.
- Data lifecycle: define collection purpose, retention, deletion proof, backup, and migration handling.
- Secret rotation: rotate affected credentials/keys when applicable; otherwise record a reviewed not-applicable rationale.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-019 → ISSUE-019 — Account deletion is a multi-store saga without complete atomic rollback

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Track every account-deletion step operationally and do not claim completion until all stores are verified empty.

**Durable remediation:** Implement a durable idempotent deletion workflow with per-store checkpoints, retries, observability, and a verifiable completion receipt.

**Intended outcome:** Remove the control gap for account deletion is a multi-store saga without complete atomic rollback while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** main.py::delete_account; ChatArchive.delete_user; memory/profile deletion; FeedbackStore.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-019 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Inject synthetic failures at each deletion step in isolated storage and verify durable job state, retry convergence, and residual records.
- Add a regression test linked to ISSUE-019 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-DEL-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Security/privacy owner reviews threat model, sensitive-data lifecycle, access, and incident implications.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Security/privacy recommendations:**
- Prevention: enforce least privilege, least context, and server-side authorization/data minimization.
- Detection: add redacted correlated telemetry and anomaly/integrity alerts.
- Response: document containment, investigation, notification, and recovery ownership.
- Data lifecycle: define collection purpose, retention, deletion proof, backup, and migration handling.
- Secret rotation: rotate affected credentials/keys when applicable; otherwise record a reviewed not-applicable rationale.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-020 → ISSUE-020 — Stored sensitive data lacks application-level encryption

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Restrict storage/operator access and independently verify volume, database, and backup encryption before production use.

**Durable remediation:** Classify sensitive fields, verify infrastructure encryption, add field-level protection where warranted, and establish key rotation/recovery procedures.

**Intended outcome:** Remove the control gap for stored sensitive data lacks application-level encryption while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** SQLite/Mongo archives; feedback stores; memory/profile stores; data directory.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-020 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Static schema/configuration review only; protected database contents were not opened or reproduced.
- Add a regression test linked to ISSUE-020 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-COMMIT-1, TR-DERIVED-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.
- Security/privacy owner reviews threat model, sensitive-data lifecycle, access, and incident implications.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Mental-health recommendations:**
- Test explicit and contextual single-turn language with calibrated urgency.
- Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.
- Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.
- Test model empty/adversarial/failure output through final response control.
- Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.

**Security/privacy recommendations:**
- Prevention: enforce least privilege, least context, and server-side authorization/data minimization.
- Detection: add redacted correlated telemetry and anomaly/integrity alerts.
- Response: document containment, investigation, notification, and recovery ownership.
- Data lifecycle: define collection purpose, retention, deletion proof, backup, and migration handling.
- Secret rotation: rotate affected credentials/keys when applicable; otherwise record a reviewed not-applicable rationale.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-023 → ISSUE-023 — Anonymous identity churn can evade rate limits

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Apply a coarse pre-identity request limit and model-cost circuit breaker while preserving privacy.

**Durable remediation:** Layer limits by trusted API principal and coarse network/device signals before identity issuance, with privacy-preserving distributed enforcement.

**Intended outcome:** Remove the control gap for anonymous identity churn can evade rate limits while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** main._client_identity; IdentityManager.from_request; RateLimiter.check.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-023 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Call request-boundary helpers with repeated synthetic requests that retain no identity and compare generated keys/buckets.
- Add a regression test linked to ISSUE-023 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-HTTP-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Security/privacy owner reviews threat model, sensitive-data lifecycle, access, and incident implications.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Security/privacy recommendations:**
- Prevention: enforce least privilege, least context, and server-side authorization/data minimization.
- Detection: add redacted correlated telemetry and anomaly/integrity alerts.
- Response: document containment, investigation, notification, and recovery ownership.
- Data lifecycle: define collection purpose, retention, deletion proof, backup, and migration handling.
- Secret rotation: rotate affected credentials/keys when applicable; otherwise record a reviewed not-applicable rationale.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-025 → ISSUE-025 — Signed identity tokens have no intrinsic expiry or revocation

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Rotate the identity secret under a controlled invalidation event and shorten accepted session lifetime at the boundary.

**Durable remediation:** Add bounded token lifetimes, rotation key identifiers, revocation/session epochs, and secure re-issuance with migration support.

**Intended outcome:** Remove the control gap for signed identity tokens have no intrinsic expiry or revocation while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** IdentityManager._build; IdentityManager.verify; IdentityManager.from_request.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-025 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Issue a synthetic token, advance an isolated clock beyond cookie age, and verify that token parsing has no time check.
- Add a regression test linked to ISSUE-025 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-HTTP-1, TR-DEL-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Security/privacy owner reviews threat model, sensitive-data lifecycle, access, and incident implications.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Security/privacy recommendations:**
- Prevention: enforce least privilege, least context, and server-side authorization/data minimization.
- Detection: add redacted correlated telemetry and anomaly/integrity alerts.
- Response: document containment, investigation, notification, and recovery ownership.
- Data lifecycle: define collection purpose, retention, deletion proof, backup, and migration handling.
- Secret rotation: rotate affected credentials/keys when applicable; otherwise record a reviewed not-applicable rationale.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-028 → ISSUE-028 — Sensitive context is transmitted to an external model without a repository-evident privacy control plane

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Minimize model-bound context, provide explicit privacy notice, and disable optional external reasoning where processing terms are unverified.

**Durable remediation:** Establish explicit notice/consent, data minimization and redaction, provider no-retention controls, regional/legal review, and auditable transmission metadata without content logging.

**Intended outcome:** Remove the control gap for sensitive context is transmitted to an external model without a repository-evident privacy control plane while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** LLMClient; ChatbotService._build_prompt; ConversationRiskReasoner; ResponseBuilder.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-028 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Static trace only; no external provider call or user data inspection was performed.
- Add a regression test linked to ISSUE-028 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-SAFE-1, TR-PROMPT-1, TR-OUT-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.
- Security/privacy owner reviews threat model, sensitive-data lifecycle, access, and incident implications.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Mental-health recommendations:**
- Test explicit and contextual single-turn language with calibrated urgency.
- Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.
- Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.
- Test model empty/adversarial/failure output through final response control.
- Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.

**Security/privacy recommendations:**
- Prevention: enforce least privilege, least context, and server-side authorization/data minimization.
- Detection: add redacted correlated telemetry and anomaly/integrity alerts.
- Response: document containment, investigation, notification, and recovery ownership.
- Data lifecycle: define collection purpose, retention, deletion proof, backup, and migration handling.
- Secret rotation: rotate affected credentials/keys when applicable; otherwise record a reviewed not-applicable rationale.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-029 → ISSUE-029 — Default tests are not hermetic and can mutate repository-selected paths

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Run tests only in the established copied sandbox; prohibit default-suite execution from the live repository.

**Durable remediation:** Provide a mandatory hermetic test fixture that redirects every writable/read-sensitive path before imports and fails on path escape.

**Intended outcome:** Remove the control gap for default tests are not hermetic and can mutate repository-selected paths while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** tests/test_api.py; tests/test_hardening.py; tests/test_spec_compliance.py.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-029 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Static test review; execute only after copying to a findings-local sandbox with synthetic settings.
- Add a regression test linked to ISSUE-029 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: EP-PYTEST, TR-DOC-1, TR-DOC-2

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Independent test reviewer confirms the new evidence exercises the intended runtime boundary.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-031 → ISSUE-031 — Critical mental-health scenario families lack systematic regression coverage

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Make reviewed high-risk scenario checks a manual release gate until systematic regression coverage exists.

**Durable remediation:** Add reviewed synthetic single/multi-turn regression suites for every matrix cell and both classifier/model failure modes.

**Intended outcome:** Remove the control gap for critical mental-health scenario families lack systematic regression coverage while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** tests/test_reasoning_safety.py; tests/test_upgrades.py; tests/test_spec_compliance.py; tests/test_legacy_parity.py.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-031 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Reconcile the generated test catalog against safety-scenarios.jsonl required dimensions.
- Add a regression test linked to ISSUE-031 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-SAFE-1, TR-OUT-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.
- Independent test reviewer confirms the new evidence exercises the intended runtime boundary.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Mental-health recommendations:**
- Test explicit and contextual single-turn language with calibrated urgency.
- Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.
- Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.
- Test model empty/adversarial/failure output through final response control.
- Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-034 → ISSUE-034 — Two-worker deployment fragments process-local correctness and abuse state

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Use a single worker for safety/stateful traffic or add sticky routing while distributed coordination is absent.

**Durable remediation:** Move coordination/limits/invalidation to shared durable primitives or enforce compatible single-worker semantics with measured capacity and distributed locks.

**Intended outcome:** Remove the control gap for two-worker deployment fragments process-local correctness and abuse state while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** render.yaml; main._service/_feedback/_limiter; ChatbotService._turn_lock; ContextCache; ResponseCache; KnowledgeCache.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-034 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- In a disposable isolated multi-process harness, route concurrent synthetic sessions/doc updates across workers and compare authoritative versus local state.
- Add a regression test linked to ISSUE-034 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-DEPLOY-1, TR-CHAT-2, TR-DOC-2

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.
- Security/privacy owner reviews threat model, sensitive-data lifecycle, access, and incident implications.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Mental-health recommendations:**
- Test explicit and contextual single-turn language with calibrated urgency.
- Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.
- Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.
- Test model empty/adversarial/failure output through final response control.
- Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.

**Security/privacy recommendations:**
- Prevention: enforce least privilege, least context, and server-side authorization/data minimization.
- Detection: add redacted correlated telemetry and anomaly/integrity alerts.
- Response: document containment, investigation, notification, and recovery ownership.
- Data lifecycle: define collection purpose, retention, deletion proof, backup, and migration handling.
- Secret rotation: rotate affected credentials/keys when applicable; otherwise record a reviewed not-applicable rationale.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-035 → ISSUE-035 — Deployment persists data/ but leaves active knowledge and cache paths ephemeral

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Disable production document mutation or place knowledge/cache on verified durable storage before restart-prone deployment.

**Durable remediation:** Mount or externalize knowledge/cache explicitly, correct documentation, and add startup persistence/reconciliation checks across workers.

**Intended outcome:** Remove the control gap for deployment persists data/ but leaves active knowledge and cache paths ephemeral while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** render.yaml disk; Settings knowledge/cache paths; document routes; KnowledgeCache.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-035 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Resolve configured paths statically and compare them with the mounted subtree; no live deployment access is needed.
- Add a regression test linked to ISSUE-035 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-DOC-1, TR-DOC-2, TR-DEPLOY-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-039 → ISSUE-039 — Operational recovery, monitoring, and capacity controls are not repository-defined

**Priority / dependency gate:** P1 / `pre-production`.

**Immediate containment:** Establish an on-call owner, basic redacted alerts, model budget, disk threshold, and backup/restore runbook before launch.

**Durable remediation:** Define SLOs, redacted telemetry, safety/availability alerts, model budgets, backpressure, disk policies, backup/restore drills, and incident runbooks.

**Intended outcome:** Remove the control gap for operational recovery, monitoring, and capacity controls are not repository-defined while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** render.yaml; logging; deployment docs; storage/cache settings.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-039 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Static review; live platform configuration was not accessed.
- Add a regression test linked to ISSUE-039 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-DEPLOY-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Mental-health recommendations:**
- Test explicit and contextual single-turn language with calibrated urgency.
- Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.
- Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.
- Test model empty/adversarial/failure output through final response control.
- Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

## P2 — Planned Hardening

### SOLUTION-005 → ISSUE-005 — CLI bypasses HTTP identity, authorization, and abuse controls

**Priority / dependency gate:** P2 / `planned-hardening`.

**Immediate containment:** Keep CLI access local-only and prohibit production/shared-storage wrappers until the boundary is authenticated.

**Durable remediation:** Document and enforce the CLI trust boundary; require explicit local-only mode or equivalent authentication and isolated storage.

**Intended outcome:** Remove the control gap for cli bypasses http identity, authorization, and abuse controls while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** main.py::run_cli; ChatbotService.handle.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-005 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Static trace only; do not expose or execute the CLI against live storage.
- Add a regression test linked to ISSUE-005 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-CLI-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Security/privacy owner reviews threat model, sensitive-data lifecycle, access, and incident implications.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Security/privacy recommendations:**
- Prevention: enforce least privilege, least context, and server-side authorization/data minimization.
- Detection: add redacted correlated telemetry and anomaly/integrity alerts.
- Response: document containment, investigation, notification, and recovery ownership.
- Data lifecycle: define collection purpose, retention, deletion proof, backup, and migration handling.
- Secret rotation: rotate affected credentials/keys when applicable; otherwise record a reviewed not-applicable rationale.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-016 → ISSUE-016 — Knowledge provenance is not carried to user-visible responses

**Priority / dependency gate:** P2 / `planned-hardening`.

**Immediate containment:** Label knowledge-backed answers as unverified when no user-visible source mapping is available.

**Durable remediation:** Propagate document IDs/version timestamps through retrieval and require claim-level citations or explicit ungrounded uncertainty.

**Intended outcome:** Remove the control gap for knowledge provenance is not carried to user-visible responses while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** CachedSection; KnowledgeCache.build_context; ChatbotService._generate.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-016 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Static trace; no live generated claims were tested.
- Add a regression test linked to ISSUE-016 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-PROMPT-1, TR-RESP-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Mental-health recommendations:**
- Test explicit and contextual single-turn language with calibrated urgency.
- Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.
- Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.
- Test model empty/adversarial/failure output through final response control.
- Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-021 → ISSUE-021 — Schema evolution, backup, restore, and orphan cleanup are unsupported by repository evidence

**Priority / dependency gate:** P2 / `planned-hardening`.

**Immediate containment:** Block schema-changing releases until a backup, restore, migration, and rollback rehearsal exists.

**Durable remediation:** Adopt versioned reversible migrations, automated backup verification, restore drills, and orphan reconciliation with release gates.

**Intended outcome:** Remove the control gap for schema evolution, backup, restore, and orphan cleanup are unsupported by repository evidence while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** ChatArchive; ChatArchiveMongo; feedback stores; mongo_client; deployment docs.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-021 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Static repository review; live backup and restore tests are outside the no-external-service boundary.
- Add a regression test linked to ISSUE-021 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-COMMIT-1, TR-DEL-1, TR-DEPLOY-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-024 → ISSUE-024 — Rate-limiter cleanup cannot remove stale non-empty buckets

**Priority / dependency gate:** P2 / `planned-hardening`.

**Immediate containment:** Cap limiter key cardinality and restart/rotate workers under monitored memory thresholds until bounded eviction exists.

**Durable remediation:** Age all sampled buckets, cap key cardinality, and use a bounded/distributed limiter with explicit eviction metrics.

**Intended outcome:** Remove the control gap for rate-limiter cleanup cannot remove stale non-empty buckets while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** RateLimiter._hits; RateLimiter.check.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-024 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Use a synthetic clock or aged deques in an isolated unit harness and trigger cleanup from a different key.
- Add a regression test linked to ISSUE-024 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-HTTP-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Security/privacy owner reviews threat model, sensitive-data lifecycle, access, and incident implications.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Security/privacy recommendations:**
- Prevention: enforce least privilege, least context, and server-side authorization/data minimization.
- Detection: add redacted correlated telemetry and anomaly/integrity alerts.
- Response: document containment, investigation, notification, and recovery ownership.
- Data lifecycle: define collection purpose, retention, deletion proof, backup, and migration handling.
- Secret rotation: rotate affected credentials/keys when applicable; otherwise record a reviewed not-applicable rationale.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-027 → ISSUE-027 — Browser security headers are not explicitly enforced

**Priority / dependency gate:** P2 / `planned-hardening`.

**Immediate containment:** Configure a conservative edge/application header baseline and verify it in staging before public exposure.

**Durable remediation:** Define and test an application/platform security-header baseline with CSP nonces/hashes and staged compatibility review.

**Intended outcome:** Remove the control gap for browser security headers are not explicitly enforced while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** main.py Flask app; ui/index.html; render.yaml.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-027 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Static review only; platform-injected headers require external validation.
- Add a regression test linked to ISSUE-027 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-RESP-1, TR-DEPLOY-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Security/privacy owner reviews threat model, sensitive-data lifecycle, access, and incident implications.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Security/privacy recommendations:**
- Prevention: enforce least privilege, least context, and server-side authorization/data minimization.
- Detection: add redacted correlated telemetry and anomaly/integrity alerts.
- Response: document containment, investigation, notification, and recovery ownership.
- Data lifecycle: define collection purpose, retention, deletion proof, backup, and migration handling.
- Secret rotation: rotate affected credentials/keys when applicable; otherwise record a reviewed not-applicable rationale.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-030 → ISSUE-030 — Archive degradation test patches a method unused by runtime

**Priority / dependency gate:** P2 / `planned-hardening`.

**Immediate containment:** Treat the affected resilience test as non-evidence for commit failure until its boundary is corrected in a later remediation change.

**Durable remediation:** Patch the exact record_turn boundary and assert no response/secondary state is committed plus retry behavior.

**Intended outcome:** Remove the control gap for archive degradation test patches a method unused by runtime while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** tests/test_security.py::ResilienceTests.test_archive_failure_degrades_gracefully; ChatbotService._record_turn.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-030 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Inspect the patch target and runtime call graph; in a sandbox, assert the intended patch is invoked.
- Add a regression test linked to ISSUE-030 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-COMMIT-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.
- Independent test reviewer confirms the new evidence exercises the intended runtime boundary.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Mental-health recommendations:**
- Test explicit and contextual single-turn language with calibrated urgency.
- Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.
- Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.
- Test model empty/adversarial/failure output through final response control.
- Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-032 → ISSUE-032 — Live/destructive integration tests have no contained offline substitute

**Priority / dependency gate:** P2 / `planned-hardening`.

**Immediate containment:** Classify live/destructive suites as non-blocking external validation and add explicit release sign-off for their untested contracts.

**Durable remediation:** Create offline provider contract tests and disposable, network-isolated backend integration environments with destructive-operation allowlists.

**Intended outcome:** Remove the control gap for live/destructive integration tests have no contained offline substitute while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** tests/test_mongo_integration.py; tests/smoke_live.py; tests/smoke_staging.py.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-032 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Static classification only; these tests must remain ineligible without enforced egress denial and disposable services.
- Add a regression test linked to ISSUE-032 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: EP-SMOKE-LIVE, EP-SMOKE-STAGING

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Independent test reviewer confirms the new evidence exercises the intended runtime boundary.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-036 → ISSUE-036 — Database clients and feedback connections lack an explicit shutdown lifecycle

**Priority / dependency gate:** P2 / `planned-hardening`.

**Immediate containment:** Use conservative worker recycling and monitor open connections until graceful close hooks are verified.

**Durable remediation:** Define connection ownership and idempotent startup/shutdown hooks; test graceful termination under the deployment server.

**Intended outcome:** Remove the control gap for database clients and feedback connections lack an explicit shutdown lifecycle while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** app/storage/mongo_client.py; FeedbackStore; main.py lifecycle; Gunicorn.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-036 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Static lifecycle trace; observing live connection cleanup is outside the audit boundary.
- Add a regression test linked to ISSUE-036 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-DEPLOY-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-037 → ISSUE-037 — Dependency installation is reproducible only by version, not artifact

**Priority / dependency gate:** P2 / `planned-hardening`.

**Immediate containment:** Freeze current reviewed artifacts and prohibit opportunistic package upgrades during deployment builds.

**Durable remediation:** Generate a reviewed hash-locked transitive dependency set, SBOM, trusted index policy, and controlled update/vulnerability review process.

**Intended outcome:** Remove the control gap for dependency installation is reproducible only by version, not artifact while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** requirements.txt; render.yaml buildCommand.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-037 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Static review only; registries and advisory services were not queried.
- Add a regression test linked to ISSUE-037 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-DEPLOY-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.
- Security/privacy owner reviews threat model, sensitive-data lifecycle, access, and incident implications.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Security/privacy recommendations:**
- Prevention: enforce least privilege, least context, and server-side authorization/data minimization.
- Detection: add redacted correlated telemetry and anomaly/integrity alerts.
- Response: document containment, investigation, notification, and recovery ownership.
- Data lifecycle: define collection purpose, retention, deletion proof, backup, and migration handling.
- Secret rotation: rotate affected credentials/keys when applicable; otherwise record a reviewed not-applicable rationale.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-038 → ISSUE-038 — IMPLEMENTED AND VERIFIED (two proposed values await sign-off)

Liveness and readiness are now separate endpoints, and initialization is an explicit startup action rather than a side effect of whichever caller arrives first.

`GET /live` answers from process state alone — no service construction, no backend contact, no configuration that can fail — so it stays 200 while a dependency is degraded and never drives a restart loop. `GET /health` is readiness only: `readiness_report()` reads `_service` without ever constructing it and reports `initializing`, `startup_deadline_exceeded`, `initialization_failed`, `storage_failed`, `storage_timeout` or `ok`, with every non-ok state returning 503. The storage check runs under a hard deadline on a daemon thread, so a wedged backend cannot hold the probe open. Dependency states are coarse and exception detail is logged rather than returned, because the route is unauthenticated. `initialize_service()` is the startup entry point and returns success instead of raising, so a failed cold start leaves the process alive on `/live` with readiness fail-closed; `get_service()` publishes `_service` only after schema check and reconciliation pass.

Verified by `tests/test_health_probe.py` (15 tests, all failing before the change): a spy proves neither probe invokes `get_service`, and a hang test asserts a wall-clock bound so the deadline is proven rather than assumed. Full suite: 461 passed, 2 skipped, 147 subtests.

`READINESS_STARTUP_GRACE_SECONDS=120` and `READINESS_PROBE_TIMEOUT_SECONDS=5` are proposed, conservative and awaiting sign-off. Readiness deliberately does not retry initialization, and only storage is probed — model-provider reachability has a designed fallback and must not remove the process from service.

**Priority / dependency gate:** P2 / `planned-hardening`.

**Immediate containment:** Point liveness probes at a side-effect-free path and increase startup grace without masking readiness failures.

**Durable remediation:** Separate side-effect-free liveness from bounded readiness, initialize explicitly, and expose redacted dependency status with startup deadlines.

**Intended outcome:** Remove the control gap for health checks can initialize the complete service and external backends while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** main.health; main.get_service; build_chatbot; archive.healthcheck.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-038 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Import in a sanitized findings-local copy with warm-up disabled and instrument constructors; do not contact external services.
- Add a regression test linked to ISSUE-038 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-HEALTH-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

---

### SOLUTION-040 → ISSUE-040 — REPOSITORY-SIDE IMPLEMENTED AND VERIFIED (external promotion gate open)

**Repository-side (closed).** `autoDeploy: false` — a commit landing on main no longer releases itself; promotion is an explicit act against a named commit. `.github/workflows/gate.yml` runs the hermetic suite on every push and PR to main, on the production interpreter (3.12.7, matched to `PYTHON_VERSION`) with the production safety configuration, from a clean checkout with no `.env`. `requirements-dev.txt` pins test-only dependencies and is asserted absent from the production build command. `OPERATIONS.md` §8 documents the promotion checklist and the rollback target. `tests/test_deployment.py::PromotionGateTests` (8 tests) fails if `autoDeploy` is re-enabled, if the workflow disappears or tolerates failures, if CI's interpreter or safety flags drift from the manifest, or if the runbook loses the checklist.

The gate was unusable before this change: from a clean checkout with the production safety configuration the suite failed 5 tests, because call-counting assertions counted every provider call and the local `.env` disables the output reviewer. `FakeLLMClient` now tags calls by purpose and those tests count reply-producing calls, so results no longer depend on an untracked file. No product behaviour changed — the ISSUE-008 output wall still reviews every outbound reply including cached answers and refusals, and the ISSUE-003 assertion was strengthened to check what each call actually carried. Verified by running the full suite both ways: 469 passed, 2 skipped in each.

**External gate (not closed, needs):** branch protection making the gate a required check; immutable artifact promotion by digest instead of rebuild-from-source; staged rollout with automated rollback criteria; the first CI execution (no push was made in this session, so the 3.12.7 result is unverified); an automated pre-deploy migration check.

**Priority / dependency gate:** P2 / `planned-hardening`.

**Immediate containment:** Disable automatic production promotion from main until mandatory test, safety, security, schema, and artifact gates are enforced.

**Durable remediation:** Promote immutable tested artifacts through safety/security/schema gates, staged rollout, and automated rollback criteria.

**Intended outcome:** Remove the control gap for automatic deployment from main lacks an artifact-promotion gate while preserving fail-safe behavior, evidence, and rollback.

**Affected components:** render.yaml autoDeploy; branch main; test configuration.

**Prerequisites:**
- Confirm baseline reproduction for ISSUE-040 using synthetic or redacted evidence.
- Assign an accountable owner and acceptance reviewer.
- Preserve current data and audit evidence before migration.

**Implementation risks:**
- A stricter control can reduce availability or create false positives if introduced without staged measurement.
- Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context.

**Migration concerns:**
- Inventory existing affected records/configuration/state and define deterministic handling for legacy values.
- Avoid silently reclassifying, deleting, or exposing existing sensitive data.

**Rollback considerations:**
- Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.
- Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material.

**Automated verification:**
- Static deployment-flow review; no deployment action was triggered.
- Add a regression test linked to ISSUE-040 that fails before and passes after remediation.
- Run backend/worker/failure variants applicable to the affected trace IDs: TR-DEPLOY-1

**Manual review:**
- Engineering owner reviews evidence and rollback readiness.

**Acceptance evidence:**
- Passing targeted unit and property tests with retained output.
- Passing integration/failure-injection evidence in a hermetic environment.
- Reviewer sign-off that issue trigger conditions no longer produce the documented impact.

**Residual risk:** Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.

**Validation limits:** No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.

## P3 — Backlog

### SOLUTION-033 → ISSUE-033 — IMPLEMENTED AND VERIFIED

`tests/lanes.py` is now the single manifest of every test/diagnostic/operator entry point, recording for each one its command, kind, hermeticity, gate membership, whether pytest may import it, and a mandatory reason. `AUTHORITATIVE_COMMAND` names the one command that counts as current evidence. The root `conftest.py` derives its `collect_ignore` from the manifest, so `pytest .` no longer aborts on the self-`sys.exit()`ing root scripts and the ignore list cannot drift. The ISSUE-029 sandbox logic moved into `tests/sandbox.py` and is reused by `conftest.py` and by `test_all.py`/`test_audit.py`, which now bind a temporary project root before any `Settings` exists (proven by data/ mtime before/after) and fix a Windows cp1252 encoding crash. Every non-hermetic lane (`context_audit.py`, `smoke_live`, `smoke_staging`) refuses without an explicit opt-in and writes nothing when refused; `context_audit_results.json` is gitignored; `Test_Report.md` carries a staleness banner; `DEVELOPER_GUIDE.md` documents all lanes.

Verified by `tests/test_entry_points.py` (17 tests / 63 subtests): manifest completeness, gate/manifest agreement, no non-hermetic lane in the gate, `pytest --collect-only .` succeeding with >400 tests and no `INTERNALERROR`, both diagnostics passing without touching `data/`, and every non-hermetic lane refusing without its opt-in. Full suite: 510 passed, 2 skipped, 612 subtests. (Subtest counts are current as of the 2026-09-01 session, which added the `load-harness` and `redteam-crisis` diagnostic lanes to the manifest and the load-resilience suite; both new lanes are classified and documented, which is what keeps `test_entry_points.py` green.)

## Residual Risk and Validation Limits

Even after repository changes, production readiness requires production-equivalent but non-sensitive evidence for provider privacy, locale resources, TLS/WAF/headers, Mongo semantics, encryption, backups/restores, monitoring, capacity, and incident response. Safety controls require qualified human review; automated checks alone cannot establish clinical appropriateness. Rollback must not reintroduce exposed data, invalid credentials, unsafe output behavior, or schema corruption.

## Final Decision Rule

Readiness may change only after all P0/P1 issue acceptance evidence, the 48 repository-test blocker resolutions, conclusive Properties 4 and 5, safety regression review, and exact G8 integrity/output checks pass. Until then the authoritative decision is **NOT READY**.
