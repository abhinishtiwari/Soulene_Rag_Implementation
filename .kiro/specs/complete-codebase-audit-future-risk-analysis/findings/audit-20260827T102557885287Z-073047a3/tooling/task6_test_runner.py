from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

RUN_ID = "audit-20260827T102557885287Z-073047a3"
SCHEMA_VERSION = "1.0"
RESULT_CLASSES = {
    "pass", "product-failure", "test-defect", "environment-failure",
    "dependency-failure", "inconclusive", "skipped-ineligible",
}
NATIVE_STATUSES = {
    "passed", "failed", "skipped", "xfailed", "xpassed", "error", "not-run",
}
SENSITIVE_ENV_KEYS = {
    "OPENAI_API_KEY", "MONGO_URI", "API_KEY", "ADMIN_API_KEY",
    "DATABASE_URL", "RUN_MONGO_INTEGRATION", "STAGING_URL", "STAGING_API_KEY",
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
}
ALLOWED_SOURCE_PREFIXES = ("app/", "tests/", "ui/", "knowledge/")
ALLOWED_SOURCE_FILES = {
    "main.py", "build_cache.py", "test_audit.py", "test_all.py",
    "context_audit.py", "pytest.ini",
}
OMITTED_PREFIXES = (
    ".git/", ".kiro/", ".pytest_cache/", ".vscode/", "data/", "cache/",
    "vector_store/", "__pycache__/",
)
OMITTED_SUFFIXES = (".pyc", ".pyo", ".sqlite", ".sqlite3", ".db")
SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|token|secret|password|mongo(?:db)?(?:\+srv)?://)"
    r"\s*[:=]\s*([^\s,;]+)"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} is not an object")
            records.append(value)
    return records


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def atomic_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(dict(record), sort_keys=True) + "\n")
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def environment_policy_digest(keys: Sequence[str]) -> str:
    serialized = json.dumps(sorted(keys), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def eligibility_for(record: Mapping[str, Any]) -> tuple[str, str]:
    path = str(record["path"])
    kind = str(record["kind"])
    if path == "tests/smoke_live.py":
        return "ineligible", "Live model smoke requires provider credentials, uncontrolled external network, and application persistence."
    if path == "tests/smoke_staging.py":
        return "ineligible", "Staging smoke requires an external HTTP endpoint and optional staging credentials."
    if path == "tests/test_mongo_integration.py":
        return "ineligible", "Real Mongo replica-set suite requires network access, credentials, child processes, database writes, and database deletion."
    if kind != "test-case":
        return "ineligible", (
            f"Cataloged {kind} is support/setup behavior invoked by test cases or a script, "
            "not a standalone executable test; accounting it as a separate run would misrepresent coverage."
        )
    return "eligible", (
        "Actual test case uses fake/in-process clients or sandbox-local temporary/storage paths; "
        "eligible only after copied-baseline, path, network-denial, and integrity attestations pass."
    )


def discovery_source(record: Mapping[str, Any]) -> str:
    path = str(record["path"])
    if path == "test_audit.py":
        return "architecture:EP-ROOT-AUDIT and static catalog"
    if path == "test_all.py":
        return "architecture:EP-ROOT-ALL and static catalog"
    if path == "context_audit.py":
        return "architecture:EP-CONTEXT-AUDIT and static catalog"
    if path.startswith("tests/"):
        return "pytest.ini:testpaths plus static catalog"
    return "static catalog"


def coverage_refs(record: Mapping[str, Any]) -> list[str]:
    refs = [f"subsystem:{name}" for name in record.get("subsystems", [])]
    refs.extend(f"safety-path:{name}" for name in record.get("safety_paths", []))
    refs.extend(f"baseline-requirement:{name}" for name in record.get("represented_requirements", []))
    refs.append("architecture:EP-PYTEST" if str(record["path"]).startswith("tests/") else "architecture:test-entrypoint")
    return sorted(set(refs))


def make_plan_record(record: Mapping[str, Any], classified_at: str) -> dict[str, Any]:
    eligibility, reason = eligibility_for(record)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": RUN_ID,
        "record_type": "test-ledger",
        "test_id": record["test_id"],
        "path": record["path"],
        "framework": record["framework"],
        "selector_or_entrypoint": record["node_id"],
        "discovery_source": discovery_source(record),
        "kind": record["kind"],
        "subsystems": record.get("subsystems", []),
        "safety_paths": record.get("safety_paths", []),
        "mutability_risks": record.get("mutability_risks", []),
        "network_risks": record.get("network_risks", []),
        "credential_risks": record.get("credential_risks", []),
        "import_startup_risks": record.get("import_startup_risks", []),
        "assertion_quality": record.get("assertion_quality", "unknown"),
        "eligibility": eligibility,
        "eligibility_reason": reason,
        "classification_time": classified_at,
        "exact_command": None,
        "sandbox_attestation_ref": None,
        "execution_status": "classified" if eligibility == "eligible" else "skipped-ineligible",
        "result_class": None if eligibility == "eligible" else "skipped-ineligible",
        "native_status": None if eligibility == "eligible" else "not-run",
        "exit_status": None,
        "started_utc": None,
        "completed_utc": None,
        "duration_ms": None,
        "redacted_output_ref": None,
        "failure_output_summary": None,
        "finding_refs": [],
        "coverage_refs": coverage_refs(record),
    }


