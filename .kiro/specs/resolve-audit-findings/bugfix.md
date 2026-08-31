# Bugfix Requirements Document

## Introduction

This bugfix specification defines the complete remediation scope for audit run `audit-20260827T102557885287Z-073047a3`. The authoritative inputs are the repository-root `issue.md` and `solution.md`. Scope includes every finding from ISSUE-001 through ISSUE-040 at priorities P0, P1, P2, and P3; the six preserved pipeline product failures; the 42-test hardening timeout cohort; and unresolved validation Properties 4, 5, and 9. No application behavior is changed by this requirements phase.

For each clause 1.N, `C-N(X)` denotes the stated bug condition over an applicable input, request, state, configuration, lifecycle event, test, or release candidate `X`. The aggregate bug condition is `C(X) = C-001(X) OR ... OR C-045(X)`. Clause 2.N defines the required property `P-N(F'(X))` for the fixed system. Fix checking requires that, for every `X` satisfying `C-N(X)`, the fixed system `F'` satisfies clause 2.N. Preservation checking requires that, for every input outside the affected bug condition, the original and fixed observable behavior remain equivalent except where a numbered requirement explicitly strengthens safety, security, privacy, integrity, or operability.

Remediation SHALL be staged by dependency gate: P0 exposure containment and fail-closed boundaries first; P1 safety, identity, data-lifecycle, consistency, distributed-state, and hermetic-test controls second; P2 planned hardening third; P3 test-governance improvement fourth; and final readiness verification last. A later gate SHALL NOT be treated as complete until its prerequisite controls and retained acceptance evidence pass. Secret values, environment credentials, conversation contents, and other sensitive records SHALL NOT be reproduced in requirements, tests, logs, reports, or migration evidence.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN `C-001(X)` holds because a normalized user message exceeds 4,000 characters and material content occurs after the retained prefix THEN the system silently truncates the message and may omit safety-critical content from analysis and persistence (ISSUE-001).

1.2 WHEN `C-002(X)` holds because first-turn safety analysis mutates process-local state before the authoritative turn commit and that commit fails THEN the system can retain uncommitted risk or analyzer state for a retry on the same worker (ISSUE-002).

1.3 WHEN `C-003(X)` holds because an input is classified as prompt injection while model generation remains available THEN the system can send stored or retrieved privileged context to the model despite the injection signal (ISSUE-003).

1.4 WHEN `C-004(X)` holds because a document filesystem operation succeeds while the corresponding index/cache operation fails, or duplicate basenames are targeted THEN the system can leave file and index state divergent or delete an unintended same-named document (ISSUE-004).

1.5 WHEN `C-005(X)` holds because the CLI is exposed beyond a trusted local boundary or points to shared production storage THEN the system bypasses HTTP identity, authorization, revocation, and abuse controls (ISSUE-005).

1.6 WHEN `C-006(X)` holds because matched self-harm language is negated, quoted, historical, or about a third party THEN the deterministic crisis floor can incorrectly treat it as current self-directed imminent risk (ISSUE-006).

1.7 WHEN `C-007(X)` holds because semantic risk reasoning is unavailable or malformed while risk is implicit, euphemistic, obfuscated, or cumulative across turns THEN the system falls back to a context-poor deterministic floor and can under-escalate risk (ISSUE-007).

1.8 WHEN `C-008(X)` holds because generated output contains diagnosis, treatment certainty, delusion reinforcement, dependency, coercion, shame, broad medical advice, or another therapeutic harm while semantic review is disabled or fails THEN the system can deliver the unsafe output after narrow deterministic checks (ISSUE-008).

1.9 WHEN `C-009(X)` holds because model-generated rolling summaries are unsafe, contradictory, stale, or inaccurate THEN the system persists and reuses those summaries without summary-specific safety and consistency validation (ISSUE-009).

1.10 WHEN `C-010(X)` holds because a crisis user is outside the configured emergency-number jurisdiction or locale is unknown THEN the system can provide an inapplicable emergency resource as though it were applicable (ISSUE-010).

1.11 WHEN `C-011(X)` holds because model output adopts exclusivity, emotional dependency, coercion, diagnosis, treatment authority, or replacement-of-care language THEN deterministic final-output controls do not comprehensively enforce vulnerable-user relational boundaries (ISSUE-011).

