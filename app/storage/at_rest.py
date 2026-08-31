"""At-rest protection posture for stored sensitive data.

Deliberately NOT an encryption engine. Application-level field encryption was
rejected for this schema because the archive projects message content in SQL
(`substr(content, ...)` for session titles and previews) and memory retrieval
tokenises stored text, so encrypting those fields would break existing features
while still leaving keys in the same process as the data.

What this module does provide is everything the application can actually
enforce and verify by itself:

  * an explicit classification of which stored fields hold sensitive data
  * local filesystem hardening of database files it creates
  * a reported posture separating locally-verified facts from operator claims

Volume, database and backup encryption are platform properties. The application
cannot observe them, so it requires an explicit operator attestation instead of
implying a guarantee it cannot check.
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path
from typing import Dict, List

log = logging.getLogger("soulene.storage")

# Data classification. `sensitive` fields carry user-authored or inferred
# personal/health-adjacent content; `identifier` fields are pseudonymous keys;
# `operational` fields are timing/bookkeeping values.
SENSITIVE_FIELDS: Dict[str, Dict[str, List[str]]] = {
    "chat_messages": {
        "sensitive": ["content"],
        "identifier": ["message_id", "user_id", "conversation_id"],
        "operational": ["role", "created_at", "sequence_number"],
    },
    "chat_sessions": {
        # metadata_json carries the derived summary; safety_state carries
        # inferred health-adjacent state.
        "sensitive": ["metadata_json", "safety_state"],
        "identifier": ["session_id", "user_id"],
        "operational": ["created_at", "updated_at", "next_sequence"],
    },
    "chat_requests": {
        "sensitive": ["user_content", "assistant_content", "state_json"],
        "identifier": ["user_id", "conversation_id", "request_id",
                       "user_message_id", "assistant_message_id"],
        "operational": ["route", "created_at", "memory_status",
                        "summary_status", "secondary_attempts",
                        "secondary_error"],
    },
    "long_term_memories": {
        "sensitive": ["text"],
        "identifier": ["user_id", "memory_id"],
        "operational": ["kind", "created_at", "updated_at", "weight", "ordinal",
                        "sources_json", "extraction_version", "confidence",
                        "quarantined_at"],
    },
    "feedback": {
        "sensitive": ["message"],
        "identifier": ["feedback_id", "user_id"],
        "operational": ["category", "created_at", "status"],
    },
    "deletion_jobs": {
        "sensitive": [],
        "identifier": ["user_id"],
        "operational": ["requested_at", "steps_json", "completed_at"],
    },
    "deleted_users": {
        "sensitive": [],
        "identifier": ["user_id"],
        "operational": ["deleted_at"],
    },
    "maintenance_runs": {
        "sensitive": [],
        "identifier": ["name"],
        "operational": ["last_run_at"],
    },
}


def classified_columns(table: str) -> List[str]:
    """Every column this module claims to have classified for a table."""
    entry = SENSITIVE_FIELDS.get(table, {})
    return [column for group in entry.values() for column in group]


def harden_file_permissions(path: Path) -> bool:
    """Restrict a database file to the owner. Returns True when applied.

    POSIX only in practice: on Windows `chmod` cannot express owner-only ACLs,
    so this reports False rather than pretending the file was hardened.
    """
    target = Path(path)
    if not target.exists() or os.name != "posix":
        return False
    try:
        os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
        return True
    except OSError as exc:
        log.warning("could not restrict permissions on a data file: %s",
                    type(exc).__name__)
        return False


def storage_posture(settings, paths: List[Path]) -> dict:
    """Report at-rest posture, separating verified facts from operator claims."""
    files = []
    for path in paths:
        candidate = Path(path)
        entry = {"exists": candidate.exists(), "owner_only": False}
        if candidate.exists() and os.name == "posix":
            mode = stat.S_IMODE(candidate.stat().st_mode)
            entry["owner_only"] = mode == 0o600
        files.append(entry)
    return {
        # Verified by this process.
        "sensitive_tables": sorted(
            table for table, groups in SENSITIVE_FIELDS.items()
            if groups.get("sensitive")
        ),
        "owner_only_files": sum(1 for f in files if f["owner_only"]),
        "data_files_present": sum(1 for f in files if f["exists"]),
        "permission_hardening_supported": os.name == "posix",
        # Claimed by the operator; the application cannot verify these.
        "encryption_required": bool(settings.require_encrypted_storage),
        "encryption_attested": bool(settings.storage_encryption_attested.strip()),
        "application_level_field_encryption": False,
    }
