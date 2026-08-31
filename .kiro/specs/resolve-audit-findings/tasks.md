# Implementation Plan

## Overview

Execute the complete audit-remediation bugfix through ordered exploration, preservation, P0 containment, P1 remediation, P2 hardening, P3 test governance, review and external-validation integration, final integration, and fail-closed validation. Every dependency gate remains blocking: later work may proceed only after its prerequisite evidence is accepted, and readiness remains `not-ready` while any mandatory repository, review, rollback, or external-validation gate is missing or inconclusive.

## Tasks

- [ ] 1. Write the complete bug-condition exploration property test before any fix
  - **Property 1: Bug Condition** - Complete Audit Remediation
  - **CRITICAL**: Implement `tests/properties/test_audit_bug_conditions.py` before changing application behavior. It MUST fail on the unfixed baseline; do not weaken assertions or fix code during this task.
  - Implement the design `isBugCondition(input)` predicate over `C-001` through `C-045`, map each matched condition to its exact requirement 2.i property, and retain each minimized synthetic counterexample, seed, component-invocation metadata, and redacted expected/observed result.
  - Run under a unique Hermetic_Test_Root with fake providers, synthetic data, denied egress, bounded subprocesses, and no `.env`, live service, runtime database, or protected-record access.
  - Cover `C-001`–`C-005`: over-limit suffix loss in `clean_message`/`ChatbotService.handle`; failed `record_turn` plus same-instance retry; injection reaching `LLMClient.generate` with context markers; document partial failures/duplicate basenames; and untrusted/shared-storage CLI operation.
  - Cover `C-006`–`C-011`: negated/quoted/historical/third-party risk; cumulative risk with semantic failure; every harmful output category with disabled/failed review; unsafe/contradictory summary reuse; unknown/stale locale resources; and dependency/coercion/diagnosis/false-authority output.
  - Cover `C-012`–`C-016`: basename collisions; disjoint-query fallback; concurrent cache writers; instruction-like stored/retrieved context; and absent user-visible source/freshness support.
  - Cover `C-017`–`C-021`: over-age records; deletion with unattributed memory; injected multi-store deletion failures; readable sensitive serializers; and schema/index changes without migration/restore/rollback/orphan evidence.
  - Cover `C-022`–`C-028`: missing separate production auth; identity churn; stale limiter keys; token replay; tracked-file metadata for `data/chat_archive.sqlite3` without opening it; missing browser headers; and provider-bound sensitive context without privacy controls.
  - Cover `C-029`–`C-040`: non-hermetic paths; wrong archive patch target; missing safety-matrix cells; absent offline contracts; fragmented test entries; cross-worker divergence; ephemeral knowledge/cache paths; absent shutdown hooks; non-hash-locked dependencies; side-effecting health; missing operational controls; and ungated auto-deploy.
  - Cover `C-041` with unchanged TST-248, TST-251, TST-252, TST-253, TST-254, and TST-263 assertions; `C-042` with all 42 hardening IDs lacking per-test terminal outcomes; `C-043` with alternate-case/traversal/prefix/sibling/link/pre-existing paths; `C-044` with arbitrary ledger sequences; and `C-045` with conditional readiness missing its condition/gate.
  - Mark complete only when all 45 conditions have an expected failing counterexample or explicit missing-control proof in the redacted ledger.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 1.13, 1.14, 1.15, 1.16, 1.17, 1.18, 1.19, 1.20, 1.21, 1.22, 1.23, 1.24, 1.25, 1.26, 1.27, 1.28, 1.29, 1.30, 1.31, 1.32, 1.33, 1.34, 1.35, 1.36, 1.37, 1.38, 1.39, 1.40, 1.41, 1.42, 1.43, 1.44, 1.45, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 2.12, 2.13, 2.14, 2.15, 2.16, 2.17, 2.18, 2.19, 2.20, 2.21, 2.22, 2.23, 2.24, 2.25, 2.26, 2.27, 2.28, 2.29, 2.30, 2.31, 2.32, 2.33, 2.34, 2.35, 2.36, 2.37, 2.38, 2.39, 2.40, 2.41, 2.42, 2.43, 2.44, 2.45_

- [ ] 2. Write observation-first preservation property tests before any fix
  - **Property 2: Preservation** - Valid Behavior and Backend Parity
  - Run unfixed code first for generated inputs where `isBugCondition(input) = false`, normalize nondeterministic IDs/timestamps, and encode observed behavior in `tests/properties/test_audit_preservation.py`; do not assume or redesign baseline behavior.
  - Observe and preserve within-limit complete message processing, successful-turn idempotency/owner scope, benign minimum context, unique-document lifecycle, trusted isolated CLI behavior, explicit-risk urgent support, non-crisis support, relevant retrieval, verified locale resources, in-retention reads, completed deletion, valid migration/rotation, valid auth, safe UI behavior, and approved minimum external context.
  - Differentially compare SQLite and disposable Mongo-compatible route, safety level, authoritative state, deletion, error, and approved telemetry results; preserve bounded fail-safe behavior for component failures outside the changed condition.
  - Generate accepted/failed stage, migration, review, rollback, and readiness states and preserve dependency stops, redaction, evidence provenance, and fail-closed outcomes.
  - Verify the preservation suite PASSES on unfixed code and retain its observation corpus as the `F(input)` oracle.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14, 3.15, 3.16, 3.17, 3.18, 3.19, 3.20, 3.21, 3.22, 3.23, 3.24, 3.25, 3.26, 3.27, 3.28, 3.29, 3.30, 3.31, 3.32_