1.12 WHEN `C-012(X)` holds because supported knowledge files in different subdirectories share a basename THEN the system keys them as one document and one can silently replace the other in scan or index state (ISSUE-012).

1.13 WHEN `C-013(X)` holds because a query has no lexical overlap with a non-empty knowledge cache THEN the system injects arbitrary leading sections instead of representing a no-result state (ISSUE-013).

1.14 WHEN `C-014(X)` holds because multiple workers persist the knowledge cache concurrently or one terminates during persistence THEN the shared fixed temporary filename can be overwritten, corrupted, or replaced with inconsistent state (ISSUE-014).

1.15 WHEN `C-015(X)` holds because memory, summaries, history, or retrieved knowledge contains instruction-like or adversarial text THEN the system relies primarily on prompt labels rather than deterministic structural containment (ISSUE-015).

1.16 WHEN `C-016(X)` holds because a knowledge-backed answer is wrong, stale, or contested THEN the user-visible response lacks a stable claim-to-source or freshness contract despite internal provenance (ISSUE-016).

1.17 WHEN `C-017(X)` holds because sensitive conversations, summaries, inferred safety state, memories, profiles, or feedback age without an explicit deletion request THEN the system retains them without a repository-enforced expiry policy (ISSUE-017).

1.18 WHEN `C-018(X)` holds because a session deletion encounters legacy or unattributed derived memory THEN the system can report session deletion while related personal or health data remains retrievable (ISSUE-018).

1.19 WHEN `C-019(X)` holds because one store fails after another store has progressed during account deletion THEN the system can leave a tombstoned account with residual data and no durable, verifiable completion state (ISSUE-019).

1.20 WHEN `C-020(X)` holds because a database file, backup, volume, collection, or privileged storage credential is exposed THEN readable application fields can disclose sensitive conversation and inferred-health data in bulk (ISSUE-020).

1.21 WHEN `C-021(X)` holds because a release changes schema or indexes, a restore is required, or partial lifecycle work leaves orphan records THEN the system lacks versioned migration, rollback, backup/restore, and orphan-reconciliation evidence (ISSUE-021).

1.22 WHEN `C-022(X)` holds because production or another publicly reachable mode starts with absent or empty user API or administrator credentials THEN the system disables authentication or lets administrator checks fall back to an insufficient boundary (ISSUE-022).

1.23 WHEN `C-023(X)` holds because an anonymous caller repeatedly discards identity state THEN the system issues fresh pseudonymous identities and allows the caller to obtain new rate-limit buckets (ISSUE-023).

1.24 WHEN `C-024(X)` holds because many one-time identities create non-empty rate-limit buckets and never return THEN stale buckets are not aged globally and worker memory can grow without a firm key bound (ISSUE-024).

1.25 WHEN `C-025(X)` holds because a signed identity token is copied and replayed while its signing secret remains valid THEN the token has no intrinsic expiry, key identifier, or revocation epoch and can remain valid beyond the cookie lifetime (ISSUE-025).

1.26 WHEN `C-026(X)` holds because a runtime conversation archive database is tracked in current or historical Git metadata THEN repository clones, backups, and history can distribute sensitive records outside runtime authorization (ISSUE-026).

1.27 WHEN `C-027(X)` holds because the browser UI is publicly deployed and edge infrastructure does not add equivalent protections THEN responses lack an explicit application-defined security-header baseline (ISSUE-027).

1.28 WHEN `C-028(X)` holds because model generation or semantic safety processing receives personal or health-related conversation context THEN sensitive data crosses an external processing boundary without repository-enforced notice, minimization, redaction, retention, or regional controls (ISSUE-028).

1.29 WHEN `C-029(X)` holds because default tests execute from the live repository with default or environment-selected writable paths THEN tests can mutate repository data, cache, knowledge, identity, or database artifacts and depend on local state (ISSUE-029).

1.30 WHEN `C-030(X)` holds because the archive-degradation test patches an interface not called by runtime THEN the test can pass without exercising the authoritative `record_turn` failure path (ISSUE-030).

1.31 WHEN `C-031(X)` holds because safety logic changes in a scenario family not covered by the existing example-driven suite THEN regressions involving contextual crisis language, obfuscation, multi-turn evolution, reviewer failure, dependency, delusion, diagnosis, or locale can pass undetected (ISSUE-031).

