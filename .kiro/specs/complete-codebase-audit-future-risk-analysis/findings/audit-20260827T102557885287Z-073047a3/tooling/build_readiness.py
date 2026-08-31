from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

RUN_ID = "audit-20260827T102557885287Z-073047a3"
RUN_ROOT = Path(__file__).resolve().parents[1]
SYNTHESIS = RUN_ROOT / "synthesis"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write(name: str, value: Any) -> None:
    path = SYNTHESIS / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def main() -> None:
    findings = load_jsonl(SYNTHESIS / "normalized-findings.jsonl")
    inventory = load(RUN_ROOT / "inventory" / "reconciliation.json")
    architecture = load(RUN_ROOT / "architecture" / "reconciliation.json")
    subsystem = load(RUN_ROOT / "subsystem" / "reconciliation.json")
    tests = load(RUN_ROOT / "tests" / "execution-summary.json")
    g5 = load(RUN_ROOT / "tests" / "gate-g5.json")
    variants = load(RUN_ROOT / "architecture" / "runtime-variants.json")
    unresolved = load(RUN_ROOT / "architecture" / "unresolved-paths.json")
    blockers = load(SYNTHESIS / "preserved-blockers.json")

    if inventory["baseline_count"] != inventory["inventory_count"] != inventory["canonical_unique_count"]:
        raise ValueError("inventory count mismatch")
    if subsystem["finding_count"] != len(findings) or set(row["finding_id"] for row in findings) != {f"ISSUE-{n:03d}" for n in range(1, 41)}:
        raise ValueError("finding coverage mismatch")
    if g5["catalog_total"] != g5["terminal_accounting_total"] or g5["eligible_total"] != g5["executed_total"]:
        raise ValueError("test accounting mismatch")

    unresolved_p0 = [row["finding_id"] for row in findings if row["priority"] == "P0"]
    unresolved_p1 = [row["finding_id"] for row in findings if row["priority"] == "P1"]
    release_blockers = unresolved_p0 + unresolved_p1 + [
        "TEST-BLOCKER-ENV-042", "TEST-BLOCKER-PRODUCT-006", "PROPERTY-4-EXACT-CASE", "PROPERTY-5-INTERRUPTED"
    ]
    readiness = {
        "run_id": RUN_ID,
        "schema_version": "1.0",
        "record_type": "readiness-decision",
        "conclusion": "not-ready",
        "rationale": "Unresolved P0/P1 findings and validation/test blockers preclude production release. The decision is fail-closed pending final G8; a later protected-artifact mismatch would independently preserve not-ready.",
        "integrity_basis": {
            "prepublication_protected_integrity_ok": tests["protected_integrity_ok"],
            "final_g8_pending": True,
            "audit_control_validation_ok": False,
            "unresolved_validator": "Property 4 exact-case output allowlist failure",
        },
        "unresolved_p0": unresolved_p0,
        "unresolved_p1": unresolved_p1,
        "release_blockers": release_blockers,
        "preproduction_conditions": [
            "Close every P0 and P1 finding with mapped acceptance evidence.",
            "Resolve and rerun the exact-case output allowlist validator (Property 4).",
            "Obtain a conclusive Property 5 result in a separately authorized validation run; do not reinterpret the interrupted result.",
            "Resolve the six tests/test_pipeline.py product failures without modifying evidence from this audit.",
            "Execute the 42 timed-out tests/test_hardening.py cases in a bounded hermetic lane and classify each native result.",
            "Complete independent safety, privacy, security, and deployment review for all external-validation-required controls.",
        ],
        "verification_gates": [
            "No unresolved P0/P1 findings", "All eligible tests terminal with no unexplained failure",
            "Properties 4 and 5 conclusively pass", "Safety scenario matrix passes reviewed regression tests",
            "Final protected-baseline and exact-created-output integrity passes",
        ],
        "reconsideration_evidence": [
            "Issue-specific automated and manual acceptance evidence for every P0/P1 remediation.",
            "Passing exact-case allowlist and ledger-order property results with retained output.",
            "Passing or explicitly adjudicated native results for the 48 repository-test blockers.",
            "External validation records for production identity, encryption, provider privacy, emergency resources, network edge, Mongo, monitoring, backup, and restore controls.",
        ],
        "residual_risk_by_domain": dict(sorted(Counter(row["primary_domain"] for row in findings).items())),
        "residual_risk_by_severity": dict(sorted(Counter(row["severity"] for row in findings).items())),
        "residual_risk_by_temporal_class": dict(sorted(Counter(row["temporal_class"] for row in findings).items())),
    }

    variant_count = len(variants) if isinstance(variants, list) else sum(len(v) if isinstance(v, list) else 1 for v in variants.values())
    coverage = {
        "run_id": RUN_ID,
        "schema_version": "1.0",
        "record_type": "coverage-proof",
        "baseline_count": inventory["baseline_count"],
        "inventory_count": inventory["inventory_count"],
        "canonical_unique_count": inventory["canonical_unique_count"],
        "disposition_counts": inventory["disposition_counts"],
        "owner_counts": inventory["owner_counts"],
        "one_primary_owner_per_file": inventory["one_primary_owner_per_file"],
        "entrypoint_count": architecture["entrypoint_count"],
        "trace_edge_count": architecture["trace_edge_count"],
        "trace_variant_count": variant_count,
        "unresolved_architecture_paths": unresolved,
        "subsystem_coverage": {
            "expected": 7,
            "completed": len(subsystem["finding_artifacts"]),
            "artifacts": subsystem["finding_artifacts"],
            "scenario_count": subsystem["scenario_count"],
            "scenario_matrix_complete": subsystem["scenario_matrix_complete"],
        },
        "findings": {"total": len(findings), "unique_ids": len({row["finding_id"] for row in findings}), "range": "ISSUE-001..ISSUE-040"},
        "tests": {
            "catalog_total": tests["catalog_total"], "actual_test_case_total": tests["actual_test_case_total"],
            "eligible_total": tests["eligibility_counts"]["eligible"], "executed_total": tests["executed_test_case_count"],
            "ineligible_total": tests["eligibility_counts"]["ineligible"],
            "result_class_counts": tests["result_class_counts"], "native_status_counts": tests["native_status_counts"],
            "network_probe_passed": tests["network_probe_passed"], "path_containment_ok": tests["path_containment_ok"],
            "protected_integrity_ok": tests["protected_integrity_ok"],
        },
        "property_status": {
            "Property 4": blockers["property_4"], "Property 5": blockers["property_5"],
            "Property 8": load(RUN_ROOT / "validation" / "property-8" / "result.json")["status"],
        },
        "limitations": load(SYNTHESIS / "limitations.json"),
    }
    write("coverage-proof.json", coverage)
    write("readiness.json", readiness)
    write("gate-g6-readiness.json", {
        "gate": "G6", "outcome": "pass", "run_id": RUN_ID,
        "coverage_reconciled": True, "readiness_conclusion": "not-ready",
        "release_blocker_count": len(release_blockers), "final_g8_pending": True,
    })
    print(json.dumps({"coverage": "reconciled", "readiness": "not-ready", "p0": len(unresolved_p0), "p1": len(unresolved_p1), "release_blockers": len(release_blockers)}))


if __name__ == "__main__":
    main()
