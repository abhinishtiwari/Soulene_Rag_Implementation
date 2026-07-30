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
    # Optional SECOND LLM reviewer on outgoing replies. Off by default: the
    # deterministic validator (prompt-leak scrub + hard safety block) always
    # runs, so this would be a duplicate reviewer costing an extra LLM call.
    enable_output_safety_check: bool = False

    # --- CAG (cache-augmented generation) ---
    knowledge_token_budget: int = 12000   # full-corpus preload when under this
    context_cache_size: int = 100         # messages held per conversation
    prompt_window: int = 20               # messages actually sent to the model
    response_cache_entries: int = 500
    max_upload_mb: int = 10
    # Repeated unsafe attempts in one session before tone hardens.
    strict_unsafe_threshold: int = 3

    # --- Request security (both disabled unless configured) ---
    api_key: str = ""              # shared client key; empty = auth disabled
    admin_api_key: str = ""        # guards document upload/delete
    rate_limit_per_minute: int = 0  # 0 = unlimited

    # --- Legacy RAG preprocessing knobs (document prep only) ---
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    chunk_size: int = 800
    chunk_overlap: int = 120

    # --- Memory ---
    max_recent_turns: int = 12

    # --- Emergency ---
    emergency_number: str = "112"

    # --- Paths (relative to PROJECT_ROOT) ---
    knowledge_dir: str = "knowledge"
    vector_store_dir: str = "vector_store"

    @property
    def root(self) -> Path:
        return PROJECT_ROOT

    @property
    def knowledge_path(self) -> Path:
        return PROJECT_ROOT / self.knowledge_dir

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
            rate_limit_per_minute=_get_int(env, "RATE_LIMIT_PER_MINUTE", cls.rate_limit_per_minute),
            max_recent_turns=_get_int(env, "MAX_RECENT_TURNS", cls.max_recent_turns),
            emergency_number=_get(env, "EMERGENCY_NUMBER", cls.emergency_number),
        )

    def require_api_key(self) -> None:
        if not self.openai_api_key:
            raise RuntimeError(
                "Missing OPENAI_API_KEY. Add it to rag_implementation/.env or the environment."
            )