1.32 WHEN `C-032(X)` holds because provider, deployment, or Mongo semantics change while live/destructive suites remain ineligible THEN no complete contained offline substitute verifies those contracts (ISSUE-032).

1.33 WHEN `C-033(X)` holds because engineers run only default test discovery or rely on historical output THEN separate root scripts and smoke/audit entry points can be omitted or stale evidence can be treated as current (ISSUE-033).

1.34 WHEN `C-034(X)` holds because requests, concurrent turns, rate checks, or document changes span multiple worker processes THEN process-local services, locks, counters, caches, and invalidation state can diverge (ISSUE-034).

1.35 WHEN `C-035(X)` holds because production documents or cache state change and a worker/container restarts THEN active knowledge and cache paths can be lost because declared durable storage covers only a different path (ISSUE-035).

1.36 WHEN `C-036(X)` holds because workers terminate, reload, or roll during deployment THEN shared database clients and feedback connections lack an explicit idempotent shutdown lifecycle (ISSUE-036).

1.37 WHEN `C-037(X)` holds because dependencies are rebuilt at a later time or a package index/artifact changes THEN exact direct versions do not guarantee identical transitive artifacts or verified provenance (ISSUE-037).

1.38 WHEN `C-038(X)` holds because a cold liveness probe reaches the health route before service initialization THEN the probe can initialize the complete service and external backends, causing side effects, delay, or restart loops (ISSUE-038).

1.39 WHEN `C-039(X)` holds because request, storage, knowledge, model cost, latency, disk, or incident load grows or a dependency fails THEN repository-defined SLOs, alerts, budgets, backpressure, backup/restore drills, capacity limits, and incident procedures are insufficient (ISSUE-039).

1.40 WHEN `C-040(X)` holds because a change reaches the main deployment branch THEN automatic deployment can rebuild and release it without mandatory test, safety, security, schema, provenance, staged-promotion, or rollback gates (ISSUE-040).

1.41 WHEN `C-041(X)` holds because the preserved `tests/test_pipeline.py` scenarios exercise indexed knowledge, retrieval support, pricing content, or instruction filtering THEN six product assertions fail and expected pipeline behavior is not demonstrated.

1.42 WHEN `C-042(X)` holds because the preserved 42-test `tests/test_hardening.py` cohort is executed under the bounded isolated runner THEN the batch reaches the 180-second limit without per-test terminal results, leaving those behaviors unverified.

1.43 WHEN `C-043(X)` holds because the created-output allowlist receives an alternate-case deliverable path THEN the exact-case validator accepts it after case-folding, so Property 4 remains failed and unresolved.

1.44 WHEN `C-044(X)` holds because complete test-ledger ordering and accounting are validated THEN Property 5 has only an interrupted run with no conclusive result or counterexample.

1.45 WHEN `C-045(X)` holds because a conditionally-ready generated readiness record omits its mandatory pre-production condition THEN the Property 9 generator labels that invalid record as expected-valid, preventing trustworthy readiness-property evidence.

### Expected Behavior (Correct)

2.1 WHEN `C-001(X)` holds THEN the system SHALL reject the oversized message before any partial analysis or persistence, or apply an explicitly disclosed safety-preserving segmentation policy, and SHALL provide a bounded response stating whether content was processed; tests SHALL place safety markers on both sides of the limit.

2.2 WHEN `C-002(X)` holds THEN the system SHALL stage pre-commit safety and analyzer changes and atomically commit or roll them back with the authoritative turn; a retry on the same instance SHALL match a fresh instance when no committed state exists.

2.3 WHEN `C-003(X)` holds THEN the system SHALL enforce a deterministic refusal or explicitly authorized least-context path before model invocation and SHALL exclude stored, cross-session, memory, summary, and retrieved context not required for that path.

2.4 WHEN `C-004(X)` holds THEN the system SHALL use stable document identity, exact-path targeting, staged commit, compensating rollback, and idempotent recovery so filesystem and index state converge after every injected save, refresh, removal, or unlink failure.

2.5 WHEN `C-005(X)` holds THEN the system SHALL refuse untrusted or shared-storage CLI operation unless an explicitly enforced trust mode supplies authorization, abuse controls, isolated identity, and isolated storage equivalent to the permitted boundary.