- [ ] 3. Implement P0 fail-closed containment as separately reviewable changes

  - [ ] 3.1 Fix ISSUE-008 model-output safety failure behavior
    - Extend `app/safety/guardrails.py::Guardrails.classify_output` and `app/chatbot/response_builder.py::ResponseBuilder.apply_output_safety` with deterministic diagnosis, treatment-certainty, medical-advice, delusion, shame, dependency, exclusivity, coercion, authority, and care-replacement categories.
    - Make disabled/timeout/malformed/failed semantic review return a bounded safe replacement; version the production policy in `render.yaml` and add category/reviewer-state unit, property, JSON, and SSE tests.
    - Keep this separately reviewable from input-crisis calibration and summary validation; rollback only to a previously accepted fail-closed output policy.
    - _Bug_Condition: C-008 where harmful output is produced and semantic review is disabled or fails_
    - _Expected_Behavior: `expectedBehavior` satisfies requirement 2.8 by blocking/replacing every defined harm_
    - _Preservation: Preserve bounded safe finalization and supportive non-harmful output under 3.7, 3.8, and 3.24_
    - _Requirements: 1.8, 2.8, 3.7, 3.8, 3.24_

  - [ ] 3.2 Fix ISSUE-022 production authentication preflight
    - Validate public/production mode in `app/config/settings.py` before app/service construction; require non-empty, separate user/admin controls and reject fallback/equal controls.
    - Update `app/security.py::ApiAuth.check_admin` and document-route guards; preserve only explicit loopback/isolated local mode. Add synthetic configuration-matrix and Flask route tests without reading `.env`.
    - _Bug_Condition: C-022 where public startup lacks valid separate user/admin controls_
    - _Expected_Behavior: `expectedBehavior` satisfies requirement 2.22 by failing startup closed_
    - _Preservation: Preserve constant-time comparison, bounded errors, and isolated local development under 3.16 and 3.17_
    - _Requirements: 1.22, 2.22, 3.16, 3.17, 3.25_

  - [ ] 3.3 Fix ISSUE-026 tracked runtime archive exposure
    - Stop tracking `data/chat_archive.sqlite3`, add runtime database patterns to `.gitignore`, and add metadata-only CI checks that reject tracked runtime data without opening record values.
    - Add a redacted history/clone/backup disposition and rotation-applicability evidence schema. Keep history rewriting and external clone/backup handling behind explicit approval and block readiness while absent.
    - _Bug_Condition: C-026 where runtime archive data is in current or historical Git metadata_
    - _Expected_Behavior: `expectedBehavior` satisfies requirement 2.26 by stopping distribution and requiring reviewed containment_
    - _Preservation: Preserve minimal chain-of-custody evidence and prohibit sensitive inspection under 3.15, 3.25, 3.26, and 3.32_
    - _Requirements: 1.26, 2.26, 3.15, 3.25, 3.26, 3.32_

  - [ ] 3.4 Add a P0 promotion gate
    - Require current accepted ISSUE-008/022 tests and ISSUE-026 containment metadata before any P1-dependent stage; test missing, stale, malformed, failed, and accepted evidence.
    - _Requirements: 2.8, 2.22, 2.26, 3.27, 3.29, 3.30_

- [ ] 4. Implement P1 message, turn-atomicity, and injection boundaries

  - [ ] 4.1 Fix ISSUE-001 all-or-nothing message-size handling
    - Add a `MessageBoundary` before `clean_message` in `main.chat`, `main.chat_stream`, and `ChatbotService.handle`; reject normalized content over 4,000 characters and state that none was analyzed/persisted.
    - Remove silent slicing and add 3,999/4,000/4,001+, normalization, prefix/suffix marker tests asserting no downstream invocation on rejection.
    - _Bug_Condition: C-001 where normalized content exceeds 4,000 characters_
    - _Expected_Behavior: requirement 2.1 whole-message rejection with disclosed status_
    - _Preservation: Preserve full processing for supported messages under 3.1_
    - _Requirements: 1.1, 2.1, 3.1_

  - [ ] 4.2 Fix ISSUE-002 pre-commit safety-state mutation
    - Add request-local `StagedSafetyState`/`TurnCoordinator` behavior in `chatbot_service.py`, `reasoner.py`, context cache, and both archive `record_turn` contracts; publish state only with the authoritative turn and clear it on every failure.
    - Add state-version migration, dual-read, reconciliation, rollback, exact failure injection, duplicate-request, and same-instance/fresh-instance retry tests for SQLite and disposable Mongo-compatible transactions.
    - _Bug_Condition: C-002 where analysis mutates local state and `record_turn` fails_
    - _Expected_Behavior: requirement 2.2 atomic commit/rollback_
    - _Preservation: Preserve idempotency, ordering, owner scope, and backend parity under 3.2, 3.20, and 3.23_
    - _Requirements: 1.2, 2.2, 3.2, 3.20, 3.23_

  - [ ] 4.3 Fix ISSUE-003 injection context exposure
    - Route injection decisions to deterministic refusal or authorized least-context handling before lookup, cross-session context, prompt assembly, or model generation; default-deny unneeded sources in `build_model_input`.
    - Add fake-model marker tests proving stored/history/summary/memory/knowledge content is absent for injection while benign authorized context remains available.
    - _Bug_Condition: C-003 where injection-class input invokes generation with privileged context_
    - _Expected_Behavior: requirement 2.3 deterministic refusal or least-context execution_
    - _Preservation: Preserve relevant owner-scoped benign context under 3.3_
    - _Requirements: 1.3, 2.3, 3.3, 3.18, 3.25_

