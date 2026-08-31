"""Generated-input validation for Property 8; no live repository data is loaded."""
from __future__ import annotations

import random

TEMPORAL = ("current-defect", "future-risk", "current-and-future")
SECTIONS = {
    "current-defect": "Current Defects",
    "future-risk": "Future Risks",
    "current-and-future": "Current and Future",
}
RNG = random.Random(8008)


def validate_partition(findings: list[dict], assignments: dict[str, list[str]]) -> bool:
    occurrences: dict[str, list[str]] = {}
    for section, ids in assignments.items():
        for finding_id in ids:
            occurrences.setdefault(finding_id, []).append(section)
    for finding in findings:
        temporal = finding.get("temporal_class")
        if temporal not in TEMPORAL:
            return False
        if not finding.get("present_impact_evidence", False) and temporal != "future-risk":
            return False
        if occurrences.get(finding["finding_id"]) != [SECTIONS[temporal]]:
            return False
    return set(occurrences) == {finding["finding_id"] for finding in findings}


def test_property_8_temporal_classification_and_partitioning() -> None:
    # Feature: complete-codebase-audit-future-risk-analysis, Property 8: Temporal classification is singular, evidence-supported, and consistently partitioned
    # **Validates: Requirements 4.2, 4.8, 13.2, 13.3**
    for example in range(240):
        findings = []
        assignments = {section: [] for section in SECTIONS.values()}
        for index in range(RNG.randint(1, 45)):
            temporal = RNG.choice(TEMPORAL)
            present = temporal != "future-risk" or RNG.choice((True, False))
            finding_id = f"ISSUE-{example:03d}-{index:03d}"
            findings.append({"finding_id": finding_id, "temporal_class": temporal, "present_impact_evidence": present})
            assignments[SECTIONS[temporal]].append(finding_id)
        assert validate_partition(findings, assignments)

        broken_findings = [dict(item) for item in findings]
        broken_assignments = {key: list(value) for key, value in assignments.items()}
        victim = RNG.choice(broken_findings)
        mutation = RNG.choice(("missing", "duplicate", "wrong-section", "unsupported", "unsupported-present"))
        expected = SECTIONS[victim["temporal_class"]]
        if mutation == "missing":
            broken_assignments[expected].remove(victim["finding_id"])
        elif mutation == "duplicate":
            broken_assignments[expected].append(victim["finding_id"])
        elif mutation == "wrong-section":
            broken_assignments[expected].remove(victim["finding_id"])
            other = RNG.choice([name for name in SECTIONS.values() if name != expected])
            broken_assignments[other].append(victim["finding_id"])
        elif mutation == "unsupported":
            victim["temporal_class"] = "unknown"
        else:
            victim["temporal_class"] = "current-defect"
            victim["present_impact_evidence"] = False
        assert not validate_partition(broken_findings, broken_assignments)
