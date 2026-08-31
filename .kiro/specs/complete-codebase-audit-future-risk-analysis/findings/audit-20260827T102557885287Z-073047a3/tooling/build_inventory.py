from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

RUN_ROOT = Path(__file__).resolve().parents[1]
ROOT = RUN_ROOT.parents[5]
sys.path.insert(0, str(RUN_ROOT / "tooling"))
from audit_controls import validate_inventory, write_json, write_jsonl  # noqa: E402

TEXT_EXTENSIONS = {".py", ".md", ".txt", ".ini", ".yaml", ".yml", ".toml", ".html", ".css", ".js", ".json", ".jsonl", ".csv", ".gitignore", ".example"}
STRUCTURE_EXTENSIONS = {".sqlite", ".sqlite3", ".db", ".pdf", ".docx", ".xlsx", ".zip", ".pack", ".idx"}
METADATA_EXTENSIONS = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico"}


def owner(path: str) -> tuple[str, list[str]]:
    lower = path.casefold()
    if lower.startswith("tests/") or lower in {"test_all.py", "test_audit.py", "pytest.ini", "test_report.md", "context_audit.py", "context_audit_results.json"} or "/.pytest_cache/" in "/" + lower:
        return "testing-quality", ["application-flow", "safety", "security-privacy"]
    if lower.startswith("app/safety/") or lower.startswith("app/prompts/"):
        return "safety", ["application-flow", "testing-quality", "security-privacy"]
    if lower.startswith("app/cag/") or lower.startswith("app/memory/") or lower.startswith("knowledge/") or lower.startswith("cache/") or lower == "build_cache.py":
        return "memory-rag-cag", ["safety", "persistence", "deployment-operations"]
    if lower.startswith("app/storage/") or lower.startswith("data/"):
        return "persistence", ["security-privacy", "testing-quality", "deployment-operations"]
    if lower in {"app/security.py", "app/identity.py", ".env", ".env.example", ".gitignore"} or lower.startswith(".git/"):
        return "security-privacy", ["application-flow", "deployment-operations"]
    if lower in {"render.yaml", "procfile", "requirements.txt", "readme.md", "developer_guide.md"} or lower.startswith(".vscode/") or lower.startswith("__pycache__/"):
        return "deployment-operations", ["security-privacy", "testing-quality", "application-flow"]
    if lower == "main.py" or lower.startswith("ui/") or lower.startswith("app/chatbot/") or lower in {"app/normalize.py", "app/types.py", "app/utils.py", "app/__init__.py", "app/llm/client.py", "app/llm/__init__.py", "app/config/settings.py", "app/config/__init__.py"}:
        return "application-flow", ["safety", "security-privacy", "persistence", "testing-quality"]
    if lower.startswith(".kiro/specs/complete-codebase-audit-future-risk-analysis/findings/"):
        return "testing-quality", ["security-privacy"]
    if lower.startswith(".kiro/"):
        return "deployment-operations", ["testing-quality"]
    return "deployment-operations", []