2.6 WHEN `C-006(X)` holds THEN the system SHALL distinguish subject, negation, quotation, and temporal context, SHALL use a calm clarification path when ambiguity remains, and SHALL reserve urgent self-risk handling for evidence that supports it; qualified safety review SHALL approve calibration.

2.7 WHEN `C-007(X)` holds THEN the system SHALL preserve a deterministic multi-turn trajectory and uncertainty state and SHALL select a conservative check-in or escalation response with redacted operational telemetry when semantic reasoning fails.

2.8 WHEN `C-008(X)` holds THEN the system SHALL block or safely replace each defined therapeutic-harm category through deterministic controls and a bounded fail-closed reviewer path; disabled, timed-out, malformed, or failed review SHALL NOT permit unproven output.

2.9 WHEN `C-009(X)` holds THEN the system SHALL treat summaries as untrusted derived data and SHALL validate safety, provenance, consistency, age, and correction status before persistence or reuse; invalid summaries SHALL be quarantined or replaced by authoritative recent turns.

2.10 WHEN `C-010(X)` holds THEN the system SHALL use verified locale-aware resources when locale and resource currency are established and SHALL otherwise use reviewed neutral local-emergency-services wording without asserting an inapplicable number.

2.11 WHEN `C-011(X)` holds THEN the system SHALL deterministically reject or rewrite exclusivity, dependency, coercion, diagnosis, treatment-authority, and replacement-of-care language and SHALL detect relevant cumulative multi-turn patterns under qualified safety review.

2.12 WHEN `C-012(X)` holds THEN the system SHALL key documents by a canonical root-bounded relative path or immutable identifier, SHALL detect migration collisions, and SHALL represent both same-named files without overwrite or ambiguity.

2.13 WHEN `C-013(X)` holds THEN the system SHALL return an explicit typed no-result state, SHALL inject no unrelated section, and SHALL require bounded uncertainty language rather than fabricated grounding.

2.14 WHEN `C-014(X)` holds THEN the system SHALL use unique staging files and inter-process coordination with version checks, or a concurrency-safe shared store, so concurrent cache persistence is serializable and crash recoverable.

2.15 WHEN `C-015(X)` holds THEN the system SHALL scan and classify stored/retrieved content, exclude instruction-like content by policy, carry provenance and trust tiers, use structural separation, and assemble only the minimum authorized context.

2.16 WHEN `C-016(X)` holds THEN the system SHALL propagate stable source identity and freshness metadata to the response and SHALL provide claim-level support or explicit ungrounded uncertainty that can be verified without exposing sensitive source content.

2.17 WHEN `C-017(X)` holds THEN the system SHALL enforce reviewed retention periods by data class across every supported backend, minimize derived health attributes, expire eligible records, and produce non-sensitive deletion evidence.

2.18 WHEN `C-018(X)` holds THEN the system SHALL migrate provenance where deterministically possible, quarantine ambiguous legacy records from retrieval, and SHALL NOT claim complete session deletion until attributable and quarantined residual state is explicitly accounted for.

2.19 WHEN `C-019(X)` holds THEN the system SHALL execute account deletion as a durable idempotent workflow with per-store checkpoints, bounded retries, observable residual state, and a completion receipt only after every required store verifies deletion.

2.20 WHEN `C-020(X)` holds THEN the system SHALL enforce data classification, least-privilege storage access, independently verified infrastructure encryption, field-level protection where required, separated keys, rotation, recovery, and migration validation without logging plaintext.

2.21 WHEN `C-021(X)` holds THEN the system SHALL require versioned reversible migrations, pre-change backups, restore acceptance tests, rollback rehearsal, schema compatibility checks, and orphan reconciliation before a schema-changing release proceeds.

2.22 WHEN `C-022(X)` holds THEN the system SHALL fail startup closed in public/production mode unless non-empty, separate user and administrator authorization controls are configured and validated; administrator operations SHALL NOT fall back to ordinary user authorization.

2.23 WHEN `C-023(X)` holds THEN the system SHALL apply privacy-preserving pre-identity and trusted-principal limits, distributed enforcement where multiple workers operate, and bounded model-cost controls so identity churn cannot multiply allowance.

2.24 WHEN `C-024(X)` holds THEN the system SHALL age stale buckets globally, cap limiter key cardinality, evict deterministically, expose non-sensitive eviction metrics, and remain memory bounded under generated one-time identities.

