"""Retention and expiry for sensitive records.

Each data class expires on its own clock, because they are not equally sensitive
and are not needed for equally long:

  * raw conversation   - what the user actually wrote; the record of record
  * rolling summary    - machine-derived recap, reconstructible from turns
  * safety state       - inferred health-adjacent state; the most sensitive class
  * derived memory     - inferred facts about the person
  * feedback           - product reports, largely operational

Windows are configuration, not constants, because the correct value is a
product/clinical/legal decision. `retention_enabled=False` keeps current
behaviour (retain indefinitely) so switching this on is an explicit act.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

log = logging.getLogger("soulene.retention")

_SECONDS_PER_DAY = 86400.0


@dataclass(frozen=True)
class RetentionPolicy:
    """Per-class retention windows in days. 0 means never expire."""

    conversation_days: int = 0
    summary_days: int = 0
    safety_state_days: int = 0
    memory_days: int = 0
    feedback_days: int = 0

    @classmethod
    def from_settings(cls, settings) -> "RetentionPolicy":
        if not settings.retention_enabled:
            return cls()
        return cls(
            conversation_days=max(0, settings.retain_conversation_days),
            summary_days=max(0, settings.retain_summary_days),
            safety_state_days=max(0, settings.retain_safety_state_days),
            memory_days=max(0, settings.retain_memory_days),
            feedback_days=max(0, settings.retain_feedback_days),
        )

    @property
    def active(self) -> bool:
        return any((self.conversation_days, self.summary_days,
                    self.safety_state_days, self.memory_days,
                    self.feedback_days))

    def cutoff(self, days: int, now: float) -> Optional[float]:
        """Absolute timestamp before which records of this class expire."""
        return None if days <= 0 else now - days * _SECONDS_PER_DAY


def run_retention(*, archive, profile=None, feedback=None,
                  policy: RetentionPolicy, now: float) -> Dict[str, int]:
    """Apply every configured window once. Returns counts of removed records.

    Each store is purged independently: one backend failing must not stop the
    others, because partial expiry is strictly better than none.
    """
    counts: Dict[str, int] = {}
    if not policy.active:
        return counts

    for label, target, method in (
        ("archive", archive, "purge_expired"),
        ("memory", profile, "purge_expired"),
        ("feedback", feedback, "purge_expired"),
    ):
        if target is None:
            continue
        purge = getattr(target, method, None)
        if not callable(purge):
            continue
        try:
            result: Any = (purge(policy=policy, now=now) if label == "archive"
                           else purge(cutoff=policy.cutoff(
                               policy.memory_days if label == "memory"
                               else policy.feedback_days, now)))
        except Exception as exc:
            # Redacted: never log record contents.
            log.error("retention sweep failed for %s: %s", label, type(exc).__name__)
            continue
        if isinstance(result, dict):
            counts.update(result)
        elif isinstance(result, int):
            counts[label] = result
    if counts:
        log.info("retention sweep removed %s", counts)
    return counts