- [ ] 5. Implement P1 contextual mental-health safety as separately reviewable policies

  - [ ] 5.1 Fix ISSUE-006 contextual crisis over-escalation
    - Add deterministic subject, negation, quotation, and temporal classification before urgent routing; unresolved ambiguity selects calm clarification while explicit current self-directed acute risk retains the urgent floor.
    - Add synthetic single/multi-turn tests and versioned-policy rollback tests.
    - _Bug_Condition: C-006 for negated, quoted, historical, or third-party matched language_
    - _Expected_Behavior: requirement 2.6 contextual distinction and clarification_
    - _Preservation: Preserve explicit-risk and non-crisis behavior under 3.6, 3.7, and 3.24_
    - _Requirements: 1.6, 2.6, 3.6, 3.7, 3.24_

  - [ ] 5.2 Fix ISSUE-007 semantic-risk failure and trajectory loss
    - Persist deterministic trajectory/uncertainty from authoritative turns and select conservative check-in/escalation on semantic failure; emit content-free reason telemetry.
    - Add generated evolution/failure tests plus schema migration, rollback, and SQLite/Mongo parity.
    - _Bug_Condition: C-007 where semantic reasoning fails for implicit/obfuscated/cumulative risk_
    - _Expected_Behavior: requirement 2.7 deterministic trajectory and conservative fallback_
    - _Preservation: Preserve explicit-risk and fail-safe behavior under 3.6, 3.8, 3.20, and 3.24_
    - _Requirements: 1.7, 2.7, 3.6, 3.8, 3.20, 3.24_

  - [ ] 5.3 Fix ISSUE-009 unsafe summary persistence/reuse
    - Add versioned summary provenance, source IDs, age/expiry, correction, and valid/quarantined/superseded state; validate safety/consistency/freshness before persistence/reuse and fall back to authoritative turns.
    - Add unsafe/stale/contradictory/corrected tests, backend parity, migration/reconciliation, and rollback-to-ignore.
    - _Bug_Condition: C-009 where unsafe, stale, or inaccurate summaries are reused_
    - _Expected_Behavior: requirement 2.9 validated untrusted derived data_
    - _Preservation: Preserve authorized recent context and safe failure under 3.3, 3.8, 3.11, and 3.24_
    - _Requirements: 1.9, 2.9, 3.3, 3.8, 3.11, 3.24_

  - [ ] 5.4 Fix ISSUE-010 locale-unsafe emergency resources
    - Replace the single assumed number with locale, verification-time, reviewer, and expiry records; unknown/unverified locale uses reviewed neutral wording and no conflicting number.
    - Add synthetic verified/unknown/stale/mismatched tests and policy rollback; never call real resources.
    - _Bug_Condition: C-010 where locale/resource applicability is unknown_
    - _Expected_Behavior: requirement 2.10 verified locale resource or neutral wording_
    - _Preservation: Preserve applicable reviewed guidance under 3.9 and 3.24_
    - _Requirements: 1.10, 2.10, 3.9, 3.24_

  - [ ] 5.5 Fix ISSUE-011 relational and false-authority boundaries
    - Detect and safely rewrite/block single-turn and cumulative dependency, exclusivity, coercion, diagnosis, treatment authority, and care replacement independently of prompts.
    - Add generated multi-turn, disagreement, false-positive/negative, and reviewer-failure tests; version separately from ISSUE-008 reviewer mechanics.
    - _Bug_Condition: C-011 where output adopts prohibited relational/authority language_
    - _Expected_Behavior: requirement 2.11 deterministic rejection/rewrite_
    - _Preservation: Preserve supportive and explicit-risk behavior under 3.6, 3.7, and 3.24_
    - _Requirements: 1.11, 2.11, 3.6, 3.7, 3.24_

- [ ] 6. Implement P1 document, retrieval, cache, and context-trust controls

  - [ ] 6.1 Fix ISSUE-012 document identity collisions
    - Replace basename keys in `knowledge_cache.py`, metadata, sections, and APIs with root-bounded case-aware path or immutable `DocumentIdentity`; migrate only unambiguous legacy entries and quarantine collisions.
    - Add duplicate/case/traversal/link/stability property tests, reconciliation, and rollback-to-read-only legacy metadata.
    - _Bug_Condition: C-012 for same basenames in separate directories_
    - _Expected_Behavior: requirement 2.12 unique stable identities_
    - _Preservation: Preserve unique-document behavior under 3.4 and 3.13_
    - _Requirements: 1.12, 2.12, 3.4, 3.13, 3.23_

  - [ ] 6.2 Fix ISSUE-013 arbitrary no-match fallback
    - Return typed `supported`, `no_result`, or `unavailable` from search/context/CAG lookup; `no_result` contains no unrelated section and requires bounded uncertainty.
    - Add query/corpus overlap properties and compatibility tests.
    - _Bug_Condition: C-013 for disjoint query against non-empty cache_
    - _Expected_Behavior: requirement 2.13 empty typed no-result_
    - _Preservation: Preserve ranked relevant retrieval under 3.10_
    - _Requirements: 1.13, 2.13, 3.10_

  - [ ] 6.3 Fix ISSUE-014 concurrent cache persistence
    - Use unique staging, checksum, fsync, generation/CAS, and inter-process coordination; quarantine/rebuild invalid generations.
    - Add generated two-process/crash schedules, stale-generation rejection, startup recovery, and rollback-to-last-verified-generation.
    - _Bug_Condition: C-014 for concurrent writers or termination during persistence_
    - _Expected_Behavior: requirement 2.14 serializable crash recovery_
    - _Preservation: Preserve retrieval/topology behavior under 3.10, 3.21, and 3.22_
    - _Requirements: 1.14, 2.14, 3.10, 3.21, 3.22_

  - [ ] 6.4 Fix ISSUE-004 non-atomic document lifecycle
    - Add staged upload/delete, operation IDs, exact document identity, candidate snapshot, generation commit, compensation, and idempotent recovery journal to `main.py` routes/CAG interfaces.
    - Inject failures after every file/manifest/cache/unlink boundary; migrate/block ambiguous basename requests and test restart/rollback convergence.
    - _Bug_Condition: C-004 for partial file/index success or ambiguous duplicate target_
    - _Expected_Behavior: requirement 2.4 staged exact commit/recovery_
    - _Preservation: Preserve successful unique lifecycle under 3.4, 3.13, and 3.23_
    - _Requirements: 1.4, 2.4, 3.4, 3.13, 3.23_

  - [ ] 6.5 Fix ISSUE-015 prompt-only stored/retrieved containment
    - Add provenance/trust tiers and instruction-like-content policy to memory, summary, history, knowledge, and prompt assembly; structurally separate sources and default legacy derived data to lower trust.
    - Add generated source/instruction and fake-model marker tests without suppressing benign relevant context.
    - _Bug_Condition: C-015 for instruction-like/adversarial stored or retrieved text_
    - _Expected_Behavior: requirement 2.15 scan, trust, separation, and minimum authorization_
    - _Preservation: Preserve benign owner-scoped context under 3.3_
    - _Requirements: 1.15, 2.15, 3.3, 3.18, 3.25_

