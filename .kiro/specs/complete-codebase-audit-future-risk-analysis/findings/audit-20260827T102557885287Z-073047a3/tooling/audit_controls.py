from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

DISPOSITIONS = {"content-reviewed", "structure-reviewed", "metadata-reviewed", "excluded-with-reason"}
DOMAINS = {"architecture-correctness", "mental-health-safety", "general-safety", "input-output-fail-safe", "memory-context", "rag-cag", "data-database", "security", "privacy", "testing-quality", "dependency-supply-chain", "performance-reliability", "deployment-operations", "maintainability"}
TEMPORAL = {"current-defect", "future-risk", "current-and-future"}
SEVERITIES = {"critical", "high", "medium", "low", "informational"}
PRIORITIES = {"P0", "P1", "P2", "P3"}
CONFIDENCE = {"confirmed", "probable", "possible"}
RESULT_CLASSES = {"pass", "product-failure", "test-defect", "environment-failure", "dependency-failure", "inconclusive", "skipped-ineligible"}
NATIVE_STATUSES = {"passed", "failed", "skipped", "xfailed", "xpassed", "error", "not-run"}


class ValidationError(ValueError):
    pass


def canonical_relative(path: str) -> str:
    value = path.replace("\\", "/")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValidationError(f"unsafe relative path: {path!r}")
    return "/".join(pure.parts).casefold()


def is_descendant(path: str, parent: str) -> bool:
    child = canonical_relative(path)
    base = canonical_relative(parent)
    return child.startswith(base + "/")


def validate_created_outputs(
    baseline_paths: Iterable[str],
    final_paths: Iterable[str],
    findings_run: str,
    *,
    reports_required: bool,
) -> tuple[bool, list[str]]:
    baseline = {canonical_relative(p) for p in baseline_paths}
    final = {canonical_relative(p) for p in final_paths}
    issue = canonical_relative("issue.md")
    solution = canonical_relative("solution.md")
    run = canonical_relative(findings_run)
    unauthorized = sorted(p for p in final - baseline if p not in {issue, solution} and not p.startswith(run + "/"))
    if reports_required and not {issue, solution}.issubset(final):
        unauthorized.append("[missing-required-root-deliverable]")
    return not unauthorized, unauthorized


def compare_integrity(
    baseline: Mapping[str, Mapping[str, Any]],
    final: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized_final = {canonical_relative(k): v for k, v in final.items()}
    mismatches: list[dict[str, Any]] = []
    for raw_path, expected in baseline.items():
        key = canonical_relative(raw_path)
        observed = normalized_final.get(key)
        if observed is None:
            mismatches.append({"path": raw_path, "kind": "missing"})
            continue
        for field_name in ("sha256", "stable_metadata"):
            if observed.get(field_name) != expected.get(field_name):
                mismatches.append({"path": raw_path, "kind": f"changed-{field_name}", "expected": expected.get(field_name), "observed": observed.get(field_name)})
    return mismatches


@dataclass(frozen=True)
class Evidence:
    path: str
    location: str
    observation: str
    status: str

    def validate(self) -> None:
        canonical_relative(self.path)
        if not self.location.strip() or not self.observation.strip():
            raise ValidationError("evidence must be independently locatable")
        if self.status not in {"repository-proven", "test-observed", "inferred", "external-validation-required", "historical-candidate"}:
            raise ValidationError("invalid evidence status")


@dataclass
class Finding:
    finding_id: str
    title: str
    primary_domain: str
    temporal_class: str
    severity: str
    priority: str
    confidence: str
    root_cause: str
    trigger_conditions: list[str]
    affected_components: list[str]
    impact: str
    existing_controls: list[str]
    control_gap: str
    evidence: list[Evidence]
    reproducibility: str
    present_impact_evidence: bool = True
    secondary_domains: list[str] = field(default_factory=list)
    specialized: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not re.fullmatch(r"ISSUE-\d{3}", self.finding_id):
            raise ValidationError("invalid finding id")
        if self.primary_domain not in DOMAINS or self.temporal_class not in TEMPORAL or self.severity not in SEVERITIES or self.priority not in PRIORITIES or self.confidence not in CONFIDENCE:
            raise ValidationError("invalid finding classification")
        if not self.present_impact_evidence and self.temporal_class != "future-risk":
            raise ValidationError("non-present impact must be future-risk")
        if not self.evidence:
            raise ValidationError("evidence required")
        if self.primary_domain in self.secondary_domains or len(self.secondary_domains) != len(set(self.secondary_domains)) or any(d not in DOMAINS for d in self.secondary_domains):
            raise ValidationError("invalid secondary domains")
        for item in self.evidence:
            item.validate()


@dataclass
class Remediation:
    remediation_id: str
    finding_ids: list[str]
    priority: str
    dependency_gate: str
    immediate_containment: str
    durable_remediation: str
    intended_outcome: str
    affected_components: list[str]
    prerequisites: list[str]
    implementation_risks: list[str]
    migration_concerns: list[str]
    rollback_considerations: list[str]
    automated_verification: list[str]
    manual_review: list[str]
    acceptance_evidence: list[str]
    residual_risk: str
    validation_limits: str
    systemic_improvement: bool = False

    def validate(self, issue_ids: set[str]) -> None:
        if self.priority not in PRIORITIES:
            raise ValidationError("invalid remediation priority")
        if not self.systemic_improvement and (not self.finding_ids or not set(self.finding_ids).issubset(issue_ids)):
            raise ValidationError("dangling or empty finding references")
        required = [self.immediate_containment, self.durable_remediation, self.intended_outcome, self.residual_risk, self.validation_limits]
        if any(not value.strip() for value in required):
            raise ValidationError("incomplete remediation")


SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|password|token|mongodb(?:\+srv)?://|authorization)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
]


