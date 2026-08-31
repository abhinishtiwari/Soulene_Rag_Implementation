"""Shared hermetic sandbox (ISSUE-029, reused by ISSUE-033).

`app.config.settings.PROJECT_ROOT` is computed at import time and every writable
path is derived from it. Rebinding it to a temporary tree is what keeps a test
run - or a manually invoked diagnostic script - out of the working repository.

This module must not import any application module at top level: callers rely on
being able to bind the sandbox *before* the first `Settings` instance exists.
"""

from __future__ import annotations

import atexit
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Read-only inputs the suite genuinely needs. Copied, never referenced in place,
# so a caller that writes to them cannot touch the repository copy.
COPIED_INPUTS = ("knowledge", "cache")


def create_sandbox(prefix: str = "soulene-tests-") -> Path:
    """Build a temporary project tree and register its cleanup."""
    sandbox = Path(tempfile.mkdtemp(prefix=prefix))
    for name in COPIED_INPUTS:
        source = REPO_ROOT / name
        if source.exists():
            shutil.copytree(source, sandbox / name)
    (sandbox / "data").mkdir(parents=True, exist_ok=True)
    if (REPO_ROOT / ".env").exists():
        shutil.copy2(REPO_ROOT / ".env", sandbox / ".env")
    atexit.register(lambda: shutil.rmtree(sandbox, ignore_errors=True))
    return sandbox


def bind_project_root(sandbox: Path) -> Path:
    """Point settings at `sandbox`. Must run before app modules build Settings."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import app.config.settings as settings_module

    settings_module.PROJECT_ROOT = sandbox
    return sandbox


def activate_sandbox(prefix: str = "soulene-script-") -> Path:
    """Create and bind a sandbox in one call.

    Root-level diagnostic scripts call this as their first statement. Without it
    they resolve `Settings.root` to the repository and write the developer's real
    database and cache (ISSUE-033).
    """
    return bind_project_root(create_sandbox(prefix))
