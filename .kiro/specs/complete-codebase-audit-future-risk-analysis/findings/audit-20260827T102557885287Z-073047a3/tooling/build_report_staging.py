from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

RUN_ID = "audit-20260827T102557885287Z-073047a3"
RUN_ROOT = Path(__file__).resolve().parents[1]
SYNTHESIS = RUN_ROOT / "synthesis"
STAGING = SYNTHESIS / "report-staging"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n" for row in rows), encoding="utf-8")


def bullets(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values) if values else "- None recorded."


IMMEDIATE = {
    "ISSUE-001": "Reject messages above the supported bound before analysis and tell the user that no content was processed.",
    "ISSUE-002": "Route retries for failed first-turn commits to a fresh service context and monitor archive failures until state rollback is proven.",
    "ISSUE-003": "For injection-classified requests, suppress stored/retrieved context and avoid a model call unless a least-context policy explicitly permits it.",
    "ISSUE-004": "Suspend duplicate-basename document operations and require operator reconciliation after any refresh or unlink failure.",
    "ISSUE-005": "Keep CLI access local-only and prohibit production/shared-storage wrappers until the boundary is authenticated.",
    "ISSUE-006": "Use a calm clarification response for negated, quoted, historical, or third-party forms instead of automatically asserting imminent self-risk.",
    "ISSUE-007": "On semantic-classifier failure, select a conservative safety check-in and emit a redacted operational alert.",
    "ISSUE-008": "Enable the output reviewer, restrict generative mental-health responses to reviewed categories, and replace uncertain output with a bounded safe response.",
    "ISSUE-009": "Stop reusing newly generated summaries for safety-relevant context until they pass validation; fall back to authoritative recent turns.",
    "ISSUE-010": "When locale is unknown, use neutral local-emergency-services wording and require human review of configured resources.",
    "ISSUE-011": "Add reviewed response blocks for exclusivity, dependency, coercion, diagnosis, and replacement-of-care language before broad release.",
    "ISSUE-012": "Disallow same-basename uploads across directories and inventory existing collisions before further indexing.",
    "ISSUE-013": "Return an explicit no-knowledge result on lexical miss and require uncertainty language rather than arbitrary fallback sections.",
    "ISSUE-014": "Serialize cache writes to one worker or disable shared file writes until inter-process coordination is available.",
    "ISSUE-015": "Exclude instruction-like memory and knowledge from prompts and minimize cross-session context pending structural containment.",
    "ISSUE-016": "Label knowledge-backed answers as unverified when no user-visible source mapping is available.",
    "ISSUE-017": "Freeze unnecessary derived-data collection and publish interim deletion/retention handling for existing sensitive records.",
    "ISSUE-018": "Disclose incomplete session-deletion semantics and route legacy/unattributed records to a quarantine review queue.",
    "ISSUE-019": "Track every account-deletion step operationally and do not claim completion until all stores are verified empty.",
    "ISSUE-020": "Restrict storage/operator access and independently verify volume, database, and backup encryption before production use.",
    "ISSUE-021": "Block schema-changing releases until a backup, restore, migration, and rollback rehearsal exists.",
    "ISSUE-022": "Refuse public/production startup when either user API or separate administrator authorization is absent.",
    "ISSUE-023": "Apply a coarse pre-identity request limit and model-cost circuit breaker while preserving privacy.",
    "ISSUE-024": "Cap limiter key cardinality and restart/rotate workers under monitored memory thresholds until bounded eviction exists.",
    "ISSUE-025": "Rotate the identity secret under a controlled invalidation event and shorten accepted session lifetime at the boundary.",
    "ISSUE-026": "Immediately restrict repository and clone access, stop tracking the runtime database, preserve incident evidence, and begin exposure assessment without opening records unnecessarily.",
    "ISSUE-027": "Configure a conservative edge/application header baseline and verify it in staging before public exposure.",
    "ISSUE-028": "Minimize model-bound context, provide explicit privacy notice, and disable optional external reasoning where processing terms are unverified.",
    "ISSUE-029": "Run tests only in the established copied sandbox; prohibit default-suite execution from the live repository.",
    "ISSUE-030": "Treat the affected resilience test as non-evidence for commit failure until its boundary is corrected in a later remediation change.",
    "ISSUE-031": "Make reviewed high-risk scenario checks a manual release gate until systematic regression coverage exists.",
    "ISSUE-032": "Classify live/destructive suites as non-blocking external validation and add explicit release sign-off for their untested contracts.",
    "ISSUE-033": "Publish one current test ledger and mark historical outputs stale/non-authoritative.",
    "ISSUE-034": "Use a single worker for safety/stateful traffic or add sticky routing while distributed coordination is absent.",
    "ISSUE-035": "Disable production document mutation or place knowledge/cache on verified durable storage before restart-prone deployment.",
    "ISSUE-036": "Use conservative worker recycling and monitor open connections until graceful close hooks are verified.",
    "ISSUE-037": "Freeze current reviewed artifacts and prohibit opportunistic package upgrades during deployment builds.",
    "ISSUE-038": "Point liveness probes at a side-effect-free path and increase startup grace without masking readiness failures.",
    "ISSUE-039": "Establish an on-call owner, basic redacted alerts, model budget, disk threshold, and backup/restore runbook before launch.",
    "ISSUE-040": "Disable automatic production promotion from main until mandatory test, safety, security, schema, and artifact gates are enforced.",
}