- [ ] 7. Implement P1 sensitive-data lifecycle and storage controls

  - [ ] 7.1 Fix ISSUE-017 missing retention enforcement
    - Implement retention by data class with timestamps, expiry/status, holds, and bounded SQLite/Mongo workers; emit redacted counts.
    - Add age/hold/retry/idempotency/parity properties, unknown-age quarantine, additive migration, restore fixture, reconciliation, and rollback-before-cutover.
    - _Bug_Condition: C-017 for aged sensitive/derived records_
    - _Expected_Behavior: requirement 2.17 enforced retention and evidence_
    - _Preservation: Preserve in-retention continuity under 3.11, 3.13, and 3.23_
    - _Requirements: 1.17, 2.17, 3.11, 3.13, 3.23, 3.25_

  - [ ] 7.2 Fix ISSUE-018 legacy-memory session deletion
    - Migrate deterministic provenance and quarantine ambiguous memory from retrieval; report deleted/quarantined/residual state and withhold completion until accounted.
    - Add mixed-provenance, retry, parity, reconciliation, and rollback-that-keeps-quarantine-closed tests.
    - _Bug_Condition: C-018 when session deletion meets unattributed memory_
    - _Expected_Behavior: requirement 2.18 accounted/quarantined residual state_
    - _Preservation: Preserve irreversible deletion/migration under 3.12 and 3.13_
    - _Requirements: 1.18, 2.18, 3.12, 3.13, 3.25_

  - [ ] 7.3 Fix ISSUE-019 partial account deletion
    - Add durable idempotent deletion jobs/checkpoints across archive, memory/profile, feedback, summaries, safety, identity, and quarantine; receipt only after verified absence.
    - Add per-step failure, restart/retry, tombstoned-job migration, parity, and no-rehydration rollback tests.
    - _Bug_Condition: C-019 for cross-store partial deletion_
    - _Expected_Behavior: requirement 2.19 durable verified completion_
    - _Preservation: Preserve idempotent deletion under 3.12, 3.20, and 3.23_
    - _Requirements: 1.19, 2.19, 3.12, 3.20, 3.23, 3.25_

  - [ ] 7.4 Fix ISSUE-020 readable sensitive fields
    - Add versioned owner-bound encryption envelopes, separated key IDs, single-encrypted-write/dual-read migration, rotation, and recovery for archive/safety/summary/memory/profile/feedback on both backends.
    - Add envelope/wrong-owner/key/version tests, batch checkpoints, parity, interrupted migration, restore, rotation, and rollback; prohibit plaintext, keys, and decrypted content in evidence.
    - _Bug_Condition: C-020 for exposed readable storage fields_
    - _Expected_Behavior: requirement 2.20 classification/encryption/key/recovery controls_
    - _Preservation: Preserve authorized reads and no plaintext copies under 3.14_
    - _Requirements: 1.20, 2.20, 3.14, 3.23, 3.25, 3.32_

- [ ] 8. Implement P1 identity, abuse, and provider-privacy controls

  - [ ] 8.1 Fix ISSUE-023 identity-churn rate-limit bypass
    - Apply privacy-preserving pre-identity/trusted-principal/model-cost limits before principal issuance; use short-lived digests, not raw network IDs.
    - Add repeated-discard properties, valid-principal layering, bounded allowance, shared-worker, and degraded-store tests.
    - _Bug_Condition: C-023 for discarded identity state creating new buckets_
    - _Expected_Behavior: requirement 2.23 bounded pre-identity/distributed enforcement_
    - _Preservation: Preserve random IDs, owner scope, privacy, and bounded errors under 3.16_
    - _Requirements: 1.23, 2.23, 3.16_

  - [ ] 8.2 Fix ISSUE-025 non-expiring/non-revocable tokens
    - Implement Token_v2 `{v,u,s,iat,exp,kid,epoch}`, keyring, skew/expiry, revocation epochs, and bounded v1 reissuance; never log token bytes/claims.
    - Add structural/signature/clock/key/rotation/revocation/tombstone/migration/rollback and shared-store parity tests.
    - _Bug_Condition: C-025 for copied token replay_
    - _Expected_Behavior: requirement 2.25 reject expired/revoked/unknown-key tokens_
    - _Preservation: Preserve constant-time verification and owner scope under 3.16_
    - _Requirements: 1.25, 2.25, 3.13, 3.16, 3.25_

  - [ ] 8.3 Fix ISSUE-028 uncontrolled external processing
    - Add operation-specific notice/consent, field classification/redaction, context budgets, and provider-control preflight around prompt, semantic, reviewer, and `LLMClient` calls; disable unverified paths.
    - Emit content-free transmission metadata and add generated source/consent/provider-state tests.
    - _Bug_Condition: C-028 for sensitive provider-bound context without controls_
    - _Expected_Behavior: requirement 2.28 notice, minimization, redaction, audit, and fail-closed provider state_
    - _Preservation: Preserve permitted minimum processing under 3.18, 3.25, 3.26, and 3.32_
    - _Requirements: 1.28, 2.28, 3.18, 3.25, 3.26, 3.32_

