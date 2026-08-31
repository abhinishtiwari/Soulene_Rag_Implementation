from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

RUN_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = RUN_ROOT / "tooling" / "task6_test_runner.py"
SPEC = importlib.util.spec_from_file_location("task6_test_runner", MODULE_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def synthetic_case(test_id: str, eligible: bool):
    if eligible:
        record = {
            "test_id": test_id,
            "eligibility": "eligible",
            "eligibility_reason": "synthetic safe case",
            "execution_status": "terminal",
            "result_class": "pass",
            "native_status": "passed",
            "exact_command": f"python -m pytest synthetic::{test_id}",
            "redacted_output_ref": f"tests/raw-output/{test_id}.txt",
        }
        events = [
            {"test_id": test_id, "state": "classified"},
            {"test_id": test_id, "state": "attested"},
            {"test_id": test_id, "state": "executing"},
            {"test_id": test_id, "state": "terminal"},
        ]
        attestation = {
            "integrity_ok": True,
            "path_containment_ok": True,
            "network_probe_result": "pass",
        }
    else:
        record = {
            "test_id": test_id,
            "eligibility": "ineligible",
            "eligibility_reason": "synthetic external network requirement",
            "execution_status": "skipped-ineligible",
            "result_class": "skipped-ineligible",
            "native_status": "not-run",
            "exact_command": None,
            "redacted_output_ref": None,
        }
        events = [
            {"test_id": test_id, "state": "classified"},
            {"test_id": test_id, "state": "skipped-ineligible"},
        ]
        attestation = None
    return record, events, attestation


def test_valid_mixed_ledger_is_accepted():
    first, first_events, first_attestation = synthetic_case("TST-A", True)
    second, second_events, _ = synthetic_case("TST-B", False)
    runner.validate_test_ledger(
        ["TST-A", "TST-B"],
        [first, second],
        first_events + second_events,
        {"TST-A": first_attestation},
    )


def test_execution_before_attestation_is_rejected():
    record, events, attestation = synthetic_case("TST-A", True)
    events[1], events[2] = events[2], events[1]
    with pytest.raises(ValueError, match="ordering"):
        runner.validate_test_ledger(
            ["TST-A"], [record], events, {"TST-A": attestation}
        )


# Feature: complete-codebase-audit-future-risk-analysis, Property 5: Test eligibility and execution accounting are total and ordered
# **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6**
@settings(max_examples=100, deadline=None, database=None)
@given(st.lists(st.booleans(), min_size=1, max_size=40))
def test_property_5_totality_and_ordering(eligibility_flags):
    discovered = [f"TST-{index:03d}" for index in range(len(eligibility_flags))]
    ledger = []
    events = []
    attestations = {}
    for test_id, eligible in zip(discovered, eligibility_flags):
        record, record_events, attestation = synthetic_case(test_id, eligible)
        ledger.append(record)
        events.extend(record_events)
        if attestation is not None:
            attestations[test_id] = attestation

    runner.validate_test_ledger(discovered, ledger, events, attestations)

    duplicate = list(ledger) + [dict(ledger[0])]
    with pytest.raises(ValueError, match="one-to-one"):
        runner.validate_test_ledger(discovered, duplicate, events, attestations)

    target_index = next((index for index, flag in enumerate(eligibility_flags) if flag), None)
    if target_index is not None:
        test_id = discovered[target_index]
        reordered = list(events)
        positions = [index for index, event in enumerate(reordered) if event["test_id"] == test_id]
        executing_position = next(index for index in positions if reordered[index]["state"] == "executing")
        attested_position = next(index for index in positions if reordered[index]["state"] == "attested")
        reordered[executing_position], reordered[attested_position] = (
            reordered[attested_position], reordered[executing_position]
        )
        with pytest.raises(ValueError, match="ordering"):
            runner.validate_test_ledger(discovered, ledger, reordered, attestations)