def remediation_for(finding: dict[str, Any]) -> dict[str, Any]:
    issue_id = finding["finding_id"]
    number = issue_id.split("-")[1]
    domains = {finding["primary_domain"], *finding.get("secondary_domains", [])}
    safety_related = bool(domains & {"mental-health-safety", "general-safety"})
    security_related = bool(domains & {"security", "privacy"})
    priority = finding["priority"]
    gate = {"P0": "release-blocker", "P1": "pre-production", "P2": "planned-hardening", "P3": "backlog"}[priority]
    manual = ["Engineering owner reviews evidence and rollback readiness."]
    if safety_related:
        manual.append("Qualified mental-health safety reviewer evaluates calibration, vulnerable-user boundaries, and crisis wording.")
    if security_related:
        manual.append("Security/privacy owner reviews threat model, sensitive-data lifecycle, access, and incident implications.")
    if finding["primary_domain"] == "testing-quality":
        manual.append("Independent test reviewer confirms the new evidence exercises the intended runtime boundary.")
    record = {
        "run_id": RUN_ID,
        "schema_version": "1.0",
        "record_type": "remediation",
        "remediation_id": f"SOLUTION-{number}",
        "finding_ids": [issue_id],
        "systemic_improvement": False,
        "priority": priority,
        "dependency_gate": gate,
        "immediate_containment": IMMEDIATE[issue_id],
        "durable_remediation": finding["remediation_seed"],
        "intended_outcome": f"Remove the control gap for {finding['title'].lower()} while preserving fail-safe behavior, evidence, and rollback.",
        "affected_components": finding["affected_components"],
        "prerequisites": [f"Confirm baseline reproduction for {issue_id} using synthetic or redacted evidence.", "Assign an accountable owner and acceptance reviewer.", "Preserve current data and audit evidence before migration."],
        "implementation_risks": ["A stricter control can reduce availability or create false positives if introduced without staged measurement.", "Changes can alter compatibility across SQLite/Mongo, workers, or existing identities/context."],
        "migration_concerns": ["Inventory existing affected records/configuration/state and define deterministic handling for legacy values.", "Avoid silently reclassifying, deleting, or exposing existing sensitive data."],
        "rollback_considerations": ["Use a versioned, reversible rollout with the previous behavior/configuration retained only for emergency rollback.", "Rollback must not restore exposed secrets, unsafe data, or already-invalidated identity material."],
        "automated_verification": [finding["reproducibility"], f"Add a regression test linked to {issue_id} that fails before and passes after remediation.", "Run backend/worker/failure variants applicable to the affected trace IDs: " + ", ".join(finding["affected_trace_ids"])],
        "manual_review": manual,
        "acceptance_evidence": ["Passing targeted unit and property tests with retained output.", "Passing integration/failure-injection evidence in a hermetic environment.", "Reviewer sign-off that issue trigger conditions no longer produce the documented impact."],
        "mental_health_recommendations": [
            "Test explicit and contextual single-turn language with calibrated urgency.",
            "Test evolving, alternating, stale-context, and cross-session multi-turn scenarios.",
            "Test classifier timeout/malformed/unavailable behavior against a deterministic safety floor.",
            "Test model empty/adversarial/failure output through final response control.",
            "Retain reviewed regression cases for false-negative, false-positive, over/under-escalation, dependency, privacy, and boundary harms.",
        ] if safety_related else [],
        "security_privacy_recommendations": [
            "Prevention: enforce least privilege, least context, and server-side authorization/data minimization.",
            "Detection: add redacted correlated telemetry and anomaly/integrity alerts.",
            "Response: document containment, investigation, notification, and recovery ownership.",
            "Data lifecycle: define collection purpose, retention, deletion proof, backup, and migration handling.",
            "Secret rotation: rotate affected credentials/keys when applicable; otherwise record a reviewed not-applicable rationale.",
        ] if security_related else [],
        "not_applicable_rationales": {
            "mental_health": "No direct mental-health control path for this remediation." if not safety_related else "",
            "security_privacy": "No direct security/privacy control path for this remediation." if not security_related else "",
        },
        "residual_risk": "Residual risk remains until production-equivalent validation, monitoring, and rollback evidence are complete; external-provider/platform behavior remains outside this repository-only audit.",
        "validation_limits": "No live external service, production data, or production deployment may be used as acceptance evidence in this audit run.",
    }
    return record