- [ ] 9. Implement P1 distributed-state, durable-path, and operations controls

  - [ ] 9.1 Fix ISSUE-034 multi-worker divergence
    - Add shared turn leases, rate/cost state, safety continuity, cache/document generations, and invalidation with a deployment capability gate; enforce measured single-worker mode until multi-worker contracts pass.
    - Add generated concurrent request/rate/safety/document/cache/restart/unavailable-coordination schedules.
    - _Bug_Condition: C-034 for process-local state across workers_
    - _Expected_Behavior: requirement 2.34 shared coordination or enforced single-worker containment_
    - _Preservation: Preserve authoritative-turn and containment semantics under 3.21 and 3.22_
    - _Requirements: 1.34, 2.34, 3.21, 3.22, 3.23_

  - [ ] 9.2 Fix ISSUE-035 ephemeral knowledge/cache paths
    - Place documents/cache beneath declared durable storage or make cache reconstructable; align settings, CAG paths, and `render.yaml`, with startup generation reconciliation.
    - Add inventory/copy/checksum/cutover/restart/rollback tests.
    - _Bug_Condition: C-035 for restart loss of active knowledge/cache_
    - _Expected_Behavior: requirement 2.35 durable/reconstructable reconciled state_
    - _Preservation: Preserve visibility/recovery safeguards under 3.21 and 3.23_
    - _Requirements: 1.35, 2.35, 3.21, 3.23_

  - [ ] 9.3 Fix ISSUE-039 missing operational controls
    - Add code-enforced SLO/budget/backpressure schemas for model cost, latency, load, disk, connections, deletion backlog, and cache divergence; add content-free alert, capacity, backup/restore, incident-owner, and rollback evidence adapters.
    - Add generated threshold/dependency-failure tests proving bounded use and no unsafe output for availability.
    - _Bug_Condition: C-039 for load/failure without sufficient operational controls_
    - _Expected_Behavior: requirement 2.39 enforced budgets, recovery, ownership, and safe degradation_
    - _Preservation: Preserve fail-safe/rollback behavior under 3.8, 3.29, and 3.31_
    - _Requirements: 1.39, 2.39, 3.8, 3.29, 3.31_

- [ ] 10. Implement P1 hermetic testing and preserved blocker closure

  - [ ] 10.1 Fix ISSUE-029 default-suite isolation
    - Add pre-import `tests/conftest.py` bootstrap that ignores `.env`, redirects every read-sensitive/writable path beneath Hermetic_Test_Root, denies egress, bounds children, and fails on path escape/live dependency.
    - Add self-tests proving protected repository paths remain unchanged.
    - _Bug_Condition: C-029 for tests resolving live/repository paths_
    - _Expected_Behavior: requirement 2.29 mandatory pre-import isolation_
    - _Preservation: Preserve synthetic bounded tests under 3.19 and 3.32_
    - _Requirements: 1.29, 2.29, 3.19, 3.32_

  - [ ] 10.2 Fix ISSUE-031 missing safety scenario matrix
    - Add a machine-readable synthetic matrix covering every required language, trajectory, source, harm, and classifier/model/reviewer failure combination; fail reconciliation for missing cells/review evidence.
    - _Bug_Condition: C-031 for uncovered safety scenario families_
    - _Expected_Behavior: requirement 2.31 complete reviewed matrix_
    - _Preservation: Preserve crisis/support behavior under 3.6, 3.7, and 3.24_
    - _Requirements: 1.31, 2.31, 3.6, 3.7, 3.24_

  - [ ] 10.3 Fix C-041 and the six pipeline product failures
    - Make `tests/test_pipeline.py` use explicit temporary synthetic knowledge/fakes while retaining TST-248/251/252/253/254/263 assertions.
    - Fix test settings, `build_chatbot`, indexing/retrieval, `449` pricing support, grounding, and instruction filtering; add one regression per failure and a six-case hermetic integration run.
    - _Bug_Condition: C-041 for preserved pipeline knowledge/grounding/pricing/filtering scenarios_
    - _Expected_Behavior: requirement 2.41 all six pass without weaker claims_
    - _Preservation: Preserve relevant retrieval/context/isolation under 3.3, 3.10, and 3.19_
    - _Requirements: 1.41, 2.41, 3.3, 3.10, 3.19_

  - [ ] 10.4 Fix C-042 hardening timeout accounting
    - Execute each of the 42 identified `test_hardening.py` IDs independently or in bounded shards with per-test timeout, process cleanup, redacted output, and exactly one terminal classification.
    - Add runner properties for timeout/crash/duplicate/missing/interruption/resume; never infer child results from parent timeout.
    - _Bug_Condition: C-042 for batch timeout without child outcomes_
    - _Expected_Behavior: requirement 2.42 one conclusive result per test_
    - _Preservation: Preserve bounded redacted tests under 3.19 and 3.26_
    - _Requirements: 1.42, 2.42, 3.19, 3.26_

  - [ ] 10.5 Fix C-043 / Property 4 exact allowlist
    - Use exact case-aware root-relative equality and safe active-run descendant checks; reject alternate case, traversal, prefix, sibling, link escape, and pre-existing matches.
    - Re-run original and generated corpora with retained output.
    - _Bug_Condition: C-043 for alternate-case accepted path_
    - _Expected_Behavior: requirement 2.43 and design Property 4_
    - _Preservation: Preserve redacted root-bounded evidence under 3.26_
    - _Requirements: 1.43, 2.43, 3.26_

  - [ ] 10.6 Fix C-044 / Property 5 ordered total accounting
    - Implement discovered → eligibility → isolation → execution → one terminal result state machine; prohibit ineligible execution and retain interrupted history under a separate run ID.
    - Add arbitrary event-sequence properties and reconcile six pipeline, 42 hardening, and exact `record_turn` evidence.
    - _Bug_Condition: C-044 for interrupted/non-total ledger validation_
    - _Expected_Behavior: requirement 2.44 and design Property 5_
    - _Preservation: Preserve evidence provenance/readiness under 3.26 and 3.30_
    - _Requirements: 1.44, 2.44, 3.26, 3.30_

  - [ ] 10.7 Fix C-045 / Property 9 readiness generation
    - Require every expected-valid conditional record to include a non-empty condition and verification gate; keep validator strict and retain the minimized counterexample.
    - Add generated conclusion/integrity/blocker/evidence/condition/gate combinations.
    - _Bug_Condition: C-045 for conditional record missing its mandatory condition_
    - _Expected_Behavior: requirement 2.45 and design Property 9_
    - _Preservation: Preserve stage/failure/not-ready rules under 3.27, 3.29, 3.30, and 3.31_
    - _Requirements: 1.45, 2.45, 3.27, 3.29, 3.30, 3.31_

