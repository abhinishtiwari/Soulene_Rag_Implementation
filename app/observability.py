"""Operational counters and budget enforcement.

Deliberately small and in-process: these exist so an operator can alarm on
safety degradation and cap runaway model spend without adding an external
metrics dependency. Counters are content-free.
"""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path
from typing import Dict


class Counters:
    """Named, content-free event counters."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: Dict[str, int] = {}

    def increment(self, name: str, amount: int = 1) -> int:
        with self._lock:
            self._values[name] = self._values.get(name, 0) + amount
            return self._values[name]

    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._values)

    def reset(self) -> None:
        with self._lock:
            self._values.clear()


COUNTERS = Counters()


class DailyCallBudget:
    """Caps provider calls per UTC day. 0 disables the cap."""

    def __init__(self, limit: int = 0):
        self.limit = max(0, int(limit))
        self._lock = threading.Lock()
        self._day = self._today()
        self._used = 0

    @staticmethod
    def _today() -> int:
        return int(time.time() // 86400)

    def consume(self) -> bool:
        """Reserve one call. False means the budget is exhausted."""
        if self.limit <= 0:
            return True
        with self._lock:
            today = self._today()
            if today != self._day:
                self._day, self._used = today, 0
            if self._used >= self.limit:
                return False
            self._used += 1
            return True

    def snapshot(self) -> dict:
        with self._lock:
            return {"limit": self.limit, "used_today": self._used,
                    "exhausted": self.limit > 0 and self._used >= self.limit}


def disk_posture(path: Path, warn_below_mb: int) -> dict:
    """Free-space report for the durable volume."""
    try:
        usage = shutil.disk_usage(str(path))
    except OSError:
        return {"available": False}
    free_mb = usage.free // (1024 * 1024)
    return {
        "available": True,
        "free_mb": free_mb,
        "total_mb": usage.total // (1024 * 1024),
        "warn_below_mb": warn_below_mb,
        "low_space": warn_below_mb > 0 and free_mb < warn_below_mb,
    }
