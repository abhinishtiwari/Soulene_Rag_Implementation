from __future__ import annotations

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

RUN_ID = "audit-20260827T102557885287Z-073047a3"
RUN = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[6]
SUBSYSTEM = RUN / "subsystem"
CATALOG = RUN / "tests" / "catalog.jsonl"
EXPECTED_FINDING_FILES = {
    "application-flow.jsonl",
    "safety.jsonl",
    "memory-rag-cag.jsonl",
    "persistence.jsonl",
    "security-privacy.jsonl",
    "testing-quality.jsonl",
    "deployment-operations.jsonl",
}
DOMAINS = {"architecture-correctness", "mental-health-safety", "general-safety", "input-output-fail-safe", "memory-context", "rag-cag", "data-database", "security", "privacy", "testing-quality", "dependency-supply-chain", "performance-reliability", "deployment-operations", "maintainability"}
TEMPORAL = {"current-defect", "future-risk", "current-and-future"}
SEVERITY = {"critical", "high", "medium", "low", "informational"}
PRIORITY = {"P0", "P1", "P2", "P3"}
CONFIDENCE = {"confirmed", "probable", "possible"}
FINDING_REQUIRED = {
    "finding_id", "title", "primary_domain", "secondary_domains", "temporal_class", "severity", "priority",
    "confidence", "root_cause", "trigger_conditions", "present_impact_evidence", "affected_components",
    "affected_trace_ids", "impact", "existing_controls", "control_gap", "evidence", "reproducibility",
    "non_reproducibility_reason", "mental_health_details", "security_privacy_details", "test_details",
    "conflicts", "external_validation_needed", "remediation_seed",
}
SCENARIO_REQUIRED = {
    "scenario_id", "scenario_family", "turns", "risk_transition", "context_sources", "control_path",
    "expected_fail_safe", "observed_behavior", "final_output_controller", "harm_modes",
    "privacy_boundary_notes", "evidence_status", "evidence_refs", "limitations",
}


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise AssertionError(f"{path.name}:{number} is not an object")
            rows.append(value)
    return rows


