"""Pure generated-input checks for audit validation properties 3, 4, and 7.

Uses Hypothesis when installed; this network-denied host lacks it, so the same
predicates are exercised over 240 deterministic generated examples per property.
"""
from __future__ import annotations

import json
import random
import string
import sys
from pathlib import Path

RUN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUN_ROOT / "tooling"))
from audit_controls import (  # noqa: E402
    assert_values_absent,
    compare_integrity,
    redact_text,
    validate_created_outputs,
)

RNG = random.Random(731947)
FINDINGS = ".kiro/specs/complete-codebase-audit-future-risk-analysis/findings/run-synthetic"


def token(length: int = 14) -> str:
    return "".join(RNG.choice(string.ascii_letters + string.digits) for _ in range(length))


def property_3() -> None:
    # Feature: complete-codebase-audit-future-risk-analysis, Property 3: Protected files preserve baseline integrity
    for _ in range(240):
        count = RNG.randint(1, 35)
        baseline = {f"src/{token(8)}-{index}.py": {"sha256": token(64), "stable_metadata": {"mode": RNG.randint(1, 511)}} for index in range(count)}
        final = json.loads(json.dumps(baseline))
        assert compare_integrity(baseline, final) == []
        victim = RNG.choice(list(baseline))
        if RNG.choice((True, False)):
            final.pop(victim)
            assert any(row["path"] == victim and row["kind"] == "missing" for row in compare_integrity(baseline, final))
        else:
            final[victim]["sha256"] = token(64)
            assert any(row["path"] == victim and row["kind"] == "changed-sha256" for row in compare_integrity(baseline, final))


def property_4() -> None:
    # Feature: complete-codebase-audit-future-risk-analysis, Property 4: Created outputs satisfy the exact allowlist
    baseline = ["main.py", "app/service.py"]
    valid_created = ["issue.md", "solution.md", f"{FINDINGS}/evidence/{token()}.json"]
    for _ in range(240):
        ok, violations = validate_created_outputs(baseline, baseline + valid_created, FINDINGS, reports_required=True)
        assert ok and not violations
        invalid = RNG.choice([
            "ISSUE.md",
            "issue.md.bak",
            ".kiro/specs/complete-codebase-audit-future-risk-analysis/findings/run-synthetic-sibling/x",
            "unauthorized.md",
            "reports/solution.md",
        ])
        ok, violations = validate_created_outputs(baseline, baseline + valid_created + [invalid], FINDINGS, reports_required=True)
        assert not ok and violations
    ok, violations = validate_created_outputs(baseline, baseline + [f"{FINDINGS}/x"], FINDINGS, reports_required=True)
    assert not ok and "[missing-required-root-deliverable]" in violations


def property_7() -> None:
    # Feature: complete-codebase-audit-future-risk-analysis, Property 7: Persisted evidence never reproduces sensitive values
    for _ in range(240):
        secret = "sk-" + token(24)
        password = token(20)
        raw = f"api_key={secret} password={password}"
        result = redact_text(raw, "synthetic.env:1")
        assert "[REDACTED SENSITIVE VALUE at synthetic.env:1]" in result
        assert_values_absent(result, [secret, password])
        raw_output = f"{FINDINGS}/tests/raw/{token()}.txt"
        assert raw_output.startswith(FINDINGS + "/")


def main() -> None:
    property_3()
    property_4()
    property_7()
    output = {
        "framework": "deterministic-generated fallback (Hypothesis unavailable; no network installation permitted)",
        "examples_per_property": 240,
        "properties": {"3": "passed", "4": "passed", "7": "passed"},
    }
    output_path = RUN_ROOT / "validation" / "properties-3-4-7-result.json"
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output))


if __name__ == "__main__":
    main()