def build_plan(repo_root: Path, run_root: Path) -> list[dict[str, Any]]:
    catalog_path = run_root / "tests" / "catalog.jsonl"
    catalog = read_jsonl(catalog_path)
    if len(catalog) != 411:
        raise RuntimeError(f"Expected 411 catalog records, found {len(catalog)}")
    ids = [str(item["test_id"]) for item in catalog]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Catalog test IDs are not unique")
    classified_at = utc_now()
    records = [make_plan_record(item, classified_at) for item in catalog]
    atomic_jsonl(run_root / "tests" / "pre-execution-ledger.jsonl", records)
    counts = Counter(item["eligibility"] for item in records)
    kinds = Counter(str(item["kind"]) for item in records)
    policy = {
        "schema_version": SCHEMA_VERSION,
        "run_id": RUN_ID,
        "record_type": "sandbox-execution-policy",
        "repository_root": str(repo_root),
        "sandbox_root": str(run_root / "sandbox"),
        "classification_time": classified_at,
        "catalog_count": len(records),
        "eligibility_counts": dict(sorted(counts.items())),
        "kind_counts": dict(sorted(kinds.items())),
        "decision_order": [
            "deny live credentials, external HTTP/model, and real Mongo",
            "deny destructive or uncontainable execution",
            "account helpers/fixtures without standalone execution",
            "require actual test-case kind",
            "require passing copied-baseline, path, network, process, and integrity attestations",
        ],
        "copied_input_policy": "baseline-verified application, test, UI, and knowledge fixture bytes only",
        "omitted_sensitive_classes": [
            "live .env and credentials", "Git metadata", "persistent data and databases",
            "identity material and user conversations", "baseline caches and generated bytecode",
        ],
        "sanitized_environment_key_names": sorted(minimal_environment(repo_root, run_root, run_root / "sandbox" / "source", run_root / "sandbox" / "control").keys()),
        "network_policy": "Python startup guard denies socket creation/connect and DNS resolution; probe must pass before imports/tests.",
        "process_policy": "CREATE_NEW_PROCESS_GROUP; bounded timeout; taskkill /T /F on timeout; process inventories recorded.",
        "timeout_ms_per_command": 180000,
        "execution_rule": "Each eligible test-case node selector appears in exactly one bounded non-watch pytest command.",
    }
    atomic_json(run_root / "tests" / "sandbox-policy.json", policy)
    return records


