"""Request-level API-key authentication and in-process rate limiting.

Local development may explicitly run without API keys. Production deployments
set REQUIRE_API_AUTH=true and fail startup unless separate client and administrator
keys are configured.

Auth model: a shared client key protects the service boundary. Write endpoints
(/documents) always require a separate ADMIN_API_KEY so a normal client cannot
inject knowledge into the CAG cache.

The rate limiter is per-process. Behind multiple Render workers each worker
holds its own window, so treat the effective limit as
    RATE_LIMIT_PER_MINUTE x worker_count.
For strict global limits, move this to Redis (see the guide).
"""

from __future__ import annotations

import hmac
import threading
import time
from collections import deque
from typing import Deque, Dict, Optional, Tuple


def constant_time_equals(a: str, b: str) -> bool:
    """Compare secrets without leaking length/content through timing."""
    return hmac.compare_digest((a or "").encode(), (b or "").encode())


class RateLimiter:
    """Sliding-window limiter keyed by caller identity."""

    def __init__(self, max_per_minute: int = 0):
        self.max_per_minute = max_per_minute
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.max_per_minute > 0

    def check(self, key: str) -> Tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        if not self.enabled:
            return True, 0
        now = time.time()
        window_start = now - 60.0
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and bucket[0] < window_start:
                bucket.popleft()
            if len(bucket) >= self.max_per_minute:
                retry = max(1, int(60 - (now - bucket[0])))
                return False, retry
            bucket.append(now)
            if len(self._hits) > self._CLEANUP_THRESHOLD:
                self._evict(window_start)
            return True, 0

    # Above this many tracked keys, sweep. One-shot identities never return, so
    # waiting for them to be revisited would never reclaim their memory.
    _CLEANUP_THRESHOLD = 10000
    # Hard ceiling so a churn attack cannot grow the table without bound even if
    # every bucket is nominally live.
    _MAX_KEYS = 50000

    def _evict(self, window_start: float) -> None:
        """Drop keys whose most recent hit has aged out of the window.

        Previously only already-empty buckets were removed, and buckets are only
        emptied when their own key is checked again, so a key seen once was
        retained forever.
        """
        for key in [k for k, hits in self._hits.items()
                    if not hits or hits[-1] < window_start]:
            self._hits.pop(key, None)
        if len(self._hits) > self._MAX_KEYS:
            # Oldest-first by most recent activity; dicts preserve insertion
            # order, so sorting by last hit is explicit rather than implied.
            ordered = sorted(self._hits.items(),
                             key=lambda item: item[1][-1] if item[1] else 0.0)
            for key, _ in ordered[:len(self._hits) - self._MAX_KEYS]:
                self._hits.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class ApiAuth:
    """Optional shared-key authentication."""

    def __init__(self, api_key: str = "", admin_api_key: str = ""):
        self.api_key = (api_key or "").strip()
        self.admin_api_key = (admin_api_key or "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @property
    def admin_enabled(self) -> bool:
        return bool(self.admin_api_key)

    @staticmethod
    def extract_key(headers, args=None) -> str:
        """Read credentials from headers only; URLs must never carry secrets."""
        auth = (headers.get("Authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return (headers.get("X-API-Key") or "").strip()

    def check(self, presented: str) -> bool:
        if not self.enabled:
            return True
        # An admin key is also a valid client key.
        if self.admin_enabled and constant_time_equals(presented, self.admin_api_key):
            return True
        return constant_time_equals(presented, self.api_key)

    def check_admin(self, presented: str) -> bool:
        """Require the separate administrator key for write operations."""
        if not self.admin_enabled:
            return False
        return constant_time_equals(presented, self.admin_api_key)
