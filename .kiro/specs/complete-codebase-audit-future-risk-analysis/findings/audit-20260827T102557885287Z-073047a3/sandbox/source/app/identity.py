"""Server-owned, signed pseudonymous identities for the web/API client."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Principal:
    user_id: str
    session_id: str
    token: str
    is_new: bool = False


class InvalidIdentity(ValueError):
    """Raised when a caller presents a malformed or forged identity token."""


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class IdentityManager:
    COOKIE_NAME = "soulene_identity"
    MAX_AGE_SECONDS = 10 * 365 * 24 * 60 * 60

    def __init__(self, secret: str | bytes):
        raw = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
        if len(raw) < 32:
            raise ValueError("identity secret must contain at least 32 bytes")
        self._secret = raw

    @classmethod
    def from_config(cls, configured_secret: str, data_dir: Path,
                    *, require_configured: bool = False) -> "IdentityManager":
        if configured_secret:
            return cls(configured_secret)
        if require_configured:
            raise RuntimeError(
                "IDENTITY_SECRET (at least 32 characters) is required for Mongo/production"
            )
        data_dir.mkdir(parents=True, exist_ok=True)
        path = data_dir / ".identity-secret"
        try:
            secret = path.read_bytes()
        except FileNotFoundError:
            secret = secrets.token_bytes(48)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                secret = path.read_bytes()
            else:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(secret)
                    handle.flush()
                    os.fsync(handle.fileno())
        return cls(secret)

    def issue(self) -> Principal:
        return self._build(f"usr_{uuid.uuid4().hex}", f"sid_{uuid.uuid4().hex}", True)

    def verify(self, token: str) -> Principal:
        try:
            encoded, supplied_signature = token.split(".", 1)
            expected = self._signature(encoded)
            if not hmac.compare_digest(supplied_signature, expected):
                raise InvalidIdentity("invalid identity signature")
            payload = json.loads(_b64decode(encoded))
            user_id = payload["u"]
            session_id = payload["s"]
            if payload.get("v") != 1:
                raise InvalidIdentity("unsupported identity version")
            if not self._valid_id(user_id, "usr_") or not self._valid_id(session_id, "sid_"):
                raise InvalidIdentity("invalid identity fields")
            return Principal(user_id, session_id, token, False)
        except InvalidIdentity:
            raise
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise InvalidIdentity("malformed identity token") from exc

    def _build(self, user_id: str, session_id: str, is_new: bool) -> Principal:
        payload = _b64encode(json.dumps(
            {"v": 1, "u": user_id, "s": session_id},
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8"))
        token = f"{payload}.{self._signature(payload)}"
        return Principal(user_id, session_id, token, is_new)

    def _signature(self, payload: str) -> str:
        return _b64encode(hmac.new(
            self._secret, payload.encode("ascii"), hashlib.sha256
        ).digest())

    @staticmethod
    def _valid_id(value: object, prefix: str) -> bool:
        if not isinstance(value, str) or not value.startswith(prefix):
            return False
        suffix = value[len(prefix):]
        return len(suffix) == 32 and all(c in "0123456789abcdef" for c in suffix)

    def from_request(self, headers, cookies) -> Principal:
        token: Optional[str] = None
        auth = (headers.get("X-Soulene-Identity") or "").strip()
        if auth:
            token = auth
        elif self.COOKIE_NAME in cookies:
            token = (cookies.get(self.COOKIE_NAME) or "").strip()
        return self.verify(token) if token else self.issue()