def minimal_environment(repo_root: Path, run_root: Path, source_root: Path, guard_root: Path) -> dict[str, str]:
    sandbox_root = run_root / "sandbox"
    home = sandbox_root / "home"
    temp = sandbox_root / "tmp"
    cache = sandbox_root / "runtime-cache"
    data = source_root / "data"
    for path in (home, temp, cache, data, source_root / "knowledge"):
        path.mkdir(parents=True, exist_ok=True)
    inherited_names = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "NUMBER_OF_PROCESSORS")
    env = {name: os.environ[name] for name in inherited_names if name in os.environ}
    env.update({
        "PYTHONPATH": os.pathsep.join((str(guard_root), str(source_root))),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "HOME": str(home),
        "USERPROFILE": str(home),
        "TEMP": str(temp),
        "TMP": str(temp),
        "TMPDIR": str(temp),
        "XDG_CACHE_HOME": str(cache),
        "SOULENE_SKIP_WARM": "1",
        "OPENAI_API_KEY": "",
        "MONGO_URI": "",
        "STORAGE_BACKEND": "sqlite",
        "RUN_MONGO_INTEGRATION": "0",
        "API_KEY": "",
        "ADMIN_API_KEY": "",
        "IDENTITY_SECRET": "synthetic-audit-identity-secret-at-least-32-bytes",
        "ENABLE_INPUT_MODERATION": "0",
        "ENABLE_SEMANTIC_SAFETY": "0",
        "ENABLE_OUTPUT_SAFETY_CHECK": "0",
        "LOG_LEVEL": "WARNING",
    })
    for key in SENSITIVE_ENV_KEYS:
        if key not in env:
            env[key] = ""
    return env


def protected_snapshot(repo_root: Path, manifest: Sequence[Mapping[str, Any]], phase: str) -> dict[str, Any]:
    mismatches: list[dict[str, Any]] = []
    checked = 0
    for expected in manifest:
        relative = str(expected["path"])
        target = repo_root / Path(PurePosixPath(relative))
        if not target.is_file():
            mismatches.append({"path": relative, "mismatch": "missing"})
            continue
        checked += 1
        observed_sha = sha256_file(target)
        observed_size = target.stat().st_size
        observed_mode = stat.S_IMODE(target.stat().st_mode)
        expected_mode = stat.S_IMODE(int(expected.get("stable_metadata", {}).get("mode", target.stat().st_mode)))
        differences: list[str] = []
        if observed_sha != expected.get("sha256"):
            differences.append("sha256")
        if observed_size != expected.get("size_bytes"):
            differences.append("size_bytes")
        if observed_mode != expected_mode:
            differences.append("mode")
        if differences:
            mismatches.append({"path": relative, "mismatch": "changed", "fields": differences})
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": RUN_ID,
        "record_type": "protected-tree-snapshot",
        "phase": phase,
        "captured_utc": utc_now(),
        "baseline_count": len(manifest),
        "checked_count": checked,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "integrity_ok": not mismatches and checked == len(manifest),
        "sensitive_content_persisted": False,
    }


def source_copy_allowed(record: Mapping[str, Any]) -> bool:
    relative = str(record["path"]).replace("\\", "/")
    lower = relative.lower()
    if str(record.get("sensitivity_hint", "none")) != "none":
        return False
    if lower == ".env" or any(lower.startswith(prefix) for prefix in OMITTED_PREFIXES):
        return False
    if "/__pycache__/" in lower or lower.endswith(OMITTED_SUFFIXES):
        return False
    return relative in ALLOWED_SOURCE_FILES or any(relative.startswith(prefix) for prefix in ALLOWED_SOURCE_PREFIXES)


def copy_baseline_inputs(repo_root: Path, run_root: Path, manifest: Sequence[Mapping[str, Any]]) -> tuple[Path, list[dict[str, Any]]]:
    source_root = run_root / "sandbox" / "source"
    if source_root.exists():
        shutil.rmtree(source_root)
    source_root.mkdir(parents=True)
    copied: list[dict[str, Any]] = []
    for record in manifest:
        if not source_copy_allowed(record):
            continue
        relative = str(record["path"])
        source = repo_root / Path(PurePosixPath(relative))
        if not source.is_file():
            raise RuntimeError(f"Baseline input disappeared: {relative}")
        observed = sha256_file(source)
        if observed != record["sha256"]:
            raise RuntimeError(f"Baseline input changed before copy: {relative}")
        destination = source_root / Path(PurePosixPath(relative))
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        copied_hash = sha256_file(destination)
        if copied_hash != record["sha256"]:
            raise RuntimeError(f"Copied input hash mismatch: {relative}")
        copied.append({"path": relative, "sha256": copied_hash, "size_bytes": destination.stat().st_size})
    return source_root, copied


