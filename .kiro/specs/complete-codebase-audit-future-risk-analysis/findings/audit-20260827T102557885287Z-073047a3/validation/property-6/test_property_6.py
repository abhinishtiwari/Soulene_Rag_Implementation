"""Generated-input validation for Property 6; no report publication."""
from __future__ import annotations

import random

RNG = random.Random(6006)


def validate(issue_ids: list[str], remediations: list[dict]) -> bool:
    if len(issue_ids) != len(set(issue_ids)):
        return False
    known = set(issue_ids)
    referenced: set[str] = set()
    for remediation in remediations:
        refs = remediation.get("finding_ids", [])
        systemic = remediation.get("systemic_improvement", False)
        if not systemic and (not refs or not set(refs).issubset(known)):
            return False
        if set(refs) - known:
            return False
        referenced.update(refs)
    return known.issubset(referenced)


def test_property_6_bidirectional_issue_solution_references() -> None:
    # Feature: complete-codebase-audit-future-risk-analysis, Property 6: Issue and solution references are bidirectionally valid
    # **Validates: Requirements 14.2, 16.7, 16.8**
    for example in range(240):
        count = RNG.randint(1, 45)
        issue_ids = [f"ISSUE-{example:03d}-{index:03d}" for index in range(count)]
        remediations = [
            {"remediation_id": f"SOLUTION-{example:03d}-{index:03d}", "finding_ids": [issue_id], "systemic_improvement": False}
            for index, issue_id in enumerate(issue_ids)
        ]
        if RNG.choice((True, False)):
            remediations.append({"remediation_id": f"SYSTEMIC-{example:03d}", "finding_ids": [], "systemic_improvement": True})
        assert validate(issue_ids, remediations)

        mutation = RNG.choice(("duplicate-issue", "dangling", "empty", "unmapped"))
        broken_ids = list(issue_ids)
        broken_remediations = [dict(item, finding_ids=list(item["finding_ids"])) for item in remediations]
        target = next(item for item in broken_remediations if not item["systemic_improvement"])
        if mutation == "duplicate-issue":
            broken_ids.append(broken_ids[0])
        elif mutation == "dangling":
            target["finding_ids"] = ["ISSUE-NOT-FOUND"]
        elif mutation == "empty":
            target["finding_ids"] = []
        else:
            missing = broken_ids[-1]
            for item in broken_remediations:
                item["finding_ids"] = [ref for ref in item["finding_ids"] if ref != missing]
        assert not validate(broken_ids, broken_remediations)