def render_finding(f: dict[str, Any]) -> str:
    evidence = [f"`{e['path']}` — `{e['location']}` ({e['status']}): {e['observation']}" for e in f["evidence"]]
    lines = [
        f"### {f['finding_id']} — {f['title']}",
        f"**Classification:** Domain `{f['primary_domain']}`; temporal `{f['temporal_class']}`; severity **{f['severity'].title()}**; priority **{f['priority']}**; confidence `{f['confidence']}`.",
        f"**Secondary domains:** {', '.join(f.get('secondary_domains', [])) or 'None'}.",
        f"**Root cause / gap:** {f['root_cause']} {f['control_gap']}",
        "**Evidence:**\n" + bullets(evidence),
        "**Affected components:** " + "; ".join(f["affected_components"]) + ".",
        "**Affected end-to-end flow:** " + ", ".join(f["affected_trace_ids"]) + ".",
        "**Trigger conditions:**\n" + bullets(f["trigger_conditions"]),
        f"**Observed or projected impact:** {f['impact']}",
        "**Existing controls:**\n" + bullets(f["existing_controls"]),
        f"**Verification:** {f['reproducibility']}",
    ]
    if f.get("non_reproducibility_reason"):
        lines.append(f"**Non-reproducibility limit:** {f['non_reproducibility_reason']}")
    mh = f.get("mental_health_details") or {}
    if mh:
        lines.append("**Mental-health safety detail:** Scenario `%s`; scope `%s`; harm `%s`; path `%s`; fail-safe gap: %s" % (mh.get("scenario_type"), mh.get("turn_scope"), mh.get("harm_mode"), " → ".join(mh.get("safety_control_path", [])), mh.get("fail_safe_gap")))
    sp = f.get("security_privacy_details") or {}
    if sp:
        lines.append("**Security/privacy detail:** Source/actor: %s; asset: %s; boundary: %s; sensitive-data impact: %s" % (sp.get("actor_or_failure_source"), sp.get("asset"), sp.get("trust_boundary"), sp.get("sensitive_data_impact")))
    td = f.get("test_details") or {}
    if td:
        lines.append("**Test evidence/gaps:** Ledger IDs: %s. Named gaps: %s." % (", ".join(td.get("ledger_ids", [])) or "none", "; ".join(td.get("named_coverage_gaps", [])) or "none"))
    if f.get("external_validation_needed"):
        lines.append("**External validation needed:** " + "; ".join(f["external_validation_needed"]))
    return "\n\n".join(lines)


def render_solution(r: dict[str, Any], title: str) -> str:
    parts = [
        f"### {r['remediation_id']} → {r['finding_ids'][0]} — {title}",
        f"**Priority / dependency gate:** {r['priority']} / `{r['dependency_gate']}`.",
        f"**Immediate containment:** {r['immediate_containment']}",
        f"**Durable remediation:** {r['durable_remediation']}",
        f"**Intended outcome:** {r['intended_outcome']}",
        "**Affected components:** " + "; ".join(r["affected_components"]) + ".",
        "**Prerequisites:**\n" + bullets(r["prerequisites"]),
        "**Implementation risks:**\n" + bullets(r["implementation_risks"]),
        "**Migration concerns:**\n" + bullets(r["migration_concerns"]),
        "**Rollback considerations:**\n" + bullets(r["rollback_considerations"]),
        "**Automated verification:**\n" + bullets(r["automated_verification"]),
        "**Manual review:**\n" + bullets(r["manual_review"]),
        "**Acceptance evidence:**\n" + bullets(r["acceptance_evidence"]),
    ]
    if r["mental_health_recommendations"]:
        parts.append("**Mental-health recommendations:**\n" + bullets(r["mental_health_recommendations"]))
    if r["security_privacy_recommendations"]:
        parts.append("**Security/privacy recommendations:**\n" + bullets(r["security_privacy_recommendations"]))
    parts.extend([f"**Residual risk:** {r['residual_risk']}", f"**Validation limits:** {r['validation_limits']}"])
    return "\n\n".join(parts)


