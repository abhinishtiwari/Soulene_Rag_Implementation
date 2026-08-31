"""Repository-root pytest configuration (ISSUE-033).

`pytest .` used to abort with `INTERNALERROR ... SystemExit: 0`: collecting the
root-level `test_all.py` executes it at import time and it calls `sys.exit()`.
The run then reported "no tests collected", which is indistinguishable from a
clean empty run.

The ignore list is derived from `tests/lanes.py`, so the manifest and pytest
cannot drift apart. Deliberately imports no application module.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tests.lanes import root_scripts_excluded_from_collection  # noqa: E402

collect_ignore = root_scripts_excluded_from_collection()
