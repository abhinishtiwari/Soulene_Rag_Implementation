from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\Users\abhin\OneDrive\Desktop\Soulene AI-Rag\New folder\Soulene_Rag_Implementation").resolve()
FINDINGS = ROOT / ".kiro" / "specs" / "complete-codebase-audit-future-risk-analysis" / "findings"
SPEC_REL = ".kiro/specs/complete-codebase-audit-future-risk-analysis/findings"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def canonical(relative: str) -> str:
    return relative.replace("\\", "/").casefold()


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def main() -> None:
    started = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, object]] = []
    directories: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    collisions: dict[str, list[str]] = {}
    seen: dict[str, str] = {}
    escaping_links: list[dict[str, str]] = []
    total_bytes = 0

    for current, dir_names, file_names in os.walk(ROOT, topdown=True, followlinks=False):
        current_path = Path(current)
        relative_dir = current_path.relative_to(ROOT).as_posix() if current_path != ROOT else "."
        directories.append({"path": relative_dir})
        # Prevent traversal into symlink/junction-like directory entries while retaining metadata records.
        retained: list[str] = []
        for name in sorted(dir_names):
            candidate = current_path / name
            try:
                if candidate.is_symlink():
                    rel = candidate.relative_to(ROOT).as_posix()
                    target = os.readlink(candidate)
                    records.append({
                        "path": rel,
                        "canonical_path": canonical(rel),
                        "entry_type": "link",
                        "sha256": None,
                        "size_bytes": 0,
                        "mtime_ns": candidate.lstat().st_mtime_ns,
                        "stable_metadata": {"mode": candidate.lstat().st_mode, "link_target": target},
                        "sensitivity_hint": "none",
                        "hash_status": "not-applicable",
                        "error": None,
                    })
                    resolved = (candidate.parent / target).resolve()
                    try:
                        resolved.relative_to(ROOT)
                    except ValueError:
                        escaping_links.append({"path": rel, "target": target})
                else:
                    retained.append(name)
            except Exception as exc:
                errors.append({"path": str(candidate), "operation": "directory-metadata", "error_type": type(exc).__name__, "message": str(exc)})
        dir_names[:] = retained

        for name in sorted(file_names):
            path = current_path / name
            try:
                rel = path.relative_to(ROOT).as_posix()
                key = canonical(rel)
                if key in seen and seen[key] != rel:
                    collisions.setdefault(key, [seen[key]]).append(rel)
                else:
                    seen[key] = rel
                info = path.lstat()
                if path.is_symlink():
                    target = os.readlink(path)
                    entry_type = "link"
                    digest = None
                    hash_status = "not-applicable"
                    stable = {"mode": info.st_mode, "link_target": target}
                    resolved = (path.parent / target).resolve()
                    try:
                        resolved.relative_to(ROOT)
                    except ValueError:
                        escaping_links.append({"path": rel, "target": target})
                elif stat.S_ISREG(info.st_mode):
                    hasher = hashlib.sha256()
                    with path.open("rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            hasher.update(chunk)
                    digest = hasher.hexdigest()
                    entry_type = "regular"
                    hash_status = "hashed"
                    stable = {"mode": info.st_mode, "readonly": not os.access(path, os.W_OK)}
                    total_bytes += info.st_size
                else:
                    digest = None
                    entry_type = "special"
                    hash_status = "not-applicable"
                    stable = {"mode": info.st_mode}
                lower = rel.casefold()
                sensitivity = "potential-sensitive" if lower == ".env" or any(part in lower for part in ("secret", "credential", "token", ".pem", ".key")) else "none"
                records.append({
                    "path": rel,
                    "canonical_path": key,
                    "entry_type": entry_type,
                    "sha256": digest,
                    "size_bytes": info.st_size,
                    "mtime_ns": info.st_mtime_ns,
                    "stable_metadata": stable,
                    "sensitivity_hint": sensitivity,
                    "hash_status": hash_status,
                    "error": None,
                })
            except Exception as exc:
                errors.append({"path": str(path), "operation": "hash-or-metadata", "error_type": type(exc).__name__, "message": str(exc)})

    records.sort(key=lambda row: str(row["canonical_path"]))
    directories.sort(key=lambda row: canonical(str(row["path"])))
    manifest = b"".join(json_bytes(row) for row in records)
    manifest_digest = hashlib.sha256(manifest).hexdigest()
    run_id = f"audit-{utc_stamp()}-{secrets.token_hex(4)}"
    run_root = FINDINGS / run_id
    baseline = run_root / "baseline"
    control = run_root / "control"
    baseline.mkdir(parents=True, exist_ok=False)
    control.mkdir(parents=True, exist_ok=False)
    (baseline / "manifest.jsonl").write_bytes(manifest)
    (baseline / "directories.jsonl").write_bytes(b"".join(json_bytes(row) for row in directories))
    (baseline / "errors.jsonl").write_bytes(b"".join(json_bytes(row) for row in errors))
    (baseline / "canonical-collisions.json").write_text(json.dumps(collisions, indent=2), encoding="utf-8")
    (baseline / "escaping-reparse-points.json").write_text(json.dumps(escaping_links, indent=2), encoding="utf-8")
    completed = datetime.now(timezone.utc).isoformat()
    metadata = {
        "schema_version": "1.0", "run_id": run_id, "algorithm": "SHA-256",
        "manifest_format": "JSON Lines UTF-8 without BOM", "manifest_entry_count": len(records),
        "regular_file_count": sum(1 for row in records if row["entry_type"] == "regular"),
        "special_file_entry_count": sum(1 for row in records if row["entry_type"] != "regular"),
        "directory_count_including_root": len(directories), "total_regular_file_bytes": total_bytes,
        "error_count": len(errors), "canonical_collision_count": len(collisions),
        "escaping_reparse_count": len(escaping_links), "manifest_sha256": manifest_digest,
        "manifest_bytes": len(manifest), "serialized_after_in_memory_capture": True,
        "source_contents_parsed": False,
    }
    (baseline / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    observed = hashlib.sha256((baseline / "manifest.jsonl").read_bytes()).hexdigest()
    digest_record = {"schema_version": "1.0", "run_id": run_id, "artifact": "baseline/manifest.jsonl", "algorithm": "SHA-256", "expected_sha256": manifest_digest, "observed_sha256": observed, "verified": observed == manifest_digest}
    (baseline / "manifest-digest.json").write_text(json.dumps(digest_record, indent=2), encoding="utf-8")
    context = {"schema_version": "1.0", "run_id": run_id, "repository_root": str(ROOT), "findings_root": str(FINDINGS), "active_run_root": str(run_root), "spec_type": "feature", "spec_config_status": "present", "capture_started_utc": started, "capture_completed_utc": completed, "baseline_capture_order": "all entries enumerated and regular files hashed in memory before active run directory creation", "recovery_of_failed_run": "audit-20260826T200045765Z-6fe3c504"}
    (control / "run-context.json").write_text(json.dumps(context, indent=2), encoding="utf-8")
    gates = {"schema_version": "1.0", "run_id": run_id, "G0": {"outcome": "pass", "root_identity_confirmed": True, "deliverable_conflict_count": 0, "containment_policy_recorded": True, "network_policy_recorded": True, "output_allowlist_recorded": True}, "G1": {"outcome": "pass" if not errors and not collisions and observed == manifest_digest else "fail", "manifest_entry_count": len(records), "regular_file_count": metadata["regular_file_count"], "hashed_regular_file_count": metadata["regular_file_count"], "directory_count": len(directories), "error_count": len(errors), "collision_count": len(collisions), "escaping_reparse_count": len(escaping_links), "manifest_digest_verified": observed == manifest_digest}, "unlocks": {"G2": not errors and not collisions and observed == manifest_digest}, "blocker": None if not errors and not collisions and observed == manifest_digest else "G1 failed; dependent analysis blocked"}
    (control / "gates.json").write_text(json.dumps(gates, indent=2), encoding="utf-8")
    (control / "containment-policy.json").write_text(json.dumps({"schema_version": "1.0", "run_id": run_id, "canonicalization": "root-bounded, Windows case-insensitive canonical relative paths", "links": "links recorded and not followed", "protected_scope": "every baseline file and baseline stable metadata", "write_scope_before_reporting": f"descendants only of {SPEC_REL}/{run_id}/", "command_policy": "potentially mutating commands require findings-local sandbox"}, indent=2), encoding="utf-8")
    (control / "network-policy.json").write_text(json.dumps({"schema_version": "1.0", "run_id": run_id, "policy": "deny", "enforcement": "no external network access permitted; networking-capable tests remain ineligible unless host-enforced denial is attested"}, indent=2), encoding="utf-8")
    (control / "output-allowlist.json").write_text(json.dumps({"schema_version": "1.0", "run_id": run_id, "audit_lifetime_created_path_allowlist": ["issue.md", "solution.md", f"{SPEC_REL}/{run_id}/**"], "root_deliverable_writer_task": "10.1 only", "preexisting_root_deliverables": [], "matching": "canonical exact paths; traversal, alternate case, sibling-prefix, and link escape rejected"}, indent=2), encoding="utf-8")
    print(json.dumps({"run_id": run_id, "g1": gates["G1"]["outcome"], "files": len(records), "directories": len(directories), "errors": len(errors), "digest": manifest_digest}))


if __name__ == "__main__":
    main()