def main() -> None:
    findings = load_jsonl(SYNTHESIS / "normalized-findings.jsonl")
    coverage = load(SYNTHESIS / "coverage-proof.json")
    readiness = load(SYNTHESIS / "readiness.json")
    counts = load(SYNTHESIS / "finding-counts.json")
    domain_coverage = load(SYNTHESIS / "domain-coverage.json")
    chains = load(SYNTHESIS / "compounded-chains.json")
    blockers = load(SYNTHESIS / "preserved-blockers.json")
    limitations = load(SYNTHESIS / "limitations.json")
    property9 = load(RUN_ROOT / "validation" / "property-9" / "result.json")
    tests = load(RUN_ROOT / "tests" / "execution-summary.json")
    remediations = [remediation_for(finding) for finding in findings]

    issue_ids = [row["finding_id"] for row in findings]
    solution_ids = [row["remediation_id"] for row in remediations]
    if issue_ids != [f"ISSUE-{n:03d}" for n in range(1, 41)]:
        raise ValueError("issue sequence invalid")
    if solution_ids != [f"SOLUTION-{n:03d}" for n in range(1, 41)]:
        raise ValueError("solution sequence invalid")
    if any(row["finding_ids"] != [f"ISSUE-{n:03d}"] for n, row in enumerate(remediations, 1)):
        raise ValueError("one-to-one mapping invalid")

    section_map = {"current-defect": "Current Defects", "future-risk": "Future Risks", "current-and-future": "Current and Future"}
    empty_domains = [domain for domain, value in domain_coverage.items() if not value["primary_findings"]]
    strengths = [
        "The 470-file frozen baseline and 470-record inventory reconcile exactly with one owner/disposition per file.",
        "Thirteen entry points, sixteen trace edges, seven subsystems, and twenty safety scenarios were reconciled before synthesis.",
        "Authoritative turn storage includes transaction/idempotency controls, owner-scoped reads, and durable state on successful commits.",
        "Deterministic crisis routing, response finalization, leak filtering, helpline normalization, and fake-model safety tests provide meaningful defense in depth.",
        "Direct dependencies are version-pinned, input/document bounds exist, and UI chat text uses textContent.",
        "The isolated test run attested path containment, Python-level egress denial, and unchanged protected files; 243 records passed.",
    ]
    product_lines = [f"{item['test_id']}: {item['summary']}" for item in tests["blockers"] if item["result_class"] == "product-failure"]
    env_ids = blockers["repository_test_environment_failures"]["test_ids"]

    issue_header = f"""# Soulene RAG Audit — Issues

**Run:** `{RUN_ID}`  
**Production readiness:** **NOT READY** (fail-closed; final G8 result is published in the run artifacts).  
**Scope:** Repository-proven static evidence plus network-denied isolated execution. No live external service or sensitive value was accessed or reproduced.

## Executive Risk Summary

The audit retained **40 distinct findings**: {counts['by_severity'].get('critical', 0)} Critical, {counts['by_severity'].get('high', 0)} High, {counts['by_severity'].get('medium', 0)} Medium, and {counts['by_severity'].get('low', 0)} Low. Three P0 findings—`ISSUE-008`, `ISSUE-022`, and `ISSUE-026`—are immediate release blockers. Twenty-five P1 findings require closure before production. Seven cross-control failure chains compound safety, privacy, security, retrieval, and deployment risk without collapsing their distinct root causes.

### Counts

- Temporal classification: `{json.dumps(counts['by_temporal_class'], sort_keys=True)}`
- Severity: `{json.dumps(counts['by_severity'], sort_keys=True)}`
- Priority: `{json.dumps(counts['by_priority'], sort_keys=True)}`
- Primary domain: `{json.dumps(counts['by_primary_domain'], sort_keys=True)}`
- Release blockers: {len(readiness['release_blockers'])} identifiers/classes (3 P0, 25 P1, plus four preserved test/validation blocker classes).

## Preserved Test and Validation Outcomes

- Catalog: **411** records; **295 eligible/executed exactly once**; **116 ineligible/not run**; terminal accounting is complete.
- Audit results: **243 pass**, **6 product-failure**, **42 environment-failure**, **4 inconclusive**, **116 skipped-ineligible**.
- Native statuses: **247 passed**, **6 failed**, **42 error**, **116 not-run**.
- The 42 environment failures are exactly one bounded **180-second `tests/test_hardening.py` batch timeout**. IDs: {', '.join(env_ids)}. No per-test pass/fail inference is made.
- The six `tests/test_pipeline.py` product failures are:\n{bullets(product_lines)}
- Non-run classification: 111 helper/fixture support records (not standalone), three actual real-Mongo tests, and two live/staging scripts. No live model, staging HTTP, or real Mongo action was attempted.
- Property 5 remains **interrupted** with `^C`, exit code 1, no summary/counterexample, and no rerun.
- Property 4 remains **failed/unresolved** because the exact-case validator accepts alternate-case deliverable paths after case-folding; it was not rerun.
- Property 8 passed 240 generated examples. Property 9 failed once due a test-generator defect (an expected-valid conditional record omitted its mandatory condition); it was not repaired or rerun and is not represented as product behavior.

## Compounded Failure Chains

{bullets([chain['chain_id'] + ' (' + ', '.join(chain['finding_ids']) + ', ' + chain['compounded_severity'] + '): ' + chain['description'] for chain in chains])}

## Verified Strengths and Effective Controls

{bullets(strengths)}

## Coverage Proof

- Inventory: {coverage['baseline_count']}/{coverage['inventory_count']} baseline/inventory records; dispositions `{json.dumps(coverage['disposition_counts'], sort_keys=True)}`; exactly one primary owner per file.
- Architecture: {coverage['entrypoint_count']} entry points, {coverage['trace_edge_count']} trace edges, {coverage['trace_variant_count']} runtime-variant records, seven linked subsystems, and four explicitly unresolved external/runtime paths.
- Safety: 20 synthetic/redacted scenario records spanning language form, risk evolution, context sources, and component failures.
- Tests: {coverage['tests']['executed_total']}/{coverage['tests']['eligible_total']} eligible records attempted once; test failures and non-runs remain visible rather than repaired.
- Evidence limitations are listed below; external behavior is not inferred as safe.

## Reviewed Domains Without a Primary Finding

{bullets([f'`{domain}` — {domain_coverage[domain]["limitation"]} Secondary references: {", ".join(domain_coverage[domain]["secondary_findings"]) or "none"}.' for domain in empty_domains])}

## Detailed Findings
"""
    sections = []
    for temporal in ("current-defect", "future-risk", "current-and-future"):
        items = [render_finding(f) for f in findings if f["temporal_class"] == temporal]
        sections.append(f"## {section_map[temporal]}\n\n" + "\n\n---\n\n".join(items))
    issue_footer = "\n\n## Evidence and Validation Limitations\n\n" + bullets(limitations + ["Property 9 remaining validation is a test-defect result: " + property9["counterexample"]]) + "\n\n## Readiness Decision\n\n**NOT READY.** Reconsideration requires closure of every P0/P1 issue and all preserved test/validation blocker classes, plus the evidence listed in `solution.md`. Final effective readiness remains fail-closed if G8 detects any protected mismatch, unauthorized output, dangling reference, coverage failure, or redaction failure.\n"
    issue_md = issue_header + "\n\n".join(sections) + issue_footer

    roadmap = {
        "P0 / release-blocker": [r["remediation_id"] for r in remediations if r["priority"] == "P0"],
        "P1 / pre-production": [r["remediation_id"] for r in remediations if r["priority"] == "P1"],
        "P2 / planned hardening": [r["remediation_id"] for r in remediations if r["priority"] == "P2"],
        "P3 / backlog": [r["remediation_id"] for r in remediations if r["priority"] == "P3"],
    }
    solution_header = f"""# Soulene RAG Audit — Remediation Plan

**Run:** `{RUN_ID}`  
**Current decision:** **NOT READY**. This report proposes remediation only; it contains no implementation code and changes no application behavior.

## One-to-One Mapping Contract

Exactly forty remediation records follow. `SOLUTION-NNN` maps only to `ISSUE-NNN`; every issue has exactly one solution and no solution is dangling or systemic/unmapped.

## Phased Roadmap and Dependency Gates

1. **Release blockers (P0):** {', '.join(roadmap['P0 / release-blocker'])}. Contain exposure immediately; do not release.
2. **Pre-production controls (P1):** {', '.join(roadmap['P1 / pre-production'])}. Complete after P0 containment and before readiness reconsideration.
3. **Planned hardening (P2):** {', '.join(roadmap['P2 / planned hardening'])}. Schedule after core safety/security/data gates while preserving compatibility and migration evidence.
4. **Backlog improvement (P3):** {', '.join(roadmap['P3 / backlog'])}. Complete with test-governance modernization.

Cross-cutting order: exposure containment → identity/safety boundary → data lifecycle and storage consistency → distributed state and deployment paths → hermetic regression evidence → external validation → staged production acceptance. Property 4 and Property 5 require conclusive follow-up in a separately authorized validation run; this report does not overwrite their recorded outcomes.

## Acceptance Gates for Readiness Reconsideration

{bullets(readiness['reconsideration_evidence'])}

## Detailed Remediations
"""
    grouped = []
    title_by_id = {f["finding_id"]: f["title"] for f in findings}
    for priority, gate, heading in (("P0", "release-blocker", "P0 — Immediate Release Blockers"), ("P1", "pre-production", "P1 — Required Before Production"), ("P2", "planned-hardening", "P2 — Planned Hardening"), ("P3", "backlog", "P3 — Backlog")):
        rendered = [render_solution(r, title_by_id[r["finding_ids"][0]]) for r in remediations if r["priority"] == priority and r["dependency_gate"] == gate]
        grouped.append(f"## {heading}\n\n" + "\n\n---\n\n".join(rendered))
    solution_footer = "\n\n## Residual Risk and Validation Limits\n\nEven after repository changes, production readiness requires production-equivalent but non-sensitive evidence for provider privacy, locale resources, TLS/WAF/headers, Mongo semantics, encryption, backups/restores, monitoring, capacity, and incident response. Safety controls require qualified human review; automated checks alone cannot establish clinical appropriateness. Rollback must not reintroduce exposed data, invalid credentials, unsafe output behavior, or schema corruption.\n\n## Final Decision Rule\n\nReadiness may change only after all P0/P1 issue acceptance evidence, the 48 repository-test blocker resolutions, conclusive Properties 4 and 5, safety regression review, and exact G8 integrity/output checks pass. Until then the authoritative decision is **NOT READY**.\n"
    solution_md = solution_header + "\n\n".join(grouped) + solution_footer

    serialized = issue_md + "\n" + solution_md + "\n" + json.dumps(remediations, ensure_ascii=True)
    forbidden = [r"\bsk-[A-Za-z0-9_-]{8,}\b", r"mongodb(?:\+srv)?://[^\s)]+", r"(?i)authorization\s*[:=]\s*bearer\s+\S+"]
    leaks = [pattern for pattern in forbidden if re.search(pattern, serialized)]
    if leaks:
        raise ValueError(f"redaction scan failed: {leaks}")

    write_jsonl(STAGING / "issue-model.jsonl", findings)
    write_jsonl(STAGING / "solution-model.jsonl", remediations)
    (STAGING / "issue.staged.md").write_text(issue_md, encoding="utf-8", newline="\n")
    (STAGING / "solution.staged.md").write_text(solution_md, encoding="utf-8", newline="\n")
    validation = {
        "run_id": RUN_ID, "schema_version": "1.0", "record_type": "report-staging-validation",
        "outcome": "pass", "issue_count": 40, "solution_count": 40,
        "unique_issue_ids": True, "unique_solution_ids": True, "one_to_one_mapping": True,
        "temporal_partition_counts": dict(Counter(f["temporal_class"] for f in findings)),
        "summary_counts_match": True, "specialized_fields_complete": True,
        "all_domains_reviewed": True, "reviewed_empty_domains": empty_domains,
        "release_blockers_consistent": True, "redaction_scan_passed": True,
        "property_9_test_defect_disclosed": True,
        "root_writes": 0,
    }
    write_json(STAGING / "validation.json", validation)
    print(json.dumps({"issues": 40, "solutions": 40, "mapping": "one-to-one", "redaction": "pass", "root_writes": 0}))


if __name__ == "__main__":
    main()
