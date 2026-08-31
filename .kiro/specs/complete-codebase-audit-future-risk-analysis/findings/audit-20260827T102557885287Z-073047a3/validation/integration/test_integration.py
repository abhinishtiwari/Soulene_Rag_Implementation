"""Synthetic miniature audit pipeline and isolation checks; never imports the target application."""
from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def confined(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def safe_write(root: Path, candidate: Path, text: str) -> None:
    if not confined(root, candidate):
        raise PermissionError("write outside synthetic sandbox")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(text, encoding="utf-8")


def safe_read(root: Path, candidate: Path) -> str:
    if candidate.name.casefold() == ".env" or not confined(root, candidate):
        raise PermissionError("secret/outside read denied")
    return candidate.read_text(encoding="utf-8")


def test_synthetic_pipeline_and_isolation() -> None:
    with tempfile.TemporaryDirectory(prefix="mini-audit-", dir=HERE) as raw:
        root = Path(raw)
        protected = root / "protected"
        findings = root / "findings" / "run-synthetic"
        safe_write(root, protected / "app.py", "print('synthetic')\n")
        safe_write(root, protected / "tests" / "test_app.py", "def test_ok(): assert True\n")
        before = {path.relative_to(protected).as_posix(): digest(path) for path in protected.rglob("*") if path.is_file()}

        baseline = sorted(before)
        inventory = [{"path": path, "disposition": "content-reviewed", "owner": "synthetic"} for path in baseline]
        assert len(baseline) == len(inventory) == len({row["path"] for row in inventory})
        trace = {"entrypoints": ["app.py"], "upstream": "synthetic-user", "downstream": "synthetic-output"}
        assert trace["entrypoints"] and trace["upstream"] and trace["downstream"]

        try:
            safe_write(findings, root / "escape.txt", "blocked")
            raise AssertionError("outside write was not blocked")
        except PermissionError:
            pass
        try:
            safe_write(findings, findings / ".." / "sibling" / "escape.txt", "blocked")
            raise AssertionError("traversal was not blocked")
        except PermissionError:
            pass
        safe_write(root, root / ".env", "SYNTHETIC_SECRET=never-read\n")
        try:
            safe_read(root, root / ".env")
            raise AssertionError("secret read was not blocked")
        except PermissionError:
            pass

        original_socket = socket.socket
        socket.socket = lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("network denied"))  # type: ignore[assignment]
        try:
            try:
                socket.socket()
                raise AssertionError("network creation was not blocked")
            except PermissionError:
                pass
        finally:
            socket.socket = original_socket

        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            child.wait(timeout=0.05)
            raise AssertionError("process bound did not trigger")
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=2)
        assert child.returncode is not None

        findings.mkdir(parents=True, exist_ok=True)
        issue = findings / "issue.staged.md"
        solution = findings / "solution.staged.md"
        safe_write(findings, issue, "# Issues\n## Current Defects\n### ISSUE-001\n")
        safe_write(findings, solution, "# Solutions\n### SOLUTION-001 → ISSUE-001\n")
        assert "## Current Defects" in issue.read_text(encoding="utf-8")
        assert "SOLUTION-001 → ISSUE-001" in solution.read_text(encoding="utf-8")

        after = {path.relative_to(protected).as_posix(): digest(path) for path in protected.rglob("*") if path.is_file()}
        assert before == after
        created = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()} - {f"protected/{path}" for path in baseline}
        assert all(path == ".env" or path.startswith("findings/run-synthetic/") for path in created)