def write_network_guard(guard_root: Path) -> None:
    guard_root.mkdir(parents=True, exist_ok=True)
    code = '''"""Audit sandbox network denial loaded automatically by Python."""
import socket

class AuditNetworkDenied(PermissionError):
    pass

def _deny(*args, **kwargs):
    raise AuditNetworkDenied("audit sandbox denies DNS and network access")

class DeniedSocket(socket.socket):
    def __new__(cls, *args, **kwargs):
        raise AuditNetworkDenied("audit sandbox denies socket creation")

socket.socket = DeniedSocket
socket.create_connection = _deny
socket.getaddrinfo = _deny
socket.gethostbyname = _deny
socket.gethostbyname_ex = _deny
socket.gethostbyaddr = _deny
'''
    (guard_root / "sitecustomize.py").write_text(code, encoding="utf-8")


def process_inventory() -> list[dict[str, Any]]:
    try:
        completed = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
            timeout=15, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        rows = csv.reader(completed.stdout.splitlines())
        result = []
        for row in rows:
            if len(row) >= 2 and row[1].replace(",", "").isdigit():
                result.append({"image": row[0], "pid": int(row[1].replace(",", ""))})
        return sorted(result, key=lambda item: item["pid"])
    except Exception:
        return []


def run_bounded(command: Sequence[str], cwd: Path, env: Mapping[str, str], timeout_seconds: int) -> dict[str, Any]:
    started = utc_now()
    before = process_inventory()
    started_perf = time.perf_counter()
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(
        list(command), cwd=str(cwd), env=dict(env), stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        creationflags=flags,
    )
    timed_out = False
    try:
        output, _ = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True, text=True, timeout=30, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        output, _ = process.communicate(timeout=30)
    duration_ms = int((time.perf_counter() - started_perf) * 1000)
    after = process_inventory()
    before_ids = {item["pid"] for item in before}
    leaked = [item for item in after if item["pid"] not in before_ids and item["pid"] != os.getpid()]
    return {
        "started_utc": started,
        "completed_utc": utc_now(),
        "duration_ms": duration_ms,
        "exit_status": process.returncode,
        "timed_out": timed_out,
        "output": output,
        "process_inventory_before": before,
        "process_inventory_after": after,
        "new_processes_after": leaked,
    }


def probe_network(source_root: Path, guard_root: Path, env: Mapping[str, str]) -> dict[str, Any]:
    probe = (
        "import socket; ok=0\n"
        "for action in (lambda: socket.getaddrinfo('example.invalid',443), "
        "lambda: socket.socket()):\n"
        "  try: action()\n"
        "  except PermissionError: ok+=1\n"
        "raise SystemExit(0 if ok==2 else 9)"
    )
    result = run_bounded([sys.executable, "-c", probe], source_root, env, 30)
    return {
        "command": subprocess.list2cmdline([sys.executable, "-c", probe]),
        "passed": result["exit_status"] == 0 and not result["timed_out"],
        "exit_status": result["exit_status"],
        "duration_ms": result["duration_ms"],
        "mechanism": "sitecustomize Python socket constructor/connect/DNS denial inherited by child Python processes",
    }


def pytest_selector(node_id: str) -> str:
    path, symbol = node_id.split("::", 1)
    if "." in symbol:
        owner, method = symbol.rsplit(".", 1)
        return f"{path}::{owner}::{method}"
    return f"{path}::{symbol}"


def batches(records: Sequence[Mapping[str, Any]], max_chars: int = 5500) -> list[list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["path"])].append(record)
    result: list[list[Mapping[str, Any]]] = []
    for path in sorted(grouped):
        current: list[Mapping[str, Any]] = []
        current_chars = 0
        for record in sorted(grouped[path], key=lambda item: str(item["test_id"])):
            length = len(pytest_selector(str(record["selector_or_entrypoint"]))) + 1
            if current and current_chars + length > max_chars:
                result.append(current)
                current, current_chars = [], 0
            current.append(record)
            current_chars += length
        if current:
            result.append(current)
    return result


def redact_output(text: str, repo_root: Path) -> str:
    redacted = text.replace(str(repo_root), "[REDACTED REPOSITORY ROOT]")
    redacted = SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED SYNTHETIC OR SENSITIVE VALUE]", redacted)
    redacted = re.sub(r"(?i)sk-[A-Za-z0-9_-]{8,}", "[REDACTED API KEY]", redacted)
    return redacted