- [ ] 11. Implement P2 CLI, provenance, migration, and limiter hardening

  - [ ] 11.1 Fix ISSUE-005 unenforced CLI trust boundary
    - Add explicit trusted-local CLI mode in `main.run_cli`; refuse shared/production storage unless equivalent authorization, abuse controls, isolated identity, and isolated storage are configured.
    - Add configuration tests and isolated bounded CLI smoke tests without live storage.
    - _Bug_Condition: C-005 for CLI outside trusted local isolation_
    - _Expected_Behavior: requirement 2.5 enforced equivalent boundary or refusal_
    - _Preservation: Preserve bounded trusted-local CLI behavior under 3.5_
    - _Requirements: 1.5, 2.5, 3.5, 3.25_

  - [ ] 11.2 Fix ISSUE-016 missing user-visible provenance
    - Propagate source ID, version/hash prefix, freshness, and claim support from `CachedSection` through CAG lookup and response serialization; require claim support or explicit uncertainty.
    - Add supported/contested/stale/no-result tests without exposing source content.
    - _Bug_Condition: C-016 for knowledge-backed answer without support/freshness contract_
    - _Expected_Behavior: requirement 2.16 stable source/freshness and claim support_
    - _Preservation: Preserve relevant retrieval under 3.10_
    - _Requirements: 1.16, 2.16, 3.10, 3.24_

  - [ ] 11.3 Fix ISSUE-021 migration/restore/rollback/orphan gaps
    - Add a shared migration ledger/runner for archive, memory, feedback, identity, summary, deletion, encryption, document, and cache schemas with checksum, compatibility, dry-run/apply/rollback, and redacted reconciliation totals.
    - Add synthetic SQLite backup/restore and disposable Mongo-compatible migration/index phases, orphan reconciliation, interruption, rollback rehearsal, and compatibility tests; block schema promotion without accepted evidence.
    - _Bug_Condition: C-021 for schema/restore/orphan work without recovery evidence_
    - _Expected_Behavior: requirement 2.21 reversible migration, restore, compatibility, and reconciliation_
    - _Preservation: Preserve attributable records and safeguards under 3.13, 3.14, and 3.23_
    - _Requirements: 1.21, 2.21, 3.13, 3.14, 3.23_

  - [ ] 11.4 Fix ISSUE-024 unbounded stale limiter keys
    - Globally age buckets, cap cardinality, evict deterministically, and emit content-free metrics in local/shared limiter interfaces.
    - Add synthetic-clock/one-time-identity properties for bounded memory, valid active buckets, deterministic eviction, and multi-worker parity.
    - _Bug_Condition: C-024 for stale non-empty one-time buckets_
    - _Expected_Behavior: requirement 2.24 global ageing and bounded keys_
    - _Preservation: Preserve privacy-preserving enforcement under 3.16_
    - _Requirements: 1.24, 2.24, 3.16_