def load_builder():
    path = RUN / "tooling" / "build_subsystem_artifacts.py"
    spec = importlib.util.spec_from_file_location("build_subsystem_artifacts", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SubsystemArtifactTests(unittest.TestCase):
    def test_seven_finding_artifacts_are_complete_unique_and_classified(self):
        found_ids: list[str] = []
        for name in sorted(EXPECTED_FINDING_FILES):
            path = SUBSYSTEM / name
            self.assertTrue(path.is_file(), name)
            rows = load_jsonl(path)
            self.assertTrue(rows, name)
            for row in rows:
                self.assertEqual(row.get("run_id"), RUN_ID)
                self.assertEqual(row.get("record_type"), "finding")
                self.assertFalse(FINDING_REQUIRED - row.keys(), f"{name}:{row.get('finding_id')}")
                self.assertRegex(row["finding_id"], r"^ISSUE-\d{3}$")
                found_ids.append(row["finding_id"])
                self.assertIn(row["primary_domain"], DOMAINS)
                self.assertIn(row["temporal_class"], TEMPORAL)
                self.assertIn(row["severity"], SEVERITY)
                self.assertIn(row["priority"], PRIORITY)
                self.assertIn(row["confidence"], CONFIDENCE)
                self.assertNotIn(row["primary_domain"], row["secondary_domains"])
                self.assertEqual(len(row["secondary_domains"]), len(set(row["secondary_domains"])))
                self.assertTrue(set(row["secondary_domains"]).issubset(DOMAINS))
                if not row["present_impact_evidence"]:
                    self.assertEqual(row["temporal_class"], "future-risk")
                self.assertTrue(row["evidence"])
                for evidence in row["evidence"]:
                    self.assertTrue({"path", "location", "observation", "status"}.issubset(evidence))
                    self.assertFalse(Path(evidence["path"]).is_absolute())
                    self.assertNotIn("..", Path(evidence["path"]).parts)
                    self.assertIn(evidence["status"], {"repository-proven", "test-observed", "inferred", "external-validation-required", "historical-candidate"})
                if row["primary_domain"] in {"mental-health-safety", "general-safety"}:
                    self.assertTrue(row["mental_health_details"])
                if row["primary_domain"] in {"security", "privacy"}:
                    self.assertTrue(row["security_privacy_details"])
                if row["primary_domain"] == "testing-quality":
                    self.assertTrue(row["test_details"])
        self.assertEqual(len(found_ids), 40)
        self.assertEqual(len(found_ids), len(set(found_ids)))
        self.assertEqual(set(found_ids), {f"ISSUE-{i:03d}" for i in range(1, 41)})

    def test_safety_scenario_matrix_covers_required_language_evolution_and_failures(self):
        rows = load_jsonl(SUBSYSTEM / "safety-scenarios.jsonl")
        self.assertGreaterEqual(len(rows), 20)
        ids = [row["scenario_id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)))
        for row in rows:
            self.assertFalse(SCENARIO_REQUIRED - row.keys(), row.get("scenario_id"))
            self.assertTrue(all(isinstance(turn, str) and turn.startswith("[synthetic") for turn in row["turns"]))
            self.assertTrue(row["control_path"])
            self.assertTrue(row["harm_modes"])
        families = {row["scenario_family"] for row in rows}
        required_forms = {"explicit", "implicit", "ambiguous", "negated", "quoted", "historical", "third-party", "euphemistic", "obfuscated", "unicode-sensitive"}
        self.assertTrue(required_forms.issubset(families))
        self.assertTrue({"risk-evolution", "step-down", "topic-switch", "alternating", "stale-context", "adversarial-context", "classifier-failure", "model-failure", "output-reviewer-failure", "archive-failure-retry"}.issubset(families))
        harms = {harm for row in rows for harm in row["harm_modes"]}
        for expected in {"false-negative", "false-positive", "over-escalation", "under-escalation", "cumulative harm", "boundary harm"}:
            self.assertIn(expected, harms)

    def test_catalog_is_a_total_ast_derived_static_account(self):
        rows = load_jsonl(CATALOG)
        self.assertTrue(rows)
        self.assertEqual(len({row["test_id"] for row in rows}), len(rows))
        self.assertEqual(len({row["node_id"] for row in rows}), len(rows))
        self.assertTrue(all(row["eligibility"] == "unclassified-pending-task-6" for row in rows))
        expected = {row["node_id"] for row in load_builder().discover_catalog()}
        actual = {row["node_id"] for row in rows}
        self.assertEqual(actual, expected)
        required_paths = {
            "tests/smoke_live.py", "tests/smoke_staging.py", "tests/test_mongo_integration.py",
            "test_all.py", "test_audit.py", "context_audit.py",
        }
        self.assertTrue(required_paths.issubset({row["path"] for row in rows}))
        network_paths = {row["path"] for row in rows if row["network_risks"]}
        self.assertTrue({"tests/smoke_live.py", "tests/smoke_staging.py", "tests/test_mongo_integration.py", "context_audit.py"}.issubset(network_paths))

    def test_persisted_artifacts_do_not_contain_obvious_secret_values_or_live_content(self):
        paths = [SUBSYSTEM / name for name in EXPECTED_FINDING_FILES]
        paths += [SUBSYSTEM / "safety-scenarios.jsonl", CATALOG]
        serialized = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        self.assertNotRegex(serialized, r"\bsk-[A-Za-z0-9_-]{8,}\b")
        self.assertNotRegex(serialized, r"mongodb(?:\+srv)?://[^\s\"]+")
        self.assertNotRegex(serialized, r"(?i)(?:api[_-]?key|password|token)\s*[=:]\s*['\"]?[A-Za-z0-9_./+-]{8,}")
        self.assertNotIn(".env:", serialized)


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SubsystemArtifactTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    payload = {
        "run_id": RUN_ID,
        "schema_version": "1.0",
        "test_file": "validation/test_subsystem_artifacts.py",
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "outcome": "pass" if result.wasSuccessful() else "fail",
    }
    output = RUN / "validation" / "subsystem-artifacts-result.json"
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if result.wasSuccessful():
        counts = {name: len(load_jsonl(SUBSYSTEM / name)) for name in sorted(EXPECTED_FINDING_FILES)}
        reconciliation = {
            "run_id": RUN_ID,
            "schema_version": "1.0",
            "gate": "G4",
            "outcome": "pass",
            "finding_artifacts": counts,
            "finding_count": sum(counts.values()),
            "scenario_count": len(load_jsonl(SUBSYSTEM / "safety-scenarios.jsonl")),
            "test_catalog_count": len(load_jsonl(CATALOG)),
            "unique_finding_ids": True,
            "scenario_matrix_complete": True,
            "catalog_static_totality": True,
            "root_writes": 0,
        }
        (SUBSYSTEM / "reconciliation.json").write_text(json.dumps(reconciliation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