def parse_junit(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    root = ET.parse(path).getroot()
    cases: list[dict[str, Any]] = []
    for case in root.iter("testcase"):
        status = "passed"
        detail = ""
        if case.find("failure") is not None:
            status = "failed"
            detail = (case.find("failure").get("message") or "")[:500]
        elif case.find("error") is not None:
            status = "error"
            detail = (case.find("error").get("message") or "")[:500]
        elif case.find("skipped") is not None:
            message = case.find("skipped").get("message") or ""
            status = "xfailed" if "xfail" in message.lower() else "skipped"
            detail = message[:500]
        cases.append({
            "classname": case.get("classname", ""),
            "name": case.get("name", ""),
            "duration_ms": int(float(case.get("time", "0") or 0) * 1000),
            "native_status": status,
            "detail": detail,
        })
    return cases


def junit_case_for(record: Mapping[str, Any], cases: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    symbol = str(record["selector_or_entrypoint"]).split("::", 1)[1]
    if "." in symbol:
        owner, method = symbol.rsplit(".", 1)
        matches = [case for case in cases if case["name"] == method and str(case["classname"]).endswith(owner)]
    else:
        matches = [case for case in cases if case["name"] == symbol]
    return matches[0] if len(matches) == 1 else None


def audit_result(record: Mapping[str, Any], native: str, detail: str, output: str) -> tuple[str, str | None]:
    combined = (detail + "\n" + output).lower()
    if native == "passed":
        if str(record["path"]) == "test_audit.py":
            return "inconclusive", "Behavior-only root audit function has no enforceable assertions; native pass does not prove its printed checks."
        return "pass", None
    if native in {"skipped", "xfailed", "xpassed"}:
        return "inconclusive", detail or f"Framework reported {native}."
    if "modulenotfounderror" in combined or "importerror" in combined or "no module named" in combined:
        return "dependency-failure", detail or "Test could not import a required dependency."
    if "timeout" in combined or "audit sandbox" in combined or "network" in combined:
        return "environment-failure", detail or "Sandbox bound or network denial interrupted execution."
    if native == "failed":
        return "product-failure", detail or "Test assertion failed against baseline behavior."
    return "environment-failure", detail or "Test framework reported an execution error."


def validate_test_ledger(
    discovered_ids: Sequence[str],
    ledger: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    attestations: Mapping[str, Mapping[str, Any]],
) -> None:
    errors: list[str] = []
    ids = [str(item.get("test_id", "")) for item in ledger]
    if len(ids) != len(set(ids)) or set(ids) != set(discovered_ids) or len(ids) != len(discovered_ids):
        errors.append("ledger is not a one-to-one cover of discovered test IDs")
    event_positions: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for position, event in enumerate(events):
        event_positions[str(event.get("test_id"))][str(event.get("state"))].append(position)
    for record in ledger:
        test_id = str(record.get("test_id"))
        eligibility = record.get("eligibility")
        positions = event_positions[test_id]
        if eligibility not in {"eligible", "ineligible"}:
            errors.append(f"{test_id}: missing singular eligibility decision")
            continue
        if len(positions.get("classified", [])) != 1:
            errors.append(f"{test_id}: classification event must occur exactly once")
        if eligibility == "ineligible":
            if record.get("execution_status") != "skipped-ineligible" or not str(record.get("eligibility_reason", "")).strip():
                errors.append(f"{test_id}: invalid ineligible accounting")
            if record.get("native_status") != "not-run" or record.get("exact_command") not in {None, ""}:
                errors.append(f"{test_id}: ineligible record looks executed")
            if positions.get("executing"):
                errors.append(f"{test_id}: ineligible record executed")
            continue
        if record.get("execution_status") != "terminal":
            errors.append(f"{test_id}: eligible record lacks terminal result")
            continue
        attestation = attestations.get(test_id, {})
        if not (attestation.get("integrity_ok") and attestation.get("path_containment_ok") and attestation.get("network_probe_result") == "pass"):
            errors.append(f"{test_id}: executing record lacks passing attestation")
        if record.get("result_class") not in RESULT_CLASSES or record.get("native_status") not in NATIVE_STATUSES:
            errors.append(f"{test_id}: invalid terminal classifications")
        if not record.get("exact_command") or not record.get("redacted_output_ref"):
            errors.append(f"{test_id}: terminal evidence incomplete")
        classified = positions.get("classified", [])
        attested = positions.get("attested", [])
        executing = positions.get("executing", [])
        terminal = positions.get("terminal", [])
        if not (len(attested) == len(executing) == len(terminal) == 1 and classified):
            errors.append(f"{test_id}: eligible transition cardinality invalid")
        elif not (classified[0] < attested[0] < executing[0] < terminal[0]):
            errors.append(f"{test_id}: eligible transition ordering invalid")
    if errors:
        raise ValueError("; ".join(errors))


def execute_plan(repo_root: Path, run_root: Path) -> None:
    plan_path = run_root / "tests" / "pre-execution-ledger.jsonl"
    if not plan_path.is_file():
        raise RuntimeError("Run plan mode before execute mode")
    ledger = read_jsonl(plan_path)
    manifest = read_jsonl(run_root / "baseline" / "manifest.jsonl")
    before = protected_snapshot(repo_root, manifest, "before-test-execution")
    atomic_json(run_root / "tests" / "protected-before.json", before)
    if not before["integrity_ok"]:
        raise RuntimeError("Protected tree differs from baseline before execution")

    source_root, copied = copy_baseline_inputs(repo_root, run_root, manifest)
    guard_root = run_root / "sandbox" / "control"
    write_network_guard(guard_root)
    env = minimal_environment(repo_root, run_root, source_root, guard_root)
    resolved_paths = [
        source_root, run_root / "sandbox" / "home", run_root / "sandbox" / "tmp",
        run_root / "sandbox" / "runtime-cache", source_root / "data", source_root / "knowledge",
    ]
    sandbox_root = (run_root / "sandbox").resolve()
    path_containment_ok = all(path.resolve().is_relative_to(sandbox_root) for path in resolved_paths)
    probe = probe_network(source_root, guard_root, env)
    process_before = process_inventory()
    attestation = {
        "schema_version": SCHEMA_VERSION,
        "run_id": RUN_ID,
        "record_type": "sandbox-attestation",
        "sandbox_root": str(sandbox_root),
        "copied_input_count": len(copied),
        "copied_inputs_ref": "sandbox/copied-inputs.jsonl",
        "omitted_sensitive_classes": [
            "live .env and credentials", "persistent databases/data", "identity material",
            "user conversations", "Git metadata", "baseline caches and bytecode",
        ],
        "environment_allowlist_digest": environment_policy_digest(list(env)),
        "environment_key_names": sorted(env),
        "environment_values_persisted": False,
        "generated_fixture_refs": ["sandbox/control/sitecustomize.py"],
        "resolved_paths": [str(path.resolve()) for path in resolved_paths],
        "path_containment_ok": path_containment_ok,
        "network_denial_mechanism": probe["mechanism"],
        "network_probe_result": "pass" if probe["passed"] else "fail",
        "network_probe": probe,
        "process_tree_policy": "CREATE_NEW_PROCESS_GROUP plus taskkill /T /F on timeout",
        "timeout_ms": 180000,
        "resource_bounds": {"pytest_batch_command_chars": 5500, "watch_mode": False, "server_mode": False},
        "pre_live_snapshot_ref": "tests/protected-before.json",
        "post_live_snapshot_ref": "tests/protected-after.json",
        "integrity_ok": before["integrity_ok"],
        "process_inventory_before": process_before,
    }
    atomic_jsonl(run_root / "sandbox" / "copied-inputs.jsonl", copied)
    atomic_json(run_root / "tests" / "sandbox-attestation.json", attestation)
    if not path_containment_ok or not probe["passed"]:
        raise RuntimeError("Sandbox path or network-denial attestation failed")

    eligible = [item for item in ledger if item["eligibility"] == "eligible"]
    events: list[dict[str, Any]] = []
    classified_at = min(str(item["classification_time"]) for item in ledger)
    for item in ledger:
        events.append({"test_id": item["test_id"], "state": "classified", "time": classified_at})
        if item["eligibility"] == "ineligible":
            events.append({"test_id": item["test_id"], "state": "skipped-ineligible", "time": classified_at})

    raw_dir = run_root / "tests" / "raw-output"
    result_dir = run_root / "tests" / "native-results"
    raw_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    by_id = {str(item["test_id"]): item for item in ledger}
    seen_selectors: set[str] = set()
    batch_records: list[dict[str, Any]] = []

    for index, batch in enumerate(batches(eligible), 1):
        selectors = [pytest_selector(str(item["selector_or_entrypoint"])) for item in batch]
        overlap = seen_selectors.intersection(selectors)
        if overlap:
            raise RuntimeError(f"Duplicate execution selectors: {sorted(overlap)}")
        seen_selectors.update(selectors)
        xml_path = result_dir / f"batch-{index:03d}.xml"
        command = [
            sys.executable, "-m", "pytest", "-q", "-s", "-p", "no:cacheprovider",
            "--disable-warnings", f"--junitxml={xml_path}", *selectors,
        ]
        exact = subprocess.list2cmdline(command)
        event_time = utc_now()
        for item in batch:
            events.append({"test_id": item["test_id"], "state": "attested", "time": event_time})
            events.append({"test_id": item["test_id"], "state": "executing", "time": event_time})
        outcome = run_bounded(command, source_root, env, 180)
        redacted = redact_output(outcome["output"], repo_root)
        output_path = raw_dir / f"batch-{index:03d}.txt"
        output_path.write_text(redacted, encoding="utf-8")
        cases = parse_junit(xml_path)
        output_ref = output_path.relative_to(run_root).as_posix()
        for item in batch:
            record = by_id[str(item["test_id"])]
            case = junit_case_for(record, cases)
            if outcome["timed_out"]:
                native, duration, detail = "error", outcome["duration_ms"], "Bounded test command timed out; process tree termination requested."
            elif case is None:
                native, duration, detail = "error", outcome["duration_ms"], "No native per-case result was emitted; collection or environment failure occurred."
            else:
                native = str(case["native_status"])
                duration = int(case["duration_ms"])
                detail = str(case["detail"])
            result_class, summary = audit_result(record, native, detail, redacted)
            record.update({
                "exact_command": exact,
                "sandbox_attestation_ref": "tests/sandbox-attestation.json",
                "execution_status": "terminal",
                "result_class": result_class,
                "native_status": native,
                "exit_status": outcome["exit_status"],
                "started_utc": outcome["started_utc"],
                "completed_utc": outcome["completed_utc"],
                "duration_ms": duration,
                "redacted_output_ref": output_ref,
                "failure_output_summary": summary,
            })
            events.append({"test_id": item["test_id"], "state": "terminal", "time": outcome["completed_utc"]})
        batch_records.append({
            "batch_id": f"BATCH-{index:03d}",
            "test_ids": [item["test_id"] for item in batch],
            "selector_count": len(selectors),
            "exact_command": exact,
            "exit_status": outcome["exit_status"],
            "timed_out": outcome["timed_out"],
            "duration_ms": outcome["duration_ms"],
            "redacted_output_ref": output_ref,
            "native_result_ref": xml_path.relative_to(run_root).as_posix(),
            "new_processes_after": outcome["new_processes_after"],
        })

    expected_selectors = {pytest_selector(str(item["selector_or_entrypoint"])) for item in eligible}
    if seen_selectors != expected_selectors:
        raise RuntimeError("Eligible selector execution accounting mismatch")

    after = protected_snapshot(repo_root, manifest, "after-test-execution")
    atomic_json(run_root / "tests" / "protected-after.json", after)
    attestation["post_live_snapshot_ref"] = "tests/protected-after.json"
    attestation["integrity_ok"] = bool(before["integrity_ok"] and after["integrity_ok"])
    attestation["process_inventory_after"] = process_inventory()
    atomic_json(run_root / "tests" / "sandbox-attestation.json", attestation)
    if not after["integrity_ok"]:
        raise RuntimeError("Protected tree changed during test execution")

    attestation_by_test = {
        str(item["test_id"]): {
            "integrity_ok": attestation["integrity_ok"],
            "path_containment_ok": attestation["path_containment_ok"],
            "network_probe_result": attestation["network_probe_result"],
        }
        for item in eligible
    }
    validate_test_ledger(
        [str(item["test_id"]) for item in ledger], ledger, events, attestation_by_test
    )
    atomic_jsonl(run_root / "tests" / "events.jsonl", events)
    atomic_jsonl(run_root / "tests" / "test-ledger.jsonl", ledger)
    atomic_json(run_root / "tests" / "execution-batches.json", batch_records)

    eligibility_counts = Counter(str(item["eligibility"]) for item in ledger)
    native_counts = Counter(str(item["native_status"]) for item in ledger)
    result_counts = Counter(str(item["result_class"]) for item in ledger)
    subsystem_executed: dict[str, set[str]] = defaultdict(set)
    safety_executed: dict[str, set[str]] = defaultdict(set)
    for item in ledger:
        if item["execution_status"] != "terminal":
            continue
        for subsystem in item["subsystems"]:
            subsystem_executed[str(subsystem)].add(str(item["test_id"]))
        for safety_path in item["safety_paths"]:
            safety_executed[str(safety_path)].add(str(item["test_id"]))
    blockers = []
    for item in ledger:
        if item["result_class"] in {"product-failure", "test-defect", "environment-failure", "dependency-failure"}:
            blockers.append({
                "test_id": item["test_id"], "result_class": item["result_class"],
                "native_status": item["native_status"], "summary": item["failure_output_summary"],
            })
    summary = {
        "schema_version": SCHEMA_VERSION,
        "run_id": RUN_ID,
        "record_type": "test-execution-summary",
        "catalog_total": len(ledger),
        "actual_test_case_total": sum(item["kind"] == "test-case" for item in ledger),
        "support_record_total": sum(item["kind"] != "test-case" for item in ledger),
        "eligibility_counts": dict(sorted(eligibility_counts.items())),
        "executed_test_case_count": sum(item["execution_status"] == "terminal" for item in ledger),
        "command_batch_count": len(batch_records),
        "native_status_counts": dict(sorted(native_counts.items())),
        "result_class_counts": dict(sorted(result_counts.items())),
        "subsystem_observed_coverage": {key: sorted(value) for key, value in sorted(subsystem_executed.items())},
        "safety_path_observed_coverage": {key: sorted(value) for key, value in sorted(safety_executed.items())},
        "blockers": blockers,
        "ineligible_classes": {
            "live-model-smoke": [item["test_id"] for item in ledger if item["path"] == "tests/smoke_live.py"],
            "staging-http-smoke": [item["test_id"] for item in ledger if item["path"] == "tests/smoke_staging.py"],
            "real-mongo": [item["test_id"] for item in ledger if item["path"] == "tests/test_mongo_integration.py"],
            "support-not-standalone": [item["test_id"] for item in ledger if item["kind"] not in {"test-case", "script-entry"}],
        },
        "limitations": [
            "Live model, staging HTTP, and real Mongo behavior was not executed by policy.",
            "Cataloged helpers and fixtures are covered through their invoking test cases, not counted as standalone executions.",
            "Root test_audit.py functions have no enforceable assertions; native passes are audit-inconclusive.",
            "Python-level egress denial is attested for Python tests; no claim is made for external production network controls.",
        ],
        "protected_integrity_ok": attestation["integrity_ok"],
        "network_probe_passed": probe["passed"],
        "path_containment_ok": path_containment_ok,
    }
    atomic_json(run_root / "tests" / "execution-summary.json", summary)
    gate = {
        "schema_version": SCHEMA_VERSION,
        "run_id": RUN_ID,
        "gate": "G5",
        "outcome": "pass" if (
            len(ledger) == 411
            and eligibility_counts["eligible"] == summary["executed_test_case_count"]
            and attestation["integrity_ok"]
            and probe["passed"]
            and path_containment_ok
        ) else "fail",
        "catalog_total": len(ledger),
        "classified_total": len(ledger),
        "eligible_total": eligibility_counts["eligible"],
        "executed_total": summary["executed_test_case_count"],
        "ineligible_total": eligibility_counts["ineligible"],
        "terminal_accounting_total": sum(item["execution_status"] in {"terminal", "skipped-ineligible"} for item in ledger),
        "protected_integrity_ok": attestation["integrity_ok"],
        "network_probe_passed": probe["passed"],
        "property_5_status": "pending-task-6.3",
        "blocker_count": len(blockers),
    }
    atomic_json(run_root / "tests" / "gate-g5.json", gate)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("plan", "execute"))
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    run_root = args.run_root.resolve()
    if run_root.name != RUN_ID or not run_root.is_relative_to(repo_root):
        raise RuntimeError("Run root identity or containment mismatch")
    if args.mode == "plan":
        build_plan(repo_root, run_root)
    else:
        execute_plan(repo_root, run_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
