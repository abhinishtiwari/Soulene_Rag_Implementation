from __future__ import annotations

import json
import random
import string
import sys
from pathlib import Path

RUN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUN_ROOT / "tooling"))
from audit_controls import ValidationError, validate_inventory  # noqa: E402

RNG = random.Random(10202)


def name() -> str:
    return "".join(RNG.choice(string.ascii_lowercase) for _ in range(12))


def record(path: str, disposition: str = "content-reviewed") -> dict:
    return {"path": path, "disposition": disposition, "disposition_reason": "reason", "inspection_limit": "bounded inspection", "primary_owner": "owner"}


def must_fail(baseline, inventory) -> None:
    try:
        validate_inventory(baseline, inventory)
    except ValidationError:
        return
    raise AssertionError("invalid generated inventory passed")


def property_1() -> None:
    # Feature: complete-codebase-audit-future-risk-analysis, Property 1: Inventory is a one-to-one cover of the baseline
    for _ in range(240):
        baseline = [f"src/{name()}-{index}.py" for index in range(RNG.randint(1, 30))]
        inventory = [record(path) for path in baseline]
        validate_inventory(baseline, inventory)
        must_fail(baseline, inventory[:-1])
        must_fail(baseline, inventory + [record(baseline[0])])
        must_fail(baseline, inventory + [record(f"extra/{name()}.py")])


def property_2() -> None:
    # Feature: complete-codebase-audit-future-risk-analysis, Property 2: Inspection disposition is unique and complete
    baseline = ["a.txt"]
    for _ in range(240):
        disposition = RNG.choice(["content-reviewed", "structure-reviewed", "metadata-reviewed", "excluded-with-reason"])
        validate_inventory(baseline, [record("a.txt", disposition)])
        bad = record("a.txt", "invalid")
        must_fail(baseline, [bad])
        bad = record("a.txt", "excluded-with-reason")
        bad["disposition_reason"] = ""
        must_fail(baseline, [bad])
        bad = record("a.txt", RNG.choice(["structure-reviewed", "metadata-reviewed"]))
        bad["inspection_limit"] = ""
        must_fail(baseline, [bad])


def main() -> None:
    property_1()
    property_2()
    result = {"framework": "deterministic-generated fallback", "examples_per_property": 240, "properties": {"1": "passed", "2": "passed"}}
    (RUN_ROOT / "validation" / "properties-1-2-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
