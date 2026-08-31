from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

RUN_ID = "audit-20260827T102557885287Z-073047a3"
ROOT = Path(__file__).resolve().parents[6]
RUN_ROOT = Path(__file__).resolve().parents[1]
INTEGRITY = RUN_ROOT / "integrity"
RUN_PREFIX = f".kiro/specs/complete-codebase-audit-future-risk-analysis/findings/{RUN_ID}/"
EXPECTED_ISSUES = {f"ISSUE-{number:03d}" for number in range(1, 41)}
EXPECTED_SOLUTIONS = {f"SOLUTION-{number:03d}" for number in range(1, 41)}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def main() -> None:
    baseline_rows = load_jsonl(RUN_ROOT / "baseline" / "manifest.jsonl")
    baseline = {row["path"]: row for row in baseline_rows}
    inventory = load_jsonl(RUN_ROOT / "inventory" / "inventory.jsonl")
    architecture = load(RUN_ROOT / "architecture" / "reconciliation.json")
    subsystem = load(RUN_ROOT / "subsystem" / "reconciliation.json")
    ledger = load_jsonl(RUN_ROOT / "tests" / "test-ledger.jsonl")
    tests = load(RUN_ROOT / "tests" / "execution-summary.json")
    findings = load_jsonl(RUN_ROOT / "synthesis" / "normalized-findings.jsonl")
    remediations = load_jsonl(RUN_ROOT / "synthesis" / "report-staging" / "solution-model.jsonl")
    staging_validation = load(RUN_ROOT / "synthesis" / "report-staging" / "validation.json")
    publication = load(RUN_ROOT / "synthesis" / "report-staging" / "gate-g7-publication.json")
    readiness = load(RUN_ROOT / "synthesis" / "readiness.json")
    property4_source = RUN_ROOT / "validation" / "test_properties_3_4_7.py"
    property5 = load(RUN_ROOT / "validation" / "property-5" / "result.json")
    property6 = load(RUN_ROOT / "validation" / "property-6" / "result.json")
    property8 = load(RUN_ROOT / "validation" / "property-8" / "result.json")
    property9 = load(RUN_ROOT / "validation" / "property-9" / "result.json")

    mismatches: list[dict[str, Any]] = []
    for path_text, expected in baseline.items():
        path = ROOT / Path(path_text)
        if not path.exists() or not path.is_file():
            mismatches.append({"path": path_text, "kind": "missing"})
            continue
        observed_stat = path.stat()
        observed_hash = digest(path)
        if observed_hash != expected["sha256"]:
            mismatches.append({"path": path_text, "kind": "changed-sha256", "expected_hash": expected["sha256"], "observed_hash": observed_hash})
        if observed_stat.st_size != expected["size_bytes"]:
            mismatches.append({"path": path_text, "kind": "changed-size", "expected": expected["size_bytes"], "observed": observed_stat.st_size})
        if observed_stat.st_mtime_ns != expected["mtime_ns"]:
            mismatches.append({"path": path_text, "kind": "changed-mtime-ns", "expected": expected["mtime_ns"], "observed": observed_stat.st_mtime_ns})
        stable = {"mode": observed_stat.st_mode, "readonly": not bool(observed_stat.st_mode & stat.S_IWUSR)}
        if stable != expected["stable_metadata"]:
            mismatches.append({"path": path_text, "kind": "changed-stable-metadata", "expected": expected["stable_metadata"], "observed": stable})

    final_paths = {rel(path) for path in ROOT.rglob("*") if path.is_file()}
    baseline_paths = set(baseline)
    expected_integrity_outputs = {f"{RUN_PREFIX}integrity/changed-paths.json", f"{RUN_PREFIX}integrity/gate-g8.json"}
    created = (final_paths - baseline_paths) | expected_integrity_outputs
    missing = sorted(baseline_paths - final_paths)
    allowed_created = {"issue.md", "solution.md"}
    unauthorized = sorted(path for path in created if path not in allowed_created and not path.startswith(RUN_PREFIX))
    created_root = sorted(path for path in created if "/" not in path)
    exact_case_ok = created_root == ["issue.md", "solution.md"]
    casefold_collisions = sorted(path for path in created if path.casefold() in {"issue.md", "solution.md"} and path not in {"issue.md", "solution.md"})

    issue_text = (ROOT / "issue.md").read_text(encoding="utf-8")
    solution_text = (ROOT / "solution.md").read_text(encoding="utf-8")
    issue_headings = re.findall(r"^### (ISSUE-\d{3})\b", issue_text, flags=re.MULTILINE)
    solution_headings = re.findall(r"^### (SOLUTION-\d{3}) → (ISSUE-\d{3})\b", solution_text, flags=re.MULTILINE)
    issue_refs_ok = len(issue_headings) == 40 and set(issue_headings) == EXPECTED_ISSUES and len(set(issue_headings)) == 40
    solution_ids = [left for left, _ in solution_headings]
    mapped_issue_ids = [right for _, right in solution_headings]
    solution_refs_ok = (
        len(solution_headings) == 40
        and set(solution_ids) == EXPECTED_SOLUTIONS
        and len(set(solution_ids)) == 40
        and set(mapped_issue_ids) == EXPECTED_ISSUES
        and len(set(mapped_issue_ids)) == 40
        and all(left.split("-")[1] == right.split("-")[1] for left, right in solution_headings)
    )
    models_ok = (
        len(findings) == len(remediations) == 40
        and {row["finding_id"] for row in findings} == EXPECTED_ISSUES
        and {row["remediation_id"] for row in remediations} == EXPECTED_SOLUTIONS
        and all(row["finding_ids"] == [f"ISSUE-{row['remediation_id'].split('-')[1]}"] for row in remediations)
    )
    report_hashes_ok = digest(ROOT / "issue.md") == publication["issue_sha256"] and digest(ROOT / "solution.md") == publication["solution_sha256"]

    inventory_paths = [row["path"] for row in inventory]
    inventory_ok = len(inventory) == len(baseline) == len(set(path.casefold() for path in inventory_paths)) == 470 and set(inventory_paths) == baseline_paths
    dispositions_ok = all(row.get("disposition") in {"content-reviewed", "structure-reviewed", "metadata-reviewed", "excluded-with-reason"} and row.get("primary_owner") for row in inventory)
    architecture_ok = architecture["outcome"] == "pass" and architecture["all_nonisolated_have_upstream_downstream"] and architecture["subsystem_count"] == 7
    subsystem_ok = subsystem["outcome"] == "pass" and len(subsystem["finding_artifacts"]) == 7 and subsystem["finding_count"] == 40
    ledger_ids = [row["test_id"] for row in ledger]
    ledger_ok = len(ledger) == 411 and len(set(ledger_ids)) == 411 and all(row["eligibility"] in {"eligible", "ineligible"} for row in ledger)
    terminal_ok = tests["catalog_total"] == 411 and sum(tests["result_class_counts"].values()) == 411 and tests["executed_test_case_count"] == 295
    blocker_counts_ok = tests["result_class_counts"] == {"environment-failure": 42, "inconclusive": 4, "pass": 243, "product-failure": 6, "skipped-ineligible": 116}
    property_statuses_preserved = (
        property4_source.exists()
        and property5["status"] == "failed-interrupted" and property5["exit_code"] == 1 and property5["stderr_or_stdout"] == "^C" and not property5["rerun_performed"]
        and property6["status"] == "passed" and property8["status"] == "passed"
        and property9["status"] == "failed" and not property9["rerun_performed"]
    )

    # High-confidence secret signatures only; report locations/classes, never values.
    high_confidence_patterns = {
        "provider-secret": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        "credentialed-mongo-uri": re.compile(r"mongodb(?:\+srv)?://[^\s/:]+:[^\s/@]+@", re.IGNORECASE),
        "private-key-block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "bearer-token": re.compile(r"authorization\s*[:=]\s*bearer\s+[A-Za-z0-9._~-]{16,}", re.IGNORECASE),
    }
    scan_paths = [ROOT / "issue.md", ROOT / "solution.md"]
    scan_paths.extend(path for path in RUN_ROOT.rglob("*") if path.is_file() and path.suffix.lower() in {".json", ".jsonl", ".md", ".txt", ".py"})
    redaction_hits: list[dict[str, str]] = []
    for path in scan_paths:
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in high_confidence_patterns.items():
            if pattern.search(text):
                redaction_hits.append({"path": rel(path), "pattern_class": label})
    redaction_ok = not redaction_hits

    report_fields_ok = all(marker in issue_text for marker in ("## Current Defects", "## Future Risks", "## Current and Future", "## Verified Strengths", "## Coverage Proof", "## Reviewed Domains Without a Primary Finding", "## Readiness Decision")) and all(marker in solution_text for marker in ("## One-to-One Mapping Contract", "## Phased Roadmap", "## Detailed Remediations", "## Residual Risk", "## Final Decision Rule"))
    summary_counts_ok = all(fragment in issue_text for fragment in ("3 Critical, 25 High, 11 Medium, and 1 Low", "**243 pass**", "**6 product-failure**", "**42 environment-failure**", "**116 skipped-ineligible**"))
    staging_ok = staging_validation["outcome"] == "pass" and staging_validation["one_to_one_mapping"] and staging_validation["redaction_scan_passed"]

    hard_failures = []
    if mismatches:
        hard_failures.append("protected-baseline-mismatch")
    if missing:
        hard_failures.append("missing-baseline-path")
    if unauthorized or not exact_case_ok or casefold_collisions:
        hard_failures.append("created-output-boundary")
    if not redaction_ok:
        hard_failures.append("redaction")
    if not (issue_refs_ok and solution_refs_ok and models_ok and report_hashes_ok):
        hard_failures.append("cross-reference-or-publication")
    if not (inventory_ok and dispositions_ok and architecture_ok and subsystem_ok and ledger_ok and terminal_ok and blocker_counts_ok and report_fields_ok and summary_counts_ok and staging_ok):
        hard_failures.append("coverage-reconciliation")

    unresolved_validation = [
        "Property 4 exact-case validator failure remains unresolved.",
        "Property 5 remains interrupted with ^C/exit 1 and no summary or counterexample.",
        "Property 9 failed because its generated expected-valid conditional record omitted the required condition; no rerun was performed.",
        "Forty-two hardening tests remain environment failures from one 180-second batch timeout.",
        "Six pipeline tests remain product failures.",
    ]
    all_mechanical_checks_pass = not hard_failures and property_statuses_preserved
    # G8 remains fail-closed because unresolved required validation/test evidence prevents all gates from passing.
    gate_outcome = "fail-closed" if unresolved_validation else ("pass" if all_mechanical_checks_pass else "fail")
    effective_readiness = "not-ready"

    changed = {
        "run_id": RUN_ID,
        "baseline_protected_mismatches": mismatches,
        "missing_baseline_paths": missing,
        "created_paths": sorted(created),
        "created_paths_outside_active_findings_run": sorted(path for path in created if not path.startswith(RUN_PREFIX)),
        "unauthorized_created_paths": unauthorized,
        "changed_or_new_paths_outside_active_findings_run": sorted({item["path"] for item in mismatches} | set(missing) | {path for path in created if not path.startswith(RUN_PREFIX)}),
    }
    result = {
        "run_id": RUN_ID,
        "schema_version": "1.0",
        "record_type": "final-g8-integrity-cross-reference",
        "gate": "G8",
        "outcome": gate_outcome,
        "effective_readiness": effective_readiness,
        "production_readiness_before_g8": readiness["conclusion"],
        "protected_integrity": {"checked": len(baseline), "mismatch_count": len(mismatches), "missing_count": len(missing), "passed": not mismatches and not missing},
        "created_output_boundary": {"created_count": len(created), "unauthorized_count": len(unauthorized), "created_root_paths": created_root, "exact_case_ok": exact_case_ok, "alternate_case_collisions": casefold_collisions, "passed": not unauthorized and exact_case_ok and not casefold_collisions},
        "coverage": {"inventory": inventory_ok and dispositions_ok, "architecture": architecture_ok, "subsystems": subsystem_ok, "test_ledger": ledger_ok and terminal_ok and blocker_counts_ok, "report_fields_and_counts": report_fields_ok and summary_counts_ok, "passed": not any(item == "coverage-reconciliation" for item in hard_failures)},
        "references": {"issue_count": len(issue_headings), "solution_count": len(solution_headings), "issue_unique_and_complete": issue_refs_ok, "solution_one_to_one": solution_refs_ok, "models_one_to_one": models_ok, "published_hashes_match_g7": report_hashes_ok, "property_6": property6["status"], "passed": issue_refs_ok and solution_refs_ok and models_ok and report_hashes_ok},
        "redaction": {"scanned_file_count": len(scan_paths), "hit_count": len(redaction_hits), "hits": redaction_hits, "passed": redaction_ok},
        "property_validation": {"property_4": "failed-unresolved-not-rerun", "property_5": property5["status"], "property_6": property6["status"], "property_8": property8["status"], "property_9": property9["status"], "statuses_preserved": property_statuses_preserved},
        "repository_test_blockers": {"environment_failures": 42, "product_failures": 6, "preserved": blocker_counts_ok},
        "hard_failure_reasons": hard_failures,
        "unresolved_fail_closed_reasons": unresolved_validation,
        "mechanical_integrity_and_cross_reference_checks_passed": all_mechanical_checks_pass,
        "changed_paths_ref": f"{RUN_PREFIX}integrity/changed-paths.json",
    }
    write(INTEGRITY / "changed-paths.json", changed)
    write(INTEGRITY / "gate-g8.json", result)
    print(json.dumps({
        "g8": gate_outcome,
        "effective_readiness": effective_readiness,
        "protected_checked": len(baseline),
        "protected_mismatches": len(mismatches),
        "unauthorized_created": len(unauthorized),
        "root_created": created_root,
        "issue_refs": len(issue_headings),
        "solution_refs": len(solution_headings),
        "redaction_hits": len(redaction_hits),
        "hard_failures": hard_failures,
    }))


if __name__ == "__main__":
    main()
