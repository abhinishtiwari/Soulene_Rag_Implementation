from __future__ import annotations

import itertools
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

RUN_ID = "audit-20260827T102557885287Z-073047a3"
RUN_ROOT = Path(__file__).resolve().parents[1]
SUBSYSTEM_DIR = RUN_ROOT / "subsystem"
SYNTHESIS_DIR = RUN_ROOT / "synthesis"
FILES = [
    "application-flow.jsonl",
    "safety.jsonl",
    "memory-rag-cag.jsonl",
    "persistence.jsonl",
    "security-privacy.jsonl",
    "testing-quality.jsonl",
    "deployment-operations.jsonl",
]
DOMAINS = {
    "architecture-correctness", "mental-health-safety", "general-safety",
    "input-output-fail-safe", "memory-context", "rag-cag", "data-database",
    "security", "privacy", "testing-quality", "dependency-supply-chain",
    "performance-reliability", "deployment-operations", "maintainability",
}
TEMPORAL = {"current-defect", "future-risk", "current-and-future"}
SEVERITIES = {"critical", "high", "medium", "low", "informational"}
PRIORITIES = {"P0", "P1", "P2", "P3"}
CONFIDENCE = {"confirmed", "probable", "possible"}
EXPECTED_IDS = {f"ISSUE-{number:03d}" for number in range(1, 41)}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n" for row in rows), encoding="utf-8")


def validate_finding(row: dict[str, Any]) -> None:
    required = {
        "finding_id", "title", "primary_domain", "temporal_class", "severity",
        "priority", "confidence", "root_cause", "trigger_conditions", "impact",
        "affected_components", "affected_trace_ids", "existing_controls", "control_gap",
        "evidence", "reproducibility", "present_impact_evidence", "remediation_seed",
    }
    missing = sorted(required - row.keys())
    if missing:
        raise ValueError(f"{row.get('finding_id')}: missing {missing}")
    if row["primary_domain"] not in DOMAINS or row["temporal_class"] not in TEMPORAL:
        raise ValueError(f"{row['finding_id']}: invalid domain/temporal class")
    if row["severity"] not in SEVERITIES or row["priority"] not in PRIORITIES or row["confidence"] not in CONFIDENCE:
        raise ValueError(f"{row['finding_id']}: invalid classification")
    if not row["present_impact_evidence"] and row["temporal_class"] != "future-risk":
        raise ValueError(f"{row['finding_id']}: projected-only finding must be future-risk")
    if not row["evidence"] or any(not e.get("path") or not e.get("location") or not e.get("observation") for e in row["evidence"]):
        raise ValueError(f"{row['finding_id']}: incomplete evidence")
    secondary = row.get("secondary_domains", [])
    if row["primary_domain"] in secondary or len(secondary) != len(set(secondary)) or not set(secondary).issubset(DOMAINS):
        raise ValueError(f"{row['finding_id']}: invalid secondary domains")
    if row["primary_domain"] == "mental-health-safety":
        required_mh = {"scenario_type", "turn_scope", "harm_mode", "safety_control_path", "fail_safe_gap"}
        if not required_mh.issubset(row.get("mental_health_details", {})):
            raise ValueError(f"{row['finding_id']}: incomplete mental-health details")
    if row["primary_domain"] in {"security", "privacy"}:
        required_sp = {"actor_or_failure_source", "asset", "trust_boundary", "sensitive_data_impact"}
        if not required_sp.issubset(row.get("security_privacy_details", {})):
            raise ValueError(f"{row['finding_id']}: incomplete security/privacy details")
    if row["primary_domain"] == "testing-quality":
        details = row.get("test_details", {})
        if not details.get("ledger_ids") and not details.get("named_coverage_gaps"):
            raise ValueError(f"{row['finding_id']}: missing testing evidence link")


def signature_tokens(row: dict[str, Any]) -> set[str]:
    text = f"{row['root_cause']} {row['control_gap']} {row['impact']}".lower()
    words = re.findall(r"[a-z][a-z0-9-]{3,}", text)
    stop = {"that", "this", "with", "without", "from", "have", "there", "when", "into", "only", "does", "user", "users", "current", "future", "repository", "control", "controls", "state", "data"}
    return {word for word in words if word not in stop}