2.25 WHEN `C-025(X)` holds THEN the system SHALL enforce issued-at and expiry claims, rotation key identifiers, revocation or session epochs, bounded migration of legacy tokens, and secure re-issuance; expired or revoked tokens SHALL fail verification.

2.26 WHEN `C-026(X)` holds THEN the system SHALL stop tracking runtime data, block future additions, preserve minimal incident evidence, restrict repository and clone access, complete reviewed history/backup/clone exposure handling, and rotate affected credentials or identifiers when assessment requires it without opening or reproducing record values unnecessarily.

2.27 WHEN `C-027(X)` holds THEN the system SHALL emit and test a reviewed browser-security-header baseline, including content, transport, framing, and referrer protections, with staged compatibility checks and independently verified edge equivalence where applicable.

2.28 WHEN `C-028(X)` holds THEN the system SHALL enforce explicit notice or consent as applicable, minimum-necessary context, field classification and redaction, auditable content-free transmission metadata, verified provider retention/training/region controls, and a disabled path when those controls are unverified.

2.29 WHEN `C-029(X)` holds THEN the system SHALL run the default test suite only after a mandatory fixture redirects every writable and read-sensitive path to a temporary root and fails before import or execution on any path escape or live-state dependency.

2.30 WHEN `C-030(X)` holds THEN the test SHALL inject failure at the exact authoritative commit interface, assert that the patch was invoked, assert no response or secondary state was committed, and verify retry and rollback behavior.

2.31 WHEN `C-031(X)` holds THEN the system SHALL maintain a reviewed synthetic matrix covering every required language form, risk evolution, context source, harm category, and classifier/model/reviewer failure mode in single-turn and multi-turn execution.

2.32 WHEN `C-032(X)` holds THEN the system SHALL provide network-isolated provider contracts and disposable backend/deployment contract environments with explicit destructive-operation allowlists, while live validation remains separately authorized and non-secret.

2.33 WHEN `C-033(X)` holds THEN the system SHALL use one authoritative test manifest that classifies every entry point into explicit lanes, records eligibility and freshness, runs or explicitly skips each entry, and marks historical outputs non-authoritative.

2.34 WHEN `C-034(X)` holds THEN the system SHALL move synchronization, rate state, safety continuity, cache invalidation, and document coordination to shared durable primitives or enforce measured single-worker semantics; cross-worker tests SHALL prove convergence before scale-out.

2.35 WHEN `C-035(X)` holds THEN the system SHALL place active knowledge and cache state on explicitly durable or reconstructable storage, reconcile it at startup, and prove document visibility and recovery across workers and restarts.

2.36 WHEN `C-036(X)` holds THEN the system SHALL define connection ownership and invoke idempotent close hooks on shutdown, reload, tests, and rolling deployment without interrupting committed work.

2.37 WHEN `C-037(X)` holds THEN the system SHALL install from a reviewed hash-locked transitive set or equivalent verified artifacts, produce an SBOM, enforce trusted-source policy, and update dependencies through a controlled vulnerability and compatibility process.

2.38 WHEN `C-038(X)` holds THEN the system SHALL expose side-effect-free liveness separately from bounded readiness, initialize dependencies explicitly, report only redacted status, and honor startup deadlines without probe-triggered service construction.

2.39 WHEN `C-039(X)` holds THEN the system SHALL enforce reviewed SLOs, redacted alerts, model budgets, backpressure, disk and connection thresholds, capacity evidence, backup/restore drills, incident ownership, and safe degraded behavior before production acceptance.

2.40 WHEN `C-040(X)` holds THEN the system SHALL promote immutable tested artifacts only after mandatory test, safety, security, privacy, schema, migration, and provenance gates, with staged rollout, canary criteria, automatic rollback criteria, and no direct ungated production deployment from main.

2.41 WHEN `C-041(X)` holds THEN the fixed pipeline SHALL index expected synthetic knowledge, preserve relevant grounded content including configured price facts, reject instruction-like material, and pass all six previously failing assertions without weakening their intended safety or retrieval claims.

2.42 WHEN `C-042(X)` holds THEN the runner SHALL partition or otherwise bound the hardening cohort so every one of the 42 tests receives exactly one conclusive terminal classification with retained redacted output, and no batch timeout SHALL be represented as an individual pass or product failure.

