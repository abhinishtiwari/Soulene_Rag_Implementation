"""Generated-input validation for Property 9; no target-tree I/O."""
from __future__ import annotations

import random

RNG = random.Random(9009)
DOMAINS = ("security", "privacy", "testing-quality", "deployment-operations")
SEVERITIES = ("critical", "high", "medium", "low")
TEMPORAL = ("current-defect", "future-risk", "current-and-future")


def decide(*, integrity_ok: bool, p0: list[str], p1: list[str], conditions: list[str], blockers: list[str]) -> str:
    if not integrity_ok or p0 or blockers:
        return "not-ready"
    if p1 or conditions:
        return "conditionally-ready"
    return "ready"


def valid(record: dict) -> bool:
    conclusion = record.get("conclusion")
    if conclusion not in {"ready", "conditionally-ready", "not-ready"}:
        return False
    if not record.get("integrity_ok", False) and conclusion != "not-ready":
        return False
    if conclusion == "ready" and (record.get("p0") or record.get("p1")):
        return False
    if conclusion == "conditionally-ready" and (not record.get("conditions") or not record.get("verification_gates")):
        return False
    if conclusion == "not-ready" and (not record.get("release_blockers") or not record.get("reconsideration_evidence")):
        return False
    return all(record.get(name) for name in ("residual_by_domain", "residual_by_severity", "residual_by_temporal"))


def test_property_9_readiness_is_deterministic_and_fail_closed() -> None:
    # Feature: complete-codebase-audit-future-risk-analysis, Property 9: Readiness gating is deterministic and fail-closed
    # **Validates: Requirements 16.1, 16.2, 16.3, 16.4, 16.5, 16.11**
    for number in range(240):
        integrity_ok = RNG.choice((True, False))
        p0 = [f"P0-{number}"] if RNG.randrange(5) == 0 else []
        p1 = [f"P1-{number}"] if RNG.randrange(3) == 0 else []
        conditions = ["condition"] if RNG.randrange(3) == 0 else []
        blockers = ["blocker"] if RNG.randrange(4) == 0 else []
        conclusion = decide(integrity_ok=integrity_ok, p0=p0, p1=p1, conditions=conditions, blockers=blockers)
        record = {
            "conclusion": conclusion, "integrity_ok": integrity_ok, "p0": p0, "p1": p1,
            "conditions": conditions, "verification_gates": ["gate"] if conclusion == "conditionally-ready" else [],
            "release_blockers": (blockers or p0 or (["integrity"] if not integrity_ok else [])) if conclusion == "not-ready" else [],
            "reconsideration_evidence": ["evidence"] if conclusion == "not-ready" else [],
            "residual_by_domain": {RNG.choice(DOMAINS): 1},
            "residual_by_severity": {RNG.choice(SEVERITIES): 1},
            "residual_by_temporal": {RNG.choice(TEMPORAL): 1},
        }
        assert valid(record)
        assert conclusion == decide(integrity_ok=integrity_ok, p0=p0, p1=p1, conditions=conditions, blockers=blockers)

        broken = dict(record)
        mutation = RNG.choice(("integrity", "p0-ready", "conditions", "blockers", "summary"))
        if mutation == "integrity":
            broken.update(integrity_ok=False, conclusion="ready", p0=[], p1=[])
        elif mutation == "p0-ready":
            broken.update(integrity_ok=True, conclusion="ready", p0=["P0-X"])
        elif mutation == "conditions":
            broken.update(integrity_ok=True, conclusion="conditionally-ready", conditions=[], verification_gates=[])
        elif mutation == "blockers":
            broken.update(conclusion="not-ready", release_blockers=[], reconsideration_evidence=[])
        else:
            broken["residual_by_domain"] = {}
        assert not valid(broken)