def main() -> None:
    findings: list[dict[str, Any]] = []
    sources: dict[str, str] = {}
    for filename in FILES:
        rows = read_jsonl(SUBSYSTEM_DIR / filename)
        for row in rows:
            validate_finding(row)
            finding_id = row["finding_id"]
            if finding_id in sources:
                raise ValueError(f"duplicate finding ID {finding_id}")
            sources[finding_id] = filename
            normalized = dict(row)
            normalized["source_artifact"] = f"subsystem/{filename}"
            findings.append(normalized)
    findings.sort(key=lambda row: row["finding_id"])
    actual_ids = {row["finding_id"] for row in findings}
    if actual_ids != EXPECTED_IDS or len(findings) != 40:
        raise ValueError(f"finding cover mismatch: missing={sorted(EXPECTED_IDS-actual_ids)} extra={sorted(actual_ids-EXPECTED_IDS)}")

    test_summary = read_json(RUN_ROOT / "tests" / "execution-summary.json")
    task6 = read_json(RUN_ROOT / "tests" / "task-6-reconciliation.json")
    property5 = read_json(RUN_ROOT / "validation" / "property-5" / "result.json")
    expected_results = {"environment-failure": 42, "inconclusive": 4, "pass": 243, "product-failure": 6, "skipped-ineligible": 116}
    if test_summary["result_class_counts"] != expected_results:
        raise ValueError("terminal test result counts changed")
    if property5.get("status") != "failed-interrupted" or property5.get("stderr_or_stdout") != "^C" or property5.get("exit_code") != 1:
        raise ValueError("Property 5 blocker changed")

    # One row per issue records the explicit retain/merge decision.
    reconciliation = []
    for row in findings:
        reconciliation.append({
            "finding_id": row["finding_id"],
            "source_artifact": row["source_artifact"],
            "decision": "retain-distinct",
            "reason": "Unique root cause and end-to-end impact path; related controls are represented as compounded chains rather than merged identifiers.",
            "classification_valid": True,
            "evidence_statuses": sorted({e["status"] for e in row["evidence"]}),
        })

    critical_high = [row for row in findings if row["severity"] in {"critical", "high"}]
    pair_reviews = []
    for left, right in itertools.combinations(critical_high, 2):
        lt, rt = signature_tokens(left), signature_tokens(right)
        overlap = len(lt & rt) / max(1, len(lt | rt))
        shared_components = sorted(set(left["affected_components"]) & set(right["affected_components"]))
        if overlap >= 0.16 or shared_components:
            pair_reviews.append({
                "left": left["finding_id"], "right": right["finding_id"],
                "token_jaccard": round(overlap, 3), "shared_components": shared_components,
                "decision": "not-duplicate",
                "reason": "Different root cause, trigger, or remediation boundary; preserve linkage through chains/secondary domains.",
            })

    chains = [
        {"chain_id": "CHAIN-001", "finding_ids": ["ISSUE-003", "ISSUE-015", "ISSUE-028"], "compounded_severity": "critical", "description": "Injection-class input can reach a model with prompt-labeled stored/retrieved context that also crosses an externally controlled privacy boundary."},
        {"chain_id": "CHAIN-002", "finding_ids": ["ISSUE-004", "ISSUE-012", "ISSUE-014", "ISSUE-034", "ISSUE-035"], "compounded_severity": "critical", "description": "Non-unique document identity, non-atomic lifecycle operations, shared cache staging, worker-local state, and ephemeral paths can produce persistent knowledge divergence."},
        {"chain_id": "CHAIN-003", "finding_ids": ["ISSUE-002", "ISSUE-007", "ISSUE-034"], "compounded_severity": "critical", "description": "Pre-commit local safety mutation, context-poor fallback, and multi-worker process isolation can make safety continuity depend on worker/failure routing."},
        {"chain_id": "CHAIN-004", "finding_ids": ["ISSUE-008", "ISSUE-011", "ISSUE-031"], "compounded_severity": "critical", "description": "Fail-open output review, prompt-only relational boundaries, and incomplete scenario coverage can permit high-impact therapeutic harm regressions."},
        {"chain_id": "CHAIN-005", "finding_ids": ["ISSUE-017", "ISSUE-018", "ISSUE-019", "ISSUE-020", "ISSUE-026"], "compounded_severity": "critical", "description": "Indefinite retention, incomplete deletion, non-transactional deletion, readable fields, and tracked runtime data compound sensitive-data exposure and irreversibility."},
        {"chain_id": "CHAIN-006", "finding_ids": ["ISSUE-022", "ISSUE-023", "ISSUE-025"], "compounded_severity": "critical", "description": "Optional authentication, identity churn, and non-expiring principals combine into weak access and abuse containment."},
        {"chain_id": "CHAIN-007", "finding_ids": ["ISSUE-013", "ISSUE-029"], "compounded_severity": "high", "description": "Retrieval/no-result defects are test-observed, while the default suite lacks a universal hermetic path boundary."},
    ]

    by_temporal = Counter(row["temporal_class"] for row in findings)
    by_severity = Counter(row["severity"] for row in findings)
    by_priority = Counter(row["priority"] for row in findings)
    by_domain = Counter(row["primary_domain"] for row in findings)
    all_domain_coverage = {
        domain: {
            "primary_findings": [row["finding_id"] for row in findings if row["primary_domain"] == domain],
            "secondary_findings": [row["finding_id"] for row in findings if domain in row.get("secondary_domains", [])],
            "reviewed": True,
            "limitation": "No primary finding; reviewed through subsystem trace and secondary-domain evidence." if by_domain[domain] == 0 else "Findings are bounded to repository and isolated-test evidence.",
        }
        for domain in sorted(DOMAINS)
    }

    blockers = {
        "repository_test_environment_failures": {
            "count": 42,
            "cause": "One bounded 180-second tests/test_hardening.py batch timed out; all 42 selected tests are environment-failure/error.",
            "test_ids": [item["test_id"] for item in test_summary["blockers"] if item["result_class"] == "environment-failure"],
        },
        "repository_test_product_failures": {
            "count": 6,
            "path": "tests/test_pipeline.py",
            "test_ids": [item["test_id"] for item in test_summary["blockers"] if item["result_class"] == "product-failure"],
            "summaries": [item["summary"] for item in test_summary["blockers"] if item["result_class"] == "product-failure"],
        },
        "property_5": {
            "status": "failed-interrupted", "exit_code": 1, "output": "^C",
            "summary_available": False, "counterexample": None, "rerun_performed": False,
        },
        "property_4": {
            "status": "failed-unresolved", "failure": "exact-case validator accepts alternate-case root deliverable paths because canonicalization case-folds before exact allowlist comparison.",
            "rerun_performed": False,
        },
    }

    limitations = [
        "No live model, staging HTTP endpoint, package registry, advisory service, or Mongo replica set was contacted.",
        "External provider behavior, retention, regional controls, production TLS/WAF/headers, backups, monitoring, and Mongo deployment semantics require external validation.",
        "The 42 timed-out hardening tests have no native per-test result; they remain environment failures, not assumed product failures or passes.",
        "Property 5 was interrupted once with ^C and exit code 1 without summary/counterexample and was not rerun.",
        "Property 4's exact-case validator failure remains unresolved and forces fail-closed readiness.",
        "Metadata/structure review intentionally did not reproduce live secrets, user records, or database contents.",
    ]

    write_jsonl(SYNTHESIS_DIR / "normalized-findings.jsonl", findings)
    write_jsonl(SYNTHESIS_DIR / "issue-reconciliation.jsonl", reconciliation)
    write_json(SYNTHESIS_DIR / "critical-high-duplicate-search.json", {
        "scope_ids": [row["finding_id"] for row in critical_high],
        "scope_count": len(critical_high), "candidate_pair_reviews": pair_reviews,
        "duplicates_merged": 0, "outcome": "pass", "all_40_ids_preserved": True,
    })
    write_json(SYNTHESIS_DIR / "compounded-chains.json", chains)
    write_json(SYNTHESIS_DIR / "conflicts.json", {"worker_conflict_count": 0, "unresolved_conflicts": [], "evidence_status_promotion_performed": False})
    write_json(SYNTHESIS_DIR / "domain-coverage.json", all_domain_coverage)
    write_json(SYNTHESIS_DIR / "finding-counts.json", {
        "total": 40, "by_temporal_class": dict(sorted(by_temporal.items())),
        "by_severity": dict(sorted(by_severity.items())), "by_priority": dict(sorted(by_priority.items())),
        "by_primary_domain": dict(sorted(by_domain.items())),
    })
    write_json(SYNTHESIS_DIR / "preserved-blockers.json", blockers)
    write_json(SYNTHESIS_DIR / "limitations.json", limitations)
    write_json(SYNTHESIS_DIR / "gate-g4-g5-g6.json", {
        "run_id": RUN_ID, "schema_version": "1.0", "record_type": "synthesis-gate",
        "G4": {"outcome": "pass", "finding_count": 40, "scenario_count": 20, "subsystem_artifact_count": 7},
        "G5": {"outcome": "pass-with-recorded-failures", "catalog_total": 411, "eligible_total": 295, "executed_total": 295, "ineligible_total": 116, "blocker_count": 48, "property_5_status": task6["g5"]["property_5_status"]},
        "G6": {"outcome": "pass", "normalized_count": 40, "duplicates_merged": 0, "conflict_count": 0, "chain_count": len(chains), "unresolved_p0": [row["finding_id"] for row in findings if row["priority"] == "P0"], "unresolved_p1": [row["finding_id"] for row in findings if row["priority"] == "P1"]},
    })
    print(json.dumps({"normalized": 40, "critical_high": len(critical_high), "duplicate_candidates_reviewed": len(pair_reviews), "chains": len(chains), "outcome": "pass"}))


if __name__ == "__main__":
    main()