2.43 WHEN `C-043(X)` holds THEN the validator SHALL accept only the exact permitted case-aware root deliverable paths and root-bounded active-run findings descendants and SHALL reject alternate-case, traversal, prefix, sibling, link-escape, and pre-existing-file matches; Property 4 SHALL pass a retained rerun.

2.44 WHEN `C-044(X)` holds THEN every discovered test SHALL receive one pre-execution eligibility decision, every eligible execution SHALL have prior passing isolation attestation and one terminal audit/native result, and every ineligible test SHALL remain unexecuted with a reason; Property 5 SHALL complete and pass with retained output.

2.45 WHEN `C-045(X)` holds THEN the readiness property generator SHALL classify a conditionally-ready record as valid only when mandatory conditions and verification gates are present, SHALL retain the corrected counterexample history, and Property 9 SHALL pass without weakening fail-closed readiness rules.

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a message is within the supported size and does not satisfy `C-001(X)` THEN the system SHALL CONTINUE TO normalize, analyze, persist, and answer the complete message without newly truncating valid content.

3.2 WHEN a turn commits successfully and does not satisfy `C-002(X)` THEN the system SHALL CONTINUE TO preserve authoritative idempotency, owner-scoped history, and durable safety-state continuity.

3.3 WHEN input is benign and authorized and does not satisfy `C-003(X)` or `C-015(X)` THEN the system SHALL CONTINUE TO use relevant, minimum-necessary recent history, memory, summary, and knowledge context without cross-user disclosure.

3.4 WHEN a document has a unique stable identity and all lifecycle operations succeed THEN the system SHALL CONTINUE TO ingest, retrieve, refresh, list, and delete that exact document while preserving supported file-type and size restrictions.

3.5 WHEN the CLI remains explicitly local, trusted, and isolated THEN the system SHALL CONTINUE TO provide bounded administrative or development functionality without weakening production controls.

3.6 WHEN language expresses current self-directed acute risk THEN the system SHALL CONTINUE TO route deterministically to empathetic urgent support; contextual-disambiguation fixes SHALL NOT reduce the explicit-risk safety floor.

3.7 WHEN language is non-crisis distress THEN the system SHALL CONTINUE TO provide supportive, non-diagnostic, non-coercive help with calibrated urgency and no claim of professional replacement.

3.8 WHEN safety classifiers, reviewers, models, caches, or storage fail THEN the system SHALL CONTINUE TO fail safely with bounded user-visible behavior; availability SHALL NOT take precedence over unproven mental-health output.

3.9 WHEN locale-aware resources are verified and applicable THEN the system SHALL CONTINUE TO provide the reviewed resource and continued-engagement guidance without introducing conflicting numbers.

3.10 WHEN retrieval has relevant support THEN the system SHALL CONTINUE TO rank and bound relevant sections, preserve source identity, and avoid adding unsupported claims; no-result fixes SHALL NOT suppress valid matches.

3.11 WHEN records are within their approved retention period and the user has not requested deletion THEN the system SHALL CONTINUE TO provide owner-scoped continuity only for the documented purpose and minimum necessary fields.

3.12 WHEN session or account deletion completes successfully THEN the system SHALL CONTINUE TO prevent deleted identities or data from being rehydrated, and retries SHALL remain idempotent.

3.13 WHEN legacy data, tokens, cache metadata, schemas, or document identities are migrated THEN the system SHALL CONTINUE TO preserve attributable valid records, SHALL NOT silently discard or merge ambiguous records, SHALL quarantine uncertainty, and SHALL produce non-sensitive reconciliation totals.

3.14 WHEN encryption or key rotation is introduced THEN the system SHALL CONTINUE TO support authorized reads during a bounded migration, SHALL verify rollback and recovery before cutover, and SHALL NOT write plaintext copies, key material, or decrypted values to logs or reports.

3.15 WHEN repository or history remediation for ISSUE-026 is performed THEN the system SHALL CONTINUE TO preserve minimal chain-of-custody evidence, SHALL NOT print or inspect conversation values unnecessarily, and SHALL require reviewed backup and clone handling before declaring containment complete.

3.16 WHEN authentication, token expiry, revocation, or rate limiting is strengthened THEN the system SHALL CONTINUE TO use constant-time secret comparison, strong random identifiers, owner scoping, privacy-preserving signals, and bounded errors without logging credentials or token values.