def classify(path: str, entry_type: str) -> tuple[str, str, str, str, list[str]]:
    lower = path.casefold()
    suffix = Path(path).suffix.casefold()
    sensitive_classes: list[str] = []
    if lower == ".env":
        return "metadata-reviewed", "Sensitive live environment file; contents intentionally not opened or reproduced.", "Only path, size, hash, and metadata reviewed to prevent secret disclosure.", "security-critical", ["secrets", "credentials"]
    if lower.startswith("data/"):
        sensitive_classes.extend(["conversation-or-user-data", "health-related-data"])
    if lower.startswith(".git/"):
        if suffix in {"", ".lock", ".idx", ".pack", ".rev", ".sample"}:
            return "metadata-reviewed", "Version-control internal or opaque object.", "Object bytes were hashed; semantic content/history reviewed separately through bounded Git metadata commands.", "security-relevant", sensitive_classes
    if entry_type != "regular":
        return "metadata-reviewed", "Non-regular baseline entry.", "Link/special-entry metadata reviewed without dereferencing.", "operational", sensitive_classes
    if suffix in STRUCTURE_EXTENSIONS or lower.endswith((".sqlite-shm", ".sqlite-wal")):
        return "structure-reviewed", "Binary/container/data structure requiring non-text inspection.", "Only schema/container structure, size, and metadata are reviewed; record values are not reproduced.", "data-or-runtime", sensitive_classes
    if suffix in METADATA_EXTENSIONS or "__pycache__/" in lower or lower.startswith(".pytest_cache/"):
        return "metadata-reviewed", "Generated or binary artifact.", "Only type, provenance, hash, size, and metadata reviewed.", "generated", sensitive_classes
    if suffix in TEXT_EXTENSIONS or Path(path).name.casefold() in {"procfile", ".gitignore"}:
        return "content-reviewed", "Readable repository text assigned to a subsystem owner.", "Full semantic review where relevant; generated/historical claims remain untrusted until verified.", "source-or-documentation", sensitive_classes
    return "metadata-reviewed", "Opaque or unsupported textual classification.", "Only baseline hash, type, size, and metadata reviewed.", "other", sensitive_classes


def main() -> None:
    manifest_path = RUN_ROOT / "baseline" / "manifest.jsonl"
    baseline = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line]
    inventory: list[dict[str, Any]] = []
    ownership: dict[str, list[str]] = {}
    for record in baseline:
        path = str(record["path"])
        primary, secondary = owner(path)
        disposition, reason, limit, relevance, sensitivity = classify(path, str(record["entry_type"]))
        if record.get("sensitivity_hint") == "potential-sensitive" and "potential-secret-material" not in sensitivity:
            sensitivity.append("potential-secret-material")
        row = {
            "schema_version": "1.0", "run_id": RUN_ROOT.name, "path": path,
            "file_type": str(record["entry_type"]) + (Path(path).suffix.casefold() or ""),
            "size_bytes": record["size_bytes"], "audit_relevance": relevance,
            "sensitive": bool(sensitivity), "sensitivity_classes": sensitivity,
            "disposition": disposition, "disposition_reason": reason,
            "inspection_limit": limit, "primary_owner": primary,
            "secondary_consumers": sorted(set(secondary) - {primary}),
            "baseline_ref": f"baseline/manifest.jsonl:{path}", "evidence_refs": [f"baseline-sha256:{str(record.get('sha256') or 'n/a')[:12]}"],
        }
        inventory.append(row)
        ownership.setdefault(primary, []).append(path)
    validate_inventory([str(row["path"]) for row in baseline], inventory)
    inventory_dir = RUN_ROOT / "inventory"
    write_jsonl(inventory_dir / "inventory.jsonl", inventory)
    write_json(inventory_dir / "ownership-map.json", {key: sorted(values, key=str.casefold) for key, values in sorted(ownership.items())})
    dispositions: dict[str, int] = {}
    for row in inventory:
        dispositions[row["disposition"]] = dispositions.get(row["disposition"], 0) + 1
    reconciliation = {
        "schema_version": "1.0", "run_id": RUN_ROOT.name, "gate": "G2", "outcome": "pass",
        "baseline_count": len(baseline), "inventory_count": len(inventory),
        "canonical_unique_count": len({str(row["path"]).replace('\\', '/').casefold() for row in inventory}),
        "one_primary_owner_per_file": all(bool(row["primary_owner"]) for row in inventory),
        "disposition_counts": dispositions, "sensitive_file_count": sum(bool(row["sensitive"]) for row in inventory),
        "owner_counts": {key: len(value) for key, value in ownership.items()},
        "limitations": ["Sensitive live configuration and user/data stores received metadata/structure review without value reproduction.", "Opaque Git objects and generated bytecode received metadata review; reachable history is reviewed separately."],
    }
    write_json(inventory_dir / "reconciliation.json", reconciliation)
    print(json.dumps(reconciliation))


if __name__ == "__main__":
    main()
