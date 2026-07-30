"""Request-level security: optional API-key auth and in-process rate limiting.

Both are OFF by default so local development is frictionless. Enable in
production by setting API_KEY (and optionally RATE_LIMIT_PER_MINUTE).

Auth model: a shared API key protects the service boundary. Write endpoints
(/documents) can additionally require an ADMIN_API_KEY so a normal client
cannot inject knowledge into the CAG cache.

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
            # Opportunistic cleanup so idle keys don't accumulate forever.
            if len(self._hits) > 10000:
                for k in [k for k, v in self._hits.items() if not v]:
                    self._hits.pop(k, None)
            return True, 0

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
    def extract_key(headers, args) -> str:
        """Read the key from Authorization: Bearer, X-API-Key, or ?api_key=."""
        auth = (headers.get("Authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return (headers.get("X-API-Key") or args.get("api_key") or "").strip()

    def check(self, presented: str) -> bool:
        if not self.enabled:
            return True
        # An admin key is also a valid client key.
        if self.admin_enabled and constant_time_equals(presented, self.admin_api_key):
            return True
        return constant_time_equals(presented, self.api_key)

    def check_admin(self, presented: str) -> bool:
        """Guard write operations (document upload/delete)."""
        if not self.admin_enabled:
            # No separate admin key configured -> fall back to normal auth.
            return self.check(presented)
        return constant_time_equals(presented, self.admin_api_key)