- [ ] 12. Implement remaining P2 runtime, supply-chain, integration, and deployment hardening

  - [ ] 12.1 Fix ISSUE-027 browser security headers
    - Add Flask middleware for reviewed CSP, transport, framing, referrer, MIME, and permissions protections; stage nonce/hash CSP compatibility for `ui/index.html`.
    - Add local client header/UI tests and an external-edge equivalence evidence slot.
    - _Bug_Condition: C-027 for public UI without application header baseline_
    - _Expected_Behavior: requirement 2.27 tested browser protections_
    - _Preservation: Preserve safe rendering/cookies/endpoints/errors under 3.17_
    - _Requirements: 1.27, 2.27, 3.17, 3.25_

  - [ ] 12.2 Fix ISSUE-030 archive degradation test boundary
    - Patch `record_turn` in `tests/test_security.py::ResilienceTests.test_archive_failure_degrades_gracefully`; assert invocation, no response/secondary commit, and same/fresh retry equivalence on both archive contracts.
    - Feed the result into Property 5 accounting.
    - _Bug_Condition: C-030 where the test patches unused `record`_
    - _Expected_Behavior: requirement 2.30 exact authoritative failure injection_
    - _Preservation: Preserve idempotency/isolation under 3.2, 3.19, and 3.20_
    - _Requirements: 1.30, 2.30, 3.2, 3.19, 3.20_

  - [ ] 12.3 Fix ISSUE-032 absent contained offline substitutes
    - Add network-isolated fake-provider and disposable Mongo/deployment contracts; require generated-name destructive allowlists and retain live suites as separately authorized/ineligible by default.
    - Add common-interface parity and egress-denial tests.
    - _Bug_Condition: C-032 for changed provider/deployment/Mongo semantics without eligible validation_
    - _Expected_Behavior: requirement 2.32 contained substitutes and explicit live authorization_
    - _Preservation: Preserve egress denial/backend semantics under 3.19, 3.20, and 3.32_
    - _Requirements: 1.32, 2.32, 3.19, 3.20, 3.32_

  - [ ] 12.4 Fix ISSUE-036 missing shutdown lifecycle
    - Define ownership and startup/drain/close hooks for archive, feedback, and shared Mongo clients in Flask/Gunicorn integration.
    - Add repeated-close, partial-init, reload, rolling termination, committed in-flight work, and test-teardown tests.
    - _Bug_Condition: C-036 for worker termination without explicit lifecycle_
    - _Expected_Behavior: requirement 2.36 idempotent close after drain_
    - _Preservation: Preserve committed work/rollback under 3.21 and 3.29_
    - _Requirements: 1.36, 2.36, 3.21, 3.29_

  - [ ] 12.5 Fix ISSUE-037 artifact reproducibility
    - Generate/enforce a reviewed hash-locked transitive set, trusted-source policy, SBOM, and provenance verification; remove opportunistic package-tool upgrades from `render.yaml`.
    - Add offline CI checks for hash/source/SBOM drift and prior verified lock rollback.
    - _Bug_Condition: C-037 for later unverified/different dependency artifacts_
    - _Expected_Behavior: requirement 2.37 verified reproducible artifacts_
    - _Preservation: Preserve deployment safeguards under 3.23_
    - _Requirements: 1.37, 2.37, 3.23, 3.25_

  - [ ] 12.6 Fix ISSUE-038 side-effecting health checks
    - Add side-effect-free `/live`, explicit initialization state, and bounded `/ready` reading preinitialized redacted status; update probe configuration/startup grace.
    - Add constructor-spy tests proving cold liveness performs no service/storage/cache/model construction.
    - _Bug_Condition: C-038 for cold probe before initialization_
    - _Expected_Behavior: requirement 2.38 separate liveness/readiness_
    - _Preservation: Preserve intended endpoints/safe errors under 3.17_
    - _Requirements: 1.38, 2.38, 3.17_

  - [ ] 12.7 Fix ISSUE-040 ungated automatic deployment
    - Disable direct production promotion from main; build one immutable artifact and enforce test, safety, security, privacy, schema/migration/restore, provenance, external, canary, and rollback gates.
    - Add missing/stale/failed-gate and canary-failure simulations; rollback only to a tested compatible artifact and never restore unsafe output/auth/data/token/plaintext/schema states.
    - _Bug_Condition: C-040 for main-branch rebuild/deploy without mandatory gates_
    - _Expected_Behavior: requirement 2.40 immutable staged promotion_
    - _Preservation: Preserve deployment/migration safety under 3.17, 3.23, and 3.29_
    - _Requirements: 1.40, 2.40, 3.17, 3.23, 3.29_

- [ ] 13. Implement P3 authoritative test governance

  - [ ] 13.1 Fix ISSUE-033 fragmented entry points and stale evidence
    - Create one manifest for pytest, `test_all.py`, `test_audit.py`, `context_audit.py`, smoke/integration suites, and helpers with lane, command, eligibility, timeout, owner, artifact, freshness, and network/destructive requirements.
    - Add runner/reconciliation for run-or-explicit-skip, stale-output rejection, Property 5 events, schema/drift/duplicate/freshness/resume tests.
    - _Bug_Condition: C-033 for omitted entry points or stale evidence_
    - _Expected_Behavior: requirement 2.33 one authoritative classified manifest_
    - _Preservation: Preserve hermetic redacted execution under 3.19 and 3.26_
    - _Requirements: 1.33, 2.33, 3.19, 3.26_

- [ ] 14. Implement machine-enforced qualified safety-review integration
  - Add versioned evidence/promotion checks for changes to guardrails, reasoner, analyzer, crisis handler, response builder, summaries, memory, prompts, locale resources, and model context.
  - Require artifact/policy/matrix identity, reviewer role, covered categories, false-positive/negative, over/under-escalation, cumulative/dependency/diagnosis/delusion/privacy/boundary disposition, decision, expiry, and rollback policy without conversation content.
  - Test that missing, stale, mismatched, rejected, or malformed evidence blocks the affected stage and readiness; automated tests alone cannot satisfy the gate.
  - _Requirements: 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 2.31, 3.6, 3.7, 3.9, 3.24, 3.27, 3.29, 3.30_

- [ ] 15. Implement machine-enforced security, privacy, data, and operations review integration
  - Add versioned evidence gates for auth/tokens/limits, encryption/retention/deletion/provider transmission/Git exposure/headers, migration/restore/document quarantine/topology/capacity/incident/rollback.
  - Validate scope/artifact, accountable role, prevention/detection/response/lifecycle/least privilege, rotation applicability, expiry, residual risk, and decision without secrets, tokens, personal content, decrypted values, or environment settings.
  - Test missing, stale, wrong-artifact, incomplete, rejected, and malformed records.
  - _Requirements: 2.17, 2.18, 2.19, 2.20, 2.21, 2.22, 2.23, 2.25, 2.26, 2.27, 2.28, 2.34, 2.35, 2.39, 2.40, 3.15, 3.16, 3.17, 3.18, 3.23, 3.25, 3.26, 3.29, 3.30_

- [ ] 16. Implement external-validation integration points without claiming external results
  - Add content-free signed/versioned evidence adapters for provider retention/training/region, infrastructure/backup encryption, locale-resource currency, edge/TLS/header equivalence, Mongo topology, monitoring/alerts, backup/restore drills, capacity, and incident ownership.
  - Bind records to environment, artifact/config version, scope, validator, timestamp/expiry, result, and redacted reference; never infer external passes from repository state.
  - Test missing, expired, wrong-environment/artifact, partial, rejected, and accepted records; all non-accepted mandatory states remain `not-ready`.
  - _Requirements: 2.10, 2.20, 2.21, 2.27, 2.28, 2.32, 2.34, 2.35, 2.39, 2.40, 3.25, 3.26, 3.30, 3.31, 3.32_

