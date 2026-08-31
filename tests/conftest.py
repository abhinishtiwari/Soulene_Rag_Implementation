"""Mandatory hermetic sandbox for the test suite.

Settings resolve every writable path from `app.config.settings.PROJECT_ROOT`,
which is computed at import time. Redirecting it here — before pytest imports any
test module — is what makes the suite hermetic: databases, caches, identity
secrets and uploaded documents all land in a temporary tree instead of the
working repository.

Without this, running the suite mutated the real `data/chat_archive.sqlite3`,
which both corrupted developer data and made order-dependent tests (timing,
cross-session digests) depend on state left by earlier runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# The sandbox mechanics live in tests/sandbox.py so root-level diagnostic
# scripts bind the same way instead of writing to the repository (ISSUE-033).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.sandbox import REPO_ROOT, create_sandbox, bind_project_root  # noqa: E402

# Must happen before any application module is imported by a test.
SANDBOX = bind_project_root(create_sandbox("soulene-tests-"))


@pytest.fixture(autouse=True)
def _assert_paths_stay_in_sandbox():
    """Fail any test whose settings escape the sandbox."""
    from app.config.settings import Settings

    root = Settings.from_env().root
    assert root == SANDBOX, f"settings escaped the sandbox: {root}"
    yield