3.17 WHEN browser and deployment controls are introduced THEN the system SHALL CONTINUE TO render user chat text safely, protect cookies appropriately, expose only intended public endpoints, and avoid leaking internal exception or configuration details.

3.18 WHEN external model processing is permitted under verified controls THEN the system SHALL CONTINUE TO send only the minimum authorized redacted context and SHALL NOT record provider keys, personal content, inferred health details, or secret values in telemetry.

3.19 WHEN tests execute THEN the system SHALL CONTINUE TO use synthetic or redacted fixtures, fake providers where applicable, explicit non-watch single runs, bounded process trees, denied external egress, and temporary paths; tests SHALL NOT read `.env`, production data, live services, or tracked runtime databases.

3.20 WHEN SQLite and Mongo behavior is supported THEN the system SHALL CONTINUE TO preserve owner authorization, transaction/idempotency guarantees, deletion semantics, and equivalent safety outcomes across backends, with differences explicitly tested rather than assumed.

3.21 WHEN multi-worker operation is enabled after coordination controls pass THEN the system SHALL CONTINUE TO produce one authoritative turn per request identifier, serialize same-session mutations, maintain consistent rate and safety state, and converge document/cache visibility.

3.22 WHEN single-worker containment is used before distributed coordination passes THEN the system SHALL CONTINUE TO enforce measured capacity, safe timeouts, and documented rollback without representing containment as completed durable remediation.

3.23 WHEN a remediation changes persistent data, identity, cryptography, storage paths, schemas, or deployment topology THEN the system SHALL CONTINUE TO require inventory, backup, dry-run, compatibility check, staged migration, reconciliation, rollback rehearsal, and accountable approval before irreversible cutover.

3.24 WHEN a remediation affects mental-health classification, crisis wording, output filtering, summaries, memory, or external context THEN the system SHALL CONTINUE TO require qualified safety review and retained regression evidence for false negatives, false positives, over-escalation, under-escalation, cumulative harm, dependency, privacy, and boundary harms.

3.25 WHEN a remediation affects authentication, privacy, sensitive storage, provider transmission, Git history, deletion, or browser boundaries THEN the system SHALL CONTINUE TO require security/privacy review covering prevention, detection, response, lifecycle, least privilege, incident handling, and secret or identifier rotation applicability.

3.26 WHEN acceptance evidence is generated THEN the system SHALL CONTINUE TO redact sensitive values, use synthetic identifiers and records, retain commands and outcomes without environment values, and distinguish repository-proven, test-observed, inferred, and externally validated claims.

3.27 WHEN remediation work begins THEN the system SHALL CONTINUE TO apply dependency order: P0 controls ISSUE-008, ISSUE-022, and ISSUE-026 first; P1 controls and preserved test blockers only after P0 containment; P2 only after affected P1 prerequisites; P3 after test-accounting foundations; and readiness verification last.

3.28 WHEN two remediations touch the same safety, identity, persistence, document, cache, deployment, or test boundary THEN the system SHALL CONTINUE TO stage them as separately reviewable changes with explicit prerequisites and integration gates rather than applying an unsafe simultaneous rewrite.

3.29 WHEN a stage fails acceptance, migration reconciliation, safety review, security review, or rollback criteria THEN the system SHALL CONTINUE TO stop dependent stages, retain redacted failure evidence, restore only a known-safe state, and SHALL NOT re-enable an exposed credential, unsafe output path, tracked runtime database, or incompatible schema.

3.30 WHEN final readiness is evaluated THEN the system SHALL CONTINUE TO return `not-ready` until every P0 and P1 finding, all 48 repository-test blockers, Properties 4 and 5, the corrected Property 9 evidence, required external validations, and exact integrity/output gates have conclusive accepted evidence.

3.31 WHEN final readiness gates pass THEN the system SHALL CONTINUE TO retain P2 and P3 disposition evidence, residual risks, monitoring and rollback ownership, and SHALL NOT infer external provider, infrastructure, encryption, emergency-resource, backup, restore, or edge behavior from repository evidence alone.

3.32 WHEN any requirement is implemented or verified THEN the system SHALL CONTINUE TO avoid modifying or exposing `.env` values, live credentials, production records, user conversations, or sensitive database contents; only redacted metadata and synthetic evidence are permitted.
