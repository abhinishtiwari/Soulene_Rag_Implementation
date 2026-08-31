"""Content-free accounting of what crosses the model-provider boundary.

Records only the purpose of each call and coarse sizes. Never records prompt or
reply text, so the audit trail cannot itself become a copy of the data it
describes. Used to make external transmission observable on /metrics.
"""

from __future__ import annotations

import threading
from typing import Dict


class TransmissionLedger:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._calls: Dict[str, int] = {}
        self._characters: Dict[str, int] = {}

    def record(self, purpose: str, characters: int) -> None:
        with self._lock:
            self._calls[purpose] = self._calls.get(purpose, 0) + 1
            self._characters[purpose] = (
                self._characters.get(purpose, 0) + max(0, int(characters)))

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "calls_by_purpose": dict(self._calls),
                "characters_by_purpose": dict(self._characters),
                "total_calls": sum(self._calls.values()),
            }

    def reset(self) -> None:
        with self._lock:
            self._calls.clear()
            self._characters.clear()


# One shared ledger: the provider boundary is process-wide.
LEDGER = TransmissionLedger()
