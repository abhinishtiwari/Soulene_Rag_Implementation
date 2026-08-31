"""ISSUE-033: the single manifest of every test/diagnostic entry point.

Before this existed, `pytest.ini` discovered `tests/` while four root-level
scripts had their own invocation semantics, and nothing recorded which of them
gated a release. Two concrete consequences:

* `pytest --collect-only .` crashed with `INTERNALERROR ... SystemExit: 0`,
  because collecting root `test_all.py` executes it at import time, and reported
  "no tests collected" - indistinguishable from a clean empty run.
* Root scripts resolved `Settings.root` to the repository, so running the
  pipeline audit wrote the developer's real `data/chat_archive.sqlite3`.

This module is data only - it must not import application modules, because
`conftest.py` imports it before the sandbox is bound. It is consumed by:

* `conftest.py` (repository root) - `collect_ignore` is derived from it, so
  `pytest .` stays safe and cannot drift from the manifest.
* `tests/test_entry_points.py` - asserts the manifest is complete, that gate
  membership matches the CI workflow, and that every lane behaves as declared.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The authoritative command. Anything claiming to be current test evidence must
# come from this.
AUTHORITATIVE_COMMAND = "python -m pytest -q tests --ignore=tests/test_mongo_integration.py"


@dataclass(frozen=True)
class Lane:
    name: str
    entry: str            # path relative to the repository root
    command: str
    kind: str             # suite | diagnostic | operator
    hermetic: bool        # cannot write outside a temporary tree
    in_gate: bool         # part of .github/workflows/gate.yml
    pytest_collect: bool  # may pytest import this path during collection
    note: str


LANES: tuple[Lane, ...] = (
    Lane(
        name="suite",
        entry="tests",
        command=AUTHORITATIVE_COMMAND,
        kind="suite",
        hermetic=True,
        in_gate=True,
        pytest_collect=True,
        note="Authoritative regression evidence. Hermetic via tests/conftest.py.",
    ),
    Lane(
        name="mongo-integration",
        entry="tests/test_mongo_integration.py",
        command="python -m pytest -q tests/test_mongo_integration.py",
        kind="suite",
        hermetic=False,
        in_gate=False,
        pytest_collect=True,
        note="Needs a live Mongo replica set; excluded from the gate "
             "(ISSUE-032 external gate). Skips itself when unreachable.",
    ),
    Lane(
        name="safety-diagnostic",
        entry="test_all.py",
        command="python test_all.py",
        kind="diagnostic",
        hermetic=True,
        in_gate=False,
        pytest_collect=False,
        note="Human-readable safety walkthrough; prints PASS/FAIL and exits "
             "non-zero on failure. Superseded for gating by "
             "tests/test_safety_matrix.py (ISSUE-031). Sandboxed at import.",
    ),
    Lane(
        name="pipeline-diagnostic",
        entry="test_audit.py",
        command="python test_audit.py",
        kind="diagnostic",
        hermetic=True,
        in_gate=False,
        pytest_collect=False,
        note="Human-readable pipeline walkthrough with a mock client. "
             "Sandboxed at import so it cannot write the real archive.",
    ),
    Lane(
        name="live-context-audit",
        entry="context_audit.py",
        command="SOULENE_ALLOW_LIVE_AUDIT=1 python context_audit.py",
        kind="diagnostic",
        hermetic=False,
        in_gate=False,
        pytest_collect=False,
        note="Posts real traffic to a running server and writes "
             "context_audit_results.json. Refuses to run unless "
             "SOULENE_ALLOW_LIVE_AUDIT=1 is set explicitly.",
    ),
    Lane(
        name="smoke-live",
        entry="tests/smoke_live.py",
        command="SOULENE_ALLOW_LIVE_SMOKE=1 python -m tests.smoke_live",
        kind="diagnostic",
        hermetic=False,
        in_gate=False,
        pytest_collect=False,
        note="Real provider calls (costs tokens) and writes the repository's "
             "data/ because it uses Settings.from_env(). Refuses without "
             "SOULENE_ALLOW_LIVE_SMOKE=1. Not collected: filename is not test_*.",
    ),
    Lane(
        name="smoke-staging",
        entry="tests/smoke_staging.py",
        command="SOULENE_ALLOW_LIVE_SMOKE=1 python -m tests.smoke_staging",
        kind="diagnostic",
        hermetic=False,
        in_gate=False,
        pytest_collect=False,
        note="Staging gate against a real provider; same live cost and "
             "non-hermetic write behaviour as smoke-live.",
    ),
    Lane(
        name="cache-build",
        entry="build_cache.py",
        command="python build_cache.py",
        kind="operator",
        hermetic=False,
        in_gate=False,
        pytest_collect=False,
        note="Operator tool. Writing the repository knowledge cache is its "
             "purpose, so it is deliberately NOT sandboxed.",
    ),
)

# Historical result files. They are kept for provenance but must state that they
# are not current evidence, or they get mistaken for a fresh run.
HISTORICAL_REPORTS: tuple[str, ...] = ("Test_Report.md",)
STALENESS_MARKER = "NOT CURRENT TEST EVIDENCE"

# File patterns that look like an entry point. Anything matching these must
# appear in LANES, so a new script fails the suite until it is classified.
ROOT_ENTRY_PATTERNS: tuple[str, ...] = ("test_*.py", "*_audit.py", "build_*.py")
# Inside tests/, `test_*.py` is the collected suite; anything else runnable is a
# separate lane that pytest will never pick up on its own.
TESTS_ENTRY_PATTERNS: tuple[str, ...] = ("smoke_*.py",)


def by_name(name: str) -> Lane:
    for lane in LANES:
        if lane.name == name:
            return lane
    raise KeyError(name)


def root_scripts_excluded_from_collection() -> list[str]:
    """Root-level entries pytest must not import during collection."""
    return [lane.entry for lane in LANES
            if not lane.pytest_collect and "/" not in lane.entry]


def discovered_root_entries() -> list[str]:
    """Entry-point-looking files that must be classified, repo-relative."""
    found: set[str] = set()
    for pattern in ROOT_ENTRY_PATTERNS:
        for path in REPO_ROOT.glob(pattern):
            if path.is_file():
                found.add(path.name)
    for pattern in TESTS_ENTRY_PATTERNS:
        for path in (REPO_ROOT / "tests").glob(pattern):
            if path.is_file():
                found.add(f"tests/{path.name}")
    return sorted(found)


def uncollected_lanes() -> list[Lane]:
    """Lanes pytest must never import by itself."""
    return [lane for lane in LANES if not lane.pytest_collect]