- [ ] 17. Integrate stage ordering, parity, migration, rollback, and deployment gates
  - Enforce baseline → P0 → P1 safety/identity/data → P1 document/distributed/tests → P2 → P3 → external validation → final readiness; stop dependent stages on any failed test, reconciliation, review, or rollback criterion.
  - Reconcile all 45 condition IDs, ISSUE-001 through ISSUE-040, six pipeline IDs, 42 hardening IDs, Properties 4/5/9, backend parity, migration/restore/rollback, reviews, and external evidence to exactly one current status.
  - Add property tests for arbitrary stage/evidence sequences, separately reviewable shared-boundary changes, stale/incompatible evidence, failed rollback, safe resume, and immutable-artifact canary/rollback simulation.
  - _Bug_Condition: aggregate `C-001 OR ... OR C-045` or an unsatisfied prerequisite_
  - _Expected_Behavior: every matched requirement 2.i plus accepted prerequisites, parity, and non-exposure_
  - _Preservation: Preserve inventories, backups, dry-runs, separate changes, stops, redaction, and safe rollback under 3.20, 3.23, 3.26, 3.27, 3.28, and 3.29_
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 2.12, 2.13, 2.14, 2.15, 2.16, 2.17, 2.18, 2.19, 2.20, 2.21, 2.22, 2.23, 2.24, 2.25, 2.26, 2.27, 2.28, 2.29, 2.30, 2.31, 2.32, 2.33, 2.34, 2.35, 2.36, 2.37, 2.38, 2.39, 2.40, 2.41, 2.42, 2.43, 2.44, 2.45, 3.20, 3.23, 3.26, 3.27, 3.28, 3.29_

- [ ] 18. Validate the completed fix and fail-closed readiness

  - [ ] 18.1 Run all required validation lanes
    - Execute only non-watch bounded manifest commands under Hermetic_Test_Root: targeted unit, safety matrix, property, document/cache concurrency, identity/lifecycle, SQLite/disposable-Mongo parity, migration/restore/rollback, six pipeline, 42 hardening, Properties 4/5/9, review, external-evidence, and deployment-gate suites.
    - Reconcile each discovered test and `C-001`–`C-045` to one current terminal result; never convert timeout, interruption, missing review, or external gap to pass.
    - _Requirements: 2.29, 2.30, 2.31, 2.32, 2.33, 2.41, 2.42, 2.43, 2.44, 2.45, 3.19, 3.20, 3.26_

  - [ ] 18.2 Verify the original exploration property now passes
    - **Property 1: Expected Behavior** - Complete Audit Remediation
    - Re-run the SAME task 1 property, not a replacement. Every generated matched condition must satisfy its 2.i requirement, prerequisites, parity, and non-exposure; missing human/external evidence is a gate failure.
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 2.12, 2.13, 2.14, 2.15, 2.16, 2.17, 2.18, 2.19, 2.20, 2.21, 2.22, 2.23, 2.24, 2.25, 2.26, 2.27, 2.28, 2.29, 2.30, 2.31, 2.32, 2.33, 2.34, 2.35, 2.36, 2.37, 2.38, 2.39, 2.40, 2.41, 2.42, 2.43, 2.44, 2.45_

  - [ ] 18.3 Verify the original preservation property still passes
    - **Property 2: Preservation** - Valid Behavior and Backend Parity
    - Re-run the SAME task 2 differential suite, not new tests; require observational equivalence outside matched conditions except explicit required strengthening.
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14, 3.15, 3.16, 3.17, 3.18, 3.19, 3.20, 3.21, 3.22, 3.23, 3.24, 3.25, 3.26, 3.27, 3.28, 3.29, 3.30, 3.31, 3.32_

  - [ ] 18.4 Checkpoint - enforce the final readiness decision
    - Emit `not-ready` with explicit redacted blockers unless every P0/P1 item, all six pipeline tests, all 42 hardening tests, Properties 4/5/9, exact integrity/output gates, backend parity, migrations/restores/rollbacks, qualified reviews, P2/P3 dispositions, and mandatory external validations are current and accepted.
    - When all gates pass, emit a reviewed readiness candidate retaining residual risks, monitoring, rollback ownership, and evidence provenance; do not infer external controls.
    - Ensure all tests pass and ask the user if questions arise.
    - _Requirements: 3.27, 3.29, 3.30, 3.31, 3.32_

## Notes

- Tasks 1 and 2 establish the unfixed exploration and preservation baselines before implementation begins.
- P0 containment and its promotion gate block all dependent P1 work; P1 acceptance blocks P2, and P2 blocks P3.
- Review and external-validation integration follow implementation governance and precede final integration and validation.
- Any failed, missing, stale, malformed, or inconclusive mandatory gate stops dependent work and preserves `not-ready` status.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1", "2"] },
    { "id": 1, "tasks": ["3.1", "3.2", "3.3"] },
    { "id": 2, "tasks": ["3.4"] },
    { "id": 3, "tasks": ["4.1", "4.2", "4.3", "5.1", "5.2", "5.3", "5.4", "5.5", "7.1", "7.2", "7.3", "7.4", "8.1", "8.2", "8.3"] },
    { "id": 4, "tasks": ["6.1", "6.2", "6.3", "6.4", "6.5", "9.1", "9.2", "9.3"] },
    { "id": 5, "tasks": ["10.1", "10.2", "10.3", "10.4", "10.5", "10.6", "10.7"] },
    { "id": 6, "tasks": ["11.1", "11.2", "11.3", "11.4", "12.1", "12.2", "12.3", "12.4", "12.5", "12.6", "12.7"] },
    { "id": 7, "tasks": ["13.1"] },
    { "id": 8, "tasks": ["14", "15"] },
    { "id": 9, "tasks": ["16"] },
    { "id": 10, "tasks": ["17"] },
    { "id": 11, "tasks": ["18.1"] },
    { "id": 12, "tasks": ["18.2", "18.3"] },
    { "id": 13, "tasks": ["18.4"] }
  ]
}
```