def redact_text(text: str, source: str = "unknown") -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        if pattern.groups >= 2:
            redacted = pattern.sub(lambda match: f"{match.group(1)}=[REDACTED SENSITIVE VALUE at {source}]", redacted)
        else:
            redacted = pattern.sub(f"[REDACTED SENSITIVE VALUE at {source}]", redacted)
    return redacted


def assert_values_absent(serialized: str, sensitive_values: Sequence[str]) -> None:
    leaked = [value for value in sensitive_values if value and value in serialized]
    if leaked:
        raise ValidationError(f"sensitive values remained: {len(leaked)}")


def validate_inventory(baseline_paths: Sequence[str], inventory: Sequence[Mapping[str, Any]]) -> None:
    expected = [canonical_relative(path) for path in baseline_paths]
    actual = [canonical_relative(str(row["path"])) for row in inventory]
    if set(expected) != set(actual) or len(actual) != len(expected) or len(actual) != len(set(actual)):
        raise ValidationError("inventory is not a one-to-one baseline cover")
    for row in inventory:
        disposition = row.get("disposition")
        if disposition not in DISPOSITIONS:
            raise ValidationError("invalid disposition")
        if disposition == "excluded-with-reason" and not str(row.get("disposition_reason", "")).strip():
            raise ValidationError("excluded files require rationale")
        if disposition in {"structure-reviewed", "metadata-reviewed"} and not str(row.get("inspection_limit", "")).strip():
            raise ValidationError("non-content review requires inspection limit")
        if not str(row.get("primary_owner", "")).strip():
            raise ValidationError("primary owner required")


def validate_issue_remediation_refs(findings: Sequence[Finding], remediations: Sequence[Remediation]) -> None:
    ids = [finding.finding_id for finding in findings]
    if len(ids) != len(set(ids)):
        raise ValidationError("duplicate finding ids")
    issue_ids = set(ids)
    for finding in findings:
        finding.validate()
    for remediation in remediations:
        remediation.validate(issue_ids)
    referenced = {finding_id for remediation in remediations for finding_id in remediation.finding_ids}
    if not issue_ids.issubset(referenced):
        raise ValidationError("unmapped issue")


def readiness_conclusion(*, integrity_ok: bool, unresolved_p0: Sequence[str], unresolved_p1: Sequence[str], conditions: Sequence[str], blockers: Sequence[str]) -> str:
    if not integrity_ok or unresolved_p0 or blockers:
        return "not-ready"
    if unresolved_p1 or conditions:
        return "conditionally-ready"
    return "ready"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for value in values:
            stream.write(json.dumps(value, sort_keys=True, ensure_ascii=True) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
