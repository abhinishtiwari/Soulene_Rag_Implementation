"""Application settings loaded from environment / .env file.

Keeps a tiny, dependency-free .env reader so the app runs without python-dotenv.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


# Project root = rag_implementation/  (this file is app/config/settings.py)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_env_file(env_file: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file. Missing file returns empty dict."""
    values: dict[str, str] = {}
    if not env_file.exists():
        return values
    try:
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            key, val = line.split("=", 1)
            values[key.strip()] = val.strip().strip("\"'")
    except OSError:
        pass
    return values


def _get(env: dict[str, str], key: str, default: str = "") -> str:
    return os.getenv(key, "").strip() or env.get(key, "").strip() or default


def _get_bool(env: dict[str, str], key: str, default: bool) -> bool:
    raw = _get(env, key, "")
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _get_int(env: dict[str, str], key: str, default: int) -> int:
    raw = _get(env, key, "")
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _get_float(env: dict[str, str], key: str, default: float) -> float:
    raw = _get(env, key, "")
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    """Runtime configuration."""

    # --- LLM ---
    openai_api_key: str = ""
    primary_model: str = "gpt-4.1-mini"
    moderation_model: str = "omni-moderation-latest"
    request_timeout_seconds: float = 20.0
    max_retries: int = 2
    temperature: float = 0.8
    max_output_tokens: int = 500

    # --- Safety toggles ---
    enable_input_moderation: bool = True
    # A separate, structured conversation-level semantic assessment runs before
    # response generation. Deterministic guardrails remain the authoritative floor.
    enable_semantic_safety: bool = True
    semantic_safety_max_chars: int = 40000
    # Optional second-pass editor for outgoing replies. Enabled by default as
    # defense in depth; the deterministic therapeutic-harm wall still runs when
    # the editor is disabled or unavailable.
    enable_output_safety_check: bool = True

    # --- CAG (cache-augmented generation) ---
    knowledge_token_budget: int = 12000   # full-corpus preload when under this
    context_cache_size: int = 100         # messages held per conversation
    prompt_window: int = 20               # messages actually sent to the model
    response_cache_entries: int = 500
    max_upload_mb: int = 10
    # Repeated unsafe attempts in one session before tone hardens.
    strict_unsafe_threshold: int = 3

    # --- Request security ---
    # Identity issuance is limited per coarse network signal so discarding a
    # cookie cannot mint a fresh quota. Expressed as a multiple of the
    # per-identity limit to leave headroom for shared NAT egress.
    # PROPOSED VALUE - awaiting sign-off.
    anon_rate_limit_multiplier: int = 5
    api_key: str = ""              # optional only when production auth is not required
    admin_api_key: str = ""        # separate key for document writes
    require_api_auth: bool = False  # production startup fails when credentials are absent
    rate_limit_per_minute: int = 0  # 0 = unlimited
    identity_secret: str = ""      # required for shared/production deployments
    # Token lifetime with sliding renewal, and a revocation epoch: bumping the
    # epoch invalidates every outstanding token. PROPOSED VALUES - need sign-off.
    identity_ttl_days: int = 180
    identity_epoch: int = 1
    secure_identity_cookie: bool = False

    # --- Legacy RAG preprocessing knobs (document prep only) ---
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    chunk_size: int = 800
    chunk_overlap: int = 120

    # --- Memory ---
    max_recent_turns: int = 12

    # --- Operational limits ---
    # Hard cap on provider calls per UTC day; 0 disables. Exceeding it degrades
    # to deterministic replies instead of spending without bound.
    # PROPOSED VALUE - awaiting sign-off.
    model_daily_call_budget: int = 0
    disk_warn_below_mb: int = 256

    # --- Probe behaviour (ISSUE-038) ---
    # Readiness reports "initializing" rather than "unavailable" until a cold
    # process has had this long to finish explicit initialization. It must
    # exceed real cold-start time (knowledge cache load + backend connect) or a
    # platform will kill healthy-but-slow starts.
    # PROPOSED VALUES - awaiting sign-off. Both defaults are deliberately
    # generous so nothing is declared dead prematurely.
    readiness_startup_grace_seconds: int = 120
    # Hard deadline for the readiness dependency probe. A hung backend must not
    # hang the probe response.
    readiness_probe_timeout_seconds: int = 5

    # --- External model provider privacy ---
    require_provider_disclosure: bool = False
    provider_disclosure_attested: str = ""
    # Active minimization control: excludes prior-session background from
    # provider calls. Defaults to current behaviour so continuity is preserved.
    send_cross_session_context: bool = True

    # --- At-rest protection ---
    # The application cannot verify volume/database encryption, so production
    # requires an explicit operator attestation instead of assuming it.
    require_encrypted_storage: bool = False
    storage_encryption_attested: str = ""

    # --- Retention (days; 0 disables expiry for that data class) ---
    #
    # These defaults are PROPOSED and require product/clinical/legal sign-off.
    # They are deliberately configurable because the right window is a policy
    # decision, not a code decision. Each class expires independently so derived
    # inferences can be dropped sooner than the words the user actually wrote.
    retention_enabled: bool = False
    retain_conversation_days: int = 365
    retain_summary_days: int = 90
    retain_safety_state_days: int = 30
    retain_memory_days: int = 180
    retain_feedback_days: int = 730
    # Minimum gap between opportunistic retention sweeps.
    retention_interval_hours: int = 24

    # --- Emergency ---
    # A number is only named to a user when the operator has also declared the
    # locale it was human-verified for; otherwise wording stays neutral.
    emergency_number: str = "112"
    emergency_locale: str = ""

    # --- Durable storage (exactly one authoritative backend) ---
    storage_backend: str = "sqlite"  # sqlite (local/single-host) | mongo
    mongo_uri: str = ""
    db_name: str = "soulene_db"

    # --- Paths (relative to PROJECT_ROOT) ---
    knowledge_dir: str = "knowledge"
    cache_dir: str = "cache"
    vector_store_dir: str = "vector_store"
    # When set, declares the durable mount. Startup then requires that every
    # writable path lives inside it, so nothing important is left on ephemeral
    # container storage.
    persistent_root: str = ""

    @property
    def root(self) -> Path:
        return PROJECT_ROOT

    @property
    def emergency_contact_is_verified(self) -> bool:
        """True only when a number AND its verified locale are both declared."""
        return bool(self.emergency_number.strip() and self.emergency_locale.strip())

    @property
    def knowledge_path(self) -> Path:
        return PROJECT_ROOT / self.knowledge_dir

    @property
    def cache_path(self) -> Path:
        return PROJECT_ROOT / self.cache_dir

    @property
    def data_path(self) -> Path:
        return PROJECT_ROOT / "data"

    def validate_persistence(self) -> None:
        """Fail startup when a declared mount does not contain writable paths.

        The deployment previously mounted only `data/` while knowledge and cache
        lived beside it, so uploaded documents and the built cache silently
        vanished on redeploy.
        """
        declared = self.persistent_root.strip()
        if not declared:
            return
        root = Path(declared).resolve()
        for label, path in (("knowledge", self.knowledge_path),
                           ("cache", self.cache_path),
                           ("data", self.data_path)):
            try:
                path.resolve().relative_to(root)
            except ValueError:
                raise RuntimeError(
                    f"{label} path {path} is outside the declared persistent "
                    f"root {root}; it would be lost on redeploy"
                ) from None

    @property
    def vector_store_path(self) -> Path:
        return PROJECT_ROOT / self.vector_store_dir

    @classmethod
    def from_env(cls) -> "Settings":
        env = _read_env_file(PROJECT_ROOT / ".env")
        return cls(
            openai_api_key=_get(env, "OPENAI_API_KEY"),
            primary_model=_get(env, "OPENAI_MODEL", cls.primary_model),
            moderation_model=_get(env, "OPENAI_MODERATION_MODEL", cls.moderation_model),
            enable_input_moderation=_get_bool(env, "ENABLE_INPUT_MODERATION", cls.enable_input_moderation),
            enable_semantic_safety=_get_bool(env, "ENABLE_SEMANTIC_SAFETY", cls.enable_semantic_safety),
            semantic_safety_max_chars=_get_int(env, "SEMANTIC_SAFETY_MAX_CHARS", cls.semantic_safety_max_chars),
            enable_output_safety_check=_get_bool(env, "ENABLE_OUTPUT_SAFETY_CHECK", cls.enable_output_safety_check),
            embedding_model=_get(env, "EMBEDDING_MODEL", cls.embedding_model),
            chunk_size=_get_int(env, "CHUNK_SIZE", cls.chunk_size),
            chunk_overlap=_get_int(env, "CHUNK_OVERLAP", cls.chunk_overlap),
            knowledge_token_budget=_get_int(env, "KNOWLEDGE_TOKEN_BUDGET", cls.knowledge_token_budget),
            context_cache_size=_get_int(env, "CONTEXT_CACHE_SIZE", cls.context_cache_size),
            prompt_window=_get_int(env, "PROMPT_WINDOW", cls.prompt_window),
            response_cache_entries=_get_int(env, "RESPONSE_CACHE_ENTRIES", cls.response_cache_entries),
            max_upload_mb=_get_int(env, "MAX_UPLOAD_MB", cls.max_upload_mb),
            strict_unsafe_threshold=_get_int(env, "STRICT_UNSAFE_THRESHOLD", cls.strict_unsafe_threshold),
            api_key=_get(env, "API_KEY"),
            admin_api_key=_get(env, "ADMIN_API_KEY"),
            require_api_auth=_get_bool(env, "REQUIRE_API_AUTH", cls.require_api_auth),
            anon_rate_limit_multiplier=_get_int(
                env, "ANON_RATE_LIMIT_MULTIPLIER", cls.anon_rate_limit_multiplier),
            rate_limit_per_minute=_get_int(env, "RATE_LIMIT_PER_MINUTE", cls.rate_limit_per_minute),
            identity_secret=_get(env, "IDENTITY_SECRET"),
            identity_ttl_days=_get_int(env, "IDENTITY_TTL_DAYS", cls.identity_ttl_days),
            identity_epoch=_get_int(env, "IDENTITY_EPOCH", cls.identity_epoch),
            secure_identity_cookie=_get_bool(env, "SECURE_IDENTITY_COOKIE", cls.secure_identity_cookie),
            max_recent_turns=_get_int(env, "MAX_RECENT_TURNS", cls.max_recent_turns),
            model_daily_call_budget=_get_int(
                env, "MODEL_DAILY_CALL_BUDGET", cls.model_daily_call_budget),
            disk_warn_below_mb=_get_int(
                env, "DISK_WARN_BELOW_MB", cls.disk_warn_below_mb),
            readiness_startup_grace_seconds=_get_int(
                env, "READINESS_STARTUP_GRACE_SECONDS",
                cls.readiness_startup_grace_seconds),
            readiness_probe_timeout_seconds=_get_int(
                env, "READINESS_PROBE_TIMEOUT_SECONDS",
                cls.readiness_probe_timeout_seconds),
            require_provider_disclosure=_get_bool(
                env, "REQUIRE_PROVIDER_DISCLOSURE", cls.require_provider_disclosure),
            provider_disclosure_attested=_get(
                env, "PROVIDER_DISCLOSURE_ATTESTED", cls.provider_disclosure_attested),
            send_cross_session_context=_get_bool(
                env, "SEND_CROSS_SESSION_CONTEXT", cls.send_cross_session_context),
            require_encrypted_storage=_get_bool(
                env, "REQUIRE_ENCRYPTED_STORAGE", cls.require_encrypted_storage),
            storage_encryption_attested=_get(
                env, "STORAGE_ENCRYPTION_ATTESTED", cls.storage_encryption_attested),
            retention_enabled=_get_bool(env, "RETENTION_ENABLED", cls.retention_enabled),
            retain_conversation_days=_get_int(
                env, "RETAIN_CONVERSATION_DAYS", cls.retain_conversation_days),
            retain_summary_days=_get_int(
                env, "RETAIN_SUMMARY_DAYS", cls.retain_summary_days),
            retain_safety_state_days=_get_int(
                env, "RETAIN_SAFETY_STATE_DAYS", cls.retain_safety_state_days),
            retain_memory_days=_get_int(
                env, "RETAIN_MEMORY_DAYS", cls.retain_memory_days),
            retain_feedback_days=_get_int(
                env, "RETAIN_FEEDBACK_DAYS", cls.retain_feedback_days),
            retention_interval_hours=_get_int(
                env, "RETENTION_INTERVAL_HOURS", cls.retention_interval_hours),
            emergency_number=_get(env, "EMERGENCY_NUMBER", cls.emergency_number),
            emergency_locale=_get(env, "EMERGENCY_LOCALE", cls.emergency_locale),
            knowledge_dir=_get(env, "KNOWLEDGE_DIR", cls.knowledge_dir),
            cache_dir=_get(env, "CACHE_DIR", cls.cache_dir),
            persistent_root=_get(env, "PERSISTENT_ROOT", cls.persistent_root),
            storage_backend=_get(env, "STORAGE_BACKEND", cls.storage_backend).lower(),
            mongo_uri=_get(env, "MONGO_URI"),
            db_name=_get(env, "DB_NAME", cls.db_name),
        )

    def validate_storage(self) -> None:
        if self.storage_backend not in {"sqlite", "mongo"}:
            raise RuntimeError("STORAGE_BACKEND must be 'sqlite' or 'mongo'")
        if self.storage_backend == "mongo" and not self.mongo_uri:
            raise RuntimeError("MONGO_URI is required when STORAGE_BACKEND=mongo")
        if self.storage_backend == "mongo" and len(self.identity_secret.encode("utf-8")) < 32:
            raise RuntimeError(
                "IDENTITY_SECRET must contain at least 32 bytes when STORAGE_BACKEND=mongo"
            )

    def validate_security(self) -> None:
        """Fail startup when a deployment declares authenticated operation."""
        if not self.require_api_auth:
            return
        if not self.api_key:
            raise RuntimeError("API_KEY is required when REQUIRE_API_AUTH=true")
        if not self.admin_api_key:
            raise RuntimeError("ADMIN_API_KEY is required when REQUIRE_API_AUTH=true")
        if self.api_key == self.admin_api_key:
            raise RuntimeError("API_KEY and ADMIN_API_KEY must be different")

    def validate_provider_disclosure(self) -> None:
        """Fail startup when a privacy notice is required but not recorded.

        Sensitive context crosses an external model boundary, so production must
        record that users are told, and by whom it was confirmed.
        """
        if not self.require_provider_disclosure:
            return
        if not self.provider_disclosure_attested.strip():
            raise RuntimeError(
                "PROVIDER_DISCLOSURE_ATTESTED is required when "
                "REQUIRE_PROVIDER_DISCLOSURE=true"
            )

    def validate_storage_protection(self) -> None:
        """Fail startup when encryption is required but not attested.

        The attestation is an operator claim, not a verification: it records who
        confirmed that volume/database/backup encryption is in place so the gap
        is explicit rather than silently assumed.
        """
        if not self.require_encrypted_storage:
            return
        if not self.storage_encryption_attested.strip():
            raise RuntimeError(
                "STORAGE_ENCRYPTION_ATTESTED is required when "
                "REQUIRE_ENCRYPTED_STORAGE=true"
            )

    def require_api_key(self) -> None:
        if not self.openai_api_key:
            raise RuntimeError(
                "Missing OPENAI_API_KEY. Add it to rag_implementation/.env or the environment."
            )
