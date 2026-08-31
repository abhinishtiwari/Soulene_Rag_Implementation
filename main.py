"""Soulene AI - CAG mental-health companion. Flask entry point.

Run:
    python main.py            # web UI + API   (http://localhost:5000)
    python main.py --cli      # terminal chat

Endpoints:
    GET  /                 chat UI
    GET  /live             liveness (process only; no service, no backend)
    GET  /health           readiness (platform health check; never initializes)
    GET  /metrics          cache / performance stats
    POST /chat             JSON reply
    POST /chat/stream      SSE token stream
    POST /documents        upload a knowledge document (multipart)
    GET  /documents        list cached documents
    DELETE /documents/<n>  remove a document from the knowledge cache
    POST /feedback         submit feedback (isolated store)
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import secrets
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from flask import Flask, Response, g, jsonify, render_template, request, stream_with_context

from app.cag.document_processor import SUPPORTED_EXTENSIONS
from app.chatbot import build_chatbot
from app.config.settings import Settings
from app.identity import IdentityManager, InvalidIdentity, Principal
from app.security import ApiAuth, RateLimiter
from app.storage.feedback_store import FeedbackStore
from app.llm.transmission import LEDGER
from app.observability import COUNTERS, disk_posture
from app.storage.at_rest import storage_posture
from app.storage.retention import RetentionPolicy, run_retention
from app.utils import MAX_MESSAGE_CHARS, exceeds_message_limit, oversized_message_reply

BASE_DIR = Path(__file__).resolve().parent

# --- production logging (no secrets, no message bodies) ---
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("soulene")
for noisy in ("openai", "httpx", "httpcore", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

app = Flask(__name__, template_folder=str(BASE_DIR / "ui"))
_settings = Settings.from_env()
_settings.validate_security()
_settings.validate_storage_protection()
_settings.validate_provider_disclosure()
_settings.validate_persistence()
app.config["MAX_CONTENT_LENGTH"] = _settings.max_upload_mb * 1024 * 1024

_service = None
_feedback = None
_identity = IdentityManager.from_config(
    _settings.identity_secret,
    _settings.root / "data",
    require_configured=_settings.storage_backend == "mongo",
    ttl_days=_settings.identity_ttl_days,
    epoch=_settings.identity_epoch,
)


_PROCESS_STARTED_AT = time.time()
# ISSUE-038: initialization is an explicit startup action, never a side effect
# of a platform probe. Readiness only *reports* what this state records.
_INIT_STATE = {"attempts": 0, "failures": 0, "last_failure_at": 0.0}


def get_service():
    global _service
    if _service is None:
        t0 = time.time()
        _INIT_STATE["attempts"] += 1
        try:
            _settings.require_api_key()
            _settings.validate_storage()
            service = build_chatbot(_settings)
            # Refuse a database written by a newer release, and repair rows
            # orphaned by an earlier partial failure before serving traffic.
            checker = getattr(service.archive, "assert_schema_supported", None)
            if callable(checker):
                checker()
            reconciler = getattr(service.archive, "reconcile_orphans", None)
            if callable(reconciler):
                report = reconciler()
                if any(report.values()):
                    log.warning("startup reconciliation: %s", report)
            stats = service.cag.stats()["knowledge_cache"]
        except Exception:
            # Recorded so readiness can answer "unavailable" straight away
            # instead of waiting out the startup grace on a known failure.
            _INIT_STATE["failures"] += 1
            _INIT_STATE["last_failure_at"] = time.time()
            raise
        # Published only once the instance is fully checked, so no probe or
        # request can observe a half-initialized service.
        _service = service
        log.info("chatbot ready in %.2fs | docs=%s sections=%s tokens=%s full_preload=%s",
                 time.time() - t0, stats["documents"], stats["sections"],
                 stats["approx_tokens"], stats["full_preload"])
    return _service


def initialize_service() -> bool:
    """Explicitly initialize the service. Used by startup paths only.

    Returns success instead of raising so a failed cold start leaves the process
    alive and answering liveness, while readiness stays fail-closed at 503.
    """
    try:
        get_service()
        return True
    except Exception as exc:
        log.error("service initialization failed: %s", type(exc).__name__)
        return False


def _bounded_probe(check, budget: float) -> tuple:
    """Run one dependency check under a hard deadline.

    Returns (state, elapsed_seconds, error_type) where state is
    ``ok`` | ``failed`` | ``timeout``. The check runs on a daemon thread so a
    wedged backend socket cannot hold the probe response open.
    """
    outcome: dict = {}

    def _run() -> None:
        try:
            check()
            outcome["state"] = "ok"
        except Exception as exc:  # noqa: BLE001 - state is reported, not raised
            outcome["state"] = "failed"
            outcome["error"] = type(exc).__name__

    t0 = time.time()
    worker = threading.Thread(target=_run, daemon=True, name="readiness-probe")
    worker.start()
    worker.join(max(0.1, float(budget)))
    elapsed = time.time() - t0
    if worker.is_alive():
        return "timeout", elapsed, ""
    return outcome.get("state", "failed"), elapsed, outcome.get("error", "")


def readiness_report() -> tuple:
    """Bounded readiness snapshot. Never constructs anything (ISSUE-038).

    Dependency states are coarse (``ok``/``failed``/``timeout``/``pending``):
    the route is unauthenticated, so exception detail is logged rather than
    returned.
    """
    uptime = round(time.time() - _PROCESS_STARTED_AT, 3)
    grace = max(0, int(_settings.readiness_startup_grace_seconds))
    body = {
        "service": "soulene-cag",
        "storage": _settings.storage_backend,
        "uptime_seconds": uptime,
        "startup_grace_seconds": grace,
    }
    service = _service  # read only; a probe must not trigger construction
    if service is None:
        body["dependencies"] = {"service": "pending", "storage": "unknown"}
        if _INIT_STATE["failures"]:
            body.update(status="unavailable", reason="initialization_failed")
        elif uptime <= grace:
            body.update(status="initializing", reason="awaiting_initialization")
        else:
            body.update(status="unavailable", reason="startup_deadline_exceeded")
        return body, 503

    state, elapsed, error_type = _bounded_probe(
        service.archive.healthcheck, _settings.readiness_probe_timeout_seconds)
    body["dependencies"] = {
        "service": "ok",
        "storage": state,
        "storage_probe_ms": round(elapsed * 1000, 1),
    }
    if state != "ok":
        log.error("readiness storage probe %s after %.2fs%s", state, elapsed,
                  f" ({error_type})" if error_type else "")
        body.update(status="unavailable", reason=f"storage_{state}")
        return body, 503
    body.update(status="ok", reason="")
    return body, 200


def get_feedback():
    global _feedback
    if _feedback is None:
        if _settings.storage_backend == "mongo":
            from app.storage.feedback_store_mongo import FeedbackStoreMongo
            from app.storage.mongo_client import get_mongo_db
            _feedback = FeedbackStoreMongo(
                get_mongo_db(_settings.mongo_uri, _settings.db_name))
        else:
            _feedback = FeedbackStore(_settings.root / "data" / "feedback.sqlite3")
    return _feedback


_retention_policy = RetentionPolicy.from_settings(_settings)
_retention_checked_at = 0.0


def run_retention_sweep(force: bool = False) -> dict:
    """Expire records per retention policy. Safe to call from any worker.

    A cheap in-process timer avoids hitting the database on every request; the
    authoritative claim is transactional, so exactly one worker sweeps per
    interval even though each worker calls this independently.
    """
    global _retention_checked_at
    if not _retention_policy.active:
        return {}
    interval = max(1, _settings.retention_interval_hours) * 3600
    now = time.time()
    if not force and (now - _retention_checked_at) < interval:
        return {}
    _retention_checked_at = now
    service = get_service()
    claim = getattr(service.archive, "claim_retention_run", None)
    if not force and callable(claim) and not claim(interval, now):
        return {}
    return run_retention(
        archive=service.archive, profile=service.profile,
        feedback=get_feedback(), policy=_retention_policy, now=now,
    )


def shutdown_resources() -> dict:
    """Close shared connections once, idempotently.

    Gunicorn terminates workers on deploy, reload and scale-down. Without an
    explicit hook the SQLite feedback connection and the shared MongoClient were
    left to process teardown, which complicated graceful shutdown and left
    connections lingering during rolling deploys.
    """
    global _feedback
    closed = {"feedback": False, "mongo": False}
    if _feedback is not None:
        try:
            _feedback.close()
            closed["feedback"] = True
        except Exception as exc:
            log.error("feedback close failed: %s", type(exc).__name__)
        finally:
            _feedback = None
    try:
        from app.storage.mongo_client import reset_mongo
        reset_mongo()
        closed["mongo"] = True
    except Exception as exc:
        log.error("mongo close failed: %s", type(exc).__name__)
    return closed


# Covers normal interpreter exit and Gunicorn worker termination.
atexit.register(shutdown_resources)


def _principal() -> Principal:
    principal = getattr(g, "principal", None)
    if principal is None:
        raise RuntimeError("request identity was not initialized")
    return principal


def _request_id(message: str, session_id: str) -> str:
    supplied = (request.headers.get("Idempotency-Key") or "").strip()
    if supplied:
        if len(supplied) > 200:
            raise ValueError("Idempotency-Key is too long")
        return supplied
    # Idempotency identifies a client-declared logical request, not its content.
    # Without an explicit key, every submission is a new request so intentional
    # repeated messages are retained as distinct turns.
    return "auto-" + uuid.uuid4().hex


def _chat_session(data: dict) -> tuple[str, str]:
    principal = _principal()
    requested = str(data.get("session_id") or "").strip()
    archive = get_service().archive
    if requested and archive.owns_session(principal.user_id, requested):
        return requested, principal.user_id
    # Never trust or reveal ownership of a caller-supplied ID. Unknown/foreign
    # IDs fall back to this principal's permanent session.
    archive.ensure_session(principal.user_id, principal.session_id)
    return principal.session_id, principal.user_id


# ---------------------------------------------------------------------------
# Security: signed principal identity + optional service key + rate limiting
# ---------------------------------------------------------------------------
_auth = ApiAuth(_settings.api_key, _settings.admin_api_key)
_limiter = RateLimiter(_settings.rate_limit_per_minute)
# Separate bucket for requests that arrive WITHOUT a usable identity, so a client
# that discards its cookie cannot mint an unlimited number of fresh quotas.
_anon_limiter = RateLimiter(
    _settings.rate_limit_per_minute * max(1, _settings.anon_rate_limit_multiplier)
    if _settings.rate_limit_per_minute > 0 else 0
)
# Platform probes. Unauthenticated, identity-free and rate-limit-free, and by
# construction side-effect-free (ISSUE-038).
_PROBE_PATHS = {"/health", "/live"}
_OPEN_PATHS = _PROBE_PATHS | {"/"}


def _network_key() -> str:
    """Coarse pre-identity signal. Not a user identifier and never stored."""
    fwd = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return f"net:{fwd or request.remote_addr or 'unknown'}"


def _client_identity() -> str:
    principal = getattr(g, "principal", None)
    if principal is not None:
        return f"user:{principal.user_id}"
    return _network_key().replace("net:", "ip:")


@app.before_request
def _guard_request():
    # Generated for every request so the CSP nonce is never reused.
    g.csp_nonce = secrets.token_urlsafe(16)
    if request.method == "OPTIONS" or request.path in _PROBE_PATHS:
        return None
    try:
        g.principal = _identity.from_request(request.headers, request.cookies)
    except InvalidIdentity:
        return jsonify({"error": "invalid identity"}), 401

    # A newly minted identity means the caller presented none, so it is charged
    # to the network bucket. Callers that keep their identity are unaffected.
    if getattr(g.principal, "is_new", False):
        allowed, retry = _anon_limiter.check(_network_key())
        if not allowed:
            return jsonify({"error": "rate limit exceeded", "retry_after": retry}), 429

    is_document_write = (
        request.path.startswith("/documents")
        and request.method in ("POST", "DELETE")
    )
    if request.path not in _OPEN_PATHS and (_auth.enabled or
                                             (is_document_write and _auth.admin_enabled)):
        presented = ApiAuth.extract_key(request.headers)
        ok = (_auth.check_admin(presented) if is_document_write
              else _auth.check(presented))
        if not ok:
            log.warning("auth rejected path=%s", request.path)
            return jsonify({"error": "unauthorized"}), 401

    if request.path not in _OPEN_PATHS:
        try:
            if (get_service().archive.is_user_deleted(g.principal.user_id)
                    and not (request.path == "/account"
                             and request.method == "DELETE")):
                response = jsonify({"error": "identity was deleted"})
                response.delete_cookie(_identity.COOKIE_NAME, path="/", samesite="Strict")
                return response, 401
        except Exception as exc:
            log.error("identity revocation check failed: %s", type(exc).__name__)
            return jsonify({"error": "identity verification unavailable"}), 503

    allowed, retry = _limiter.check(_client_identity())
    if not allowed:
        return jsonify({"error": "rate limit exceeded", "retry_after": retry}), 429
    try:
        run_retention_sweep()
    except Exception as exc:
        # Retention must never block a user's request.
        log.error("retention sweep skipped: %s", type(exc).__name__)
    return None


@app.after_request
def _set_security_headers(response):
    """Defence-in-depth browser headers.

    The CSP is nonce-based rather than using 'unsafe-inline': the UI's inline
    style and script blocks carry the per-request nonce, so injected markup
    cannot execute even if it reaches the page.
    """
    nonce = getattr(g, "csp_nonce", "")
    response.headers.setdefault("Content-Security-Policy", "; ".join((
        "default-src 'self'",
        f"script-src 'self' 'nonce-{nonce}'",
        f"style-src 'self' 'nonce-{nonce}'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "font-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )))
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    # Only meaningful over TLS, and harmful to send otherwise.
    if request.is_secure or _settings.secure_identity_cookie:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.after_request
def _set_identity_cookie(response):
    principal = getattr(g, "principal", None)
    if principal is not None and (principal.is_new or principal.needs_refresh):
        # Sliding renewal: an active caller keeps working indefinitely while an
        # abandoned token still expires on its own clock.
        if principal.needs_refresh and not principal.is_new:
            principal = _identity.reissue(principal)
        response.set_cookie(
            _identity.COOKIE_NAME, principal.token,
            max_age=_identity.MAX_AGE_SECONDS, httponly=True,
            secure=_settings.secure_identity_cookie or request.is_secure,
            samesite="Strict", path="/",
        )
    return response


# ---------------------------------------------------------------------------
# Health / metrics
# ---------------------------------------------------------------------------
@app.get("/live")
def live():
    """Liveness: is this process running?

    ISSUE-038: deliberately answers from process state alone - no service
    construction, no backend contact, no configuration that can fail - so a
    restart is only ever triggered by a genuinely dead process, not by a slow
    cold start or a degraded dependency.
    """
    return jsonify({"status": "alive", "service": "soulene-cag",
                    "uptime_seconds": round(time.time() - _PROCESS_STARTED_AT, 3)}), 200


@app.get("/health")
def health():
    """Readiness: should this process receive traffic?

    Reports the outcome of explicit initialization plus a deadline-bounded
    dependency probe. It never initializes anything itself (ISSUE-038).
    """
    body, code = readiness_report()
    return jsonify(body), code


@app.get("/metrics")
def metrics():
    # ISS-18 FIX: Require authentication for metrics endpoint.
    if _auth.enabled:
        presented = ApiAuth.extract_key(request.headers, request.args)
        if not _auth.check(presented):
            return jsonify({"error": "unauthorized"}), 401
    try:
        stats = get_service().stats()
        # Surfaced so the at-rest posture is observable rather than assumed.
        stats["storage_at_rest"] = storage_posture(_settings, _data_file_paths())
        # Content-free record of what crossed the external model boundary.
        stats["operational"] = {
            "counters": COUNTERS.snapshot(),
            "disk": disk_posture(_settings.data_path, _settings.disk_warn_below_mb),
            "model_budget": (get_service().client._budget.snapshot()
                             if getattr(get_service().client, "_budget", None)
                             else {"limit": 0}),
        }
        stats["provider_transmission"] = {
            **LEDGER.snapshot(),
            "disclosure_required": bool(_settings.require_provider_disclosure),
            "disclosure_attested": bool(_settings.provider_disclosure_attested.strip()),
            "cross_session_context_sent": bool(_settings.send_cross_session_context),
        }
        return jsonify(stats), 200
    except Exception as exc:
        log.error("metrics failed: %s", type(exc).__name__)
        return jsonify({"error": "metrics unavailable"}), 503


def _data_file_paths() -> list:
    data_dir = _settings.root / "data"
    return [data_dir / "chat_archive.sqlite3", data_dir / "feedback.sqlite3"]


@app.get("/")
def index():
    return render_template("index.html", csp_nonce=g.csp_nonce)


@app.get("/identity")
def identity():
    """Return only the caller's own stable pseudonymous identity."""
    principal = _principal()
    try:
        get_service().archive.ensure_session(principal.user_id, principal.session_id)
    except Exception as exc:
        log.error("identity persistence failed: %s", type(exc).__name__)
        return jsonify({"error": "identity unavailable"}), 503
    return jsonify({"user_id": principal.user_id,
                    "session_id": principal.session_id}), 200


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
@app.post("/chat")
def chat():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    if not isinstance(message, str) or not message.strip():
        return jsonify({"reply": "Please enter a message."}), 400
    # Oversized input is refused whole: truncating could drop risk wording.
    if exceeds_message_limit(message):
        return jsonify({"reply": oversized_message_reply(message),
                        "error": "message too long",
                        "max_chars": MAX_MESSAGE_CHARS}), 413
    try:
        session_id, user_id = _chat_session(data)
        request_id = _request_id(message.strip(), session_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    t0 = time.time()
    try:
        result = get_service().handle(
            session_id=session_id, user_message=message.strip(),
            user_id=user_id, request_id=request_id,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 409
    except Exception as exc:
        log.error("chat failed before durable completion: %s", type(exc).__name__)
        return jsonify({"reply": "Your message could not be saved. Please retry.",
                        "error": "persistence unavailable"}), 503
    log.info("chat ok intent=%s safety=%s latency=%.2fs",
             result.intent.value, result.safety_level.value, time.time() - t0)
    return jsonify({
        "reply": result.reply,
        "route": result.route.value,
        "request_id": request_id,
        "latency_ms": int((time.time() - t0) * 1000),
        # Attribution for knowledge-grounded answers; empty means the reply was
        # not grounded in a document and should not be read as sourced fact.
        "grounded": bool(result.used_rag),
        "sources": result.retrieved,
    })


@app.post("/chat/stream")
def chat_stream():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    if not isinstance(message, str) or not message.strip():
        return jsonify({"reply": "Please enter a message."}), 400
    if exceeds_message_limit(message):
        return jsonify({"reply": oversized_message_reply(message),
                        "error": "message too long",
                        "max_chars": MAX_MESSAGE_CHARS}), 413
    try:
        session_id, user_id = _chat_session(data)
        request_id = _request_id(message.strip(), session_id)
        # The pipeline already buffers model output for safety. Complete and
        # durably commit the turn before sending SSE headers or [DONE].
        result = get_service().handle(
            session_id=session_id, user_message=message.strip(),
            user_id=user_id, request_id=request_id,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        log.error("stream failed before durable completion: %s", type(exc).__name__)
        return jsonify({"error": "message was not durably stored"}), 503

    def generate():
        yield f"data: {json.dumps({'delta': result.reply, 'request_id': request_id})}\n\n"
        yield "data: [DONE]\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# Documents (CAG knowledge cache)
# ---------------------------------------------------------------------------
@app.get("/documents")
def list_documents():
    try:
        svc = get_service()
        return jsonify({"documents": svc.cag.knowledge.documents(),
                        "cache": svc.cag.knowledge.stats()}), 200
    except Exception:
        return jsonify({"error": "unavailable"}), 503


@app.post("/documents")
def upload_document():
    if "file" not in request.files:
        return jsonify({"error": "no file provided (field name: 'file')"}), 400
    f = request.files["file"]
    filename = (f.filename or "").strip()
    if not filename:
        return jsonify({"error": "empty filename"}), 400

    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return jsonify({"error": f"unsupported type {ext}",
                        "supported": sorted(SUPPORTED_EXTENSIONS)}), 415

    # Sanitize: strip any directory components to prevent path traversal.
    safe_name = Path(filename).name.replace("\\", "_")
    knowledge_type = (request.form.get("knowledge_type") or "general").strip().lower()
    knowledge_type = "".join(c for c in knowledge_type if c.isalnum() or c in "-_") or "general"

    target_dir = _settings.knowledge_path / knowledge_type
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe_name

    # Staged write: any previous version is set aside under an unindexed
    # extension so a failed ingest can be compensated back to the prior state.
    backup = target.with_name(target.name + ".prev") if target.exists() else None
    try:
        if backup is not None:
            os.replace(target, backup)
        f.save(str(target))
    except Exception as exc:
        log.error("upload save failed: %s", type(exc).__name__)
        if backup is not None and backup.exists():
            os.replace(backup, target)
        return jsonify({"error": "could not save file"}), 500

    try:
        report = get_service().cag.refresh_documents()
    except Exception as exc:
        log.error("upload ingest failed: %s", type(exc).__name__)
        # Compensate so the filesystem never disagrees with the index.
        target.unlink(missing_ok=True)
        if backup is not None and backup.exists():
            os.replace(backup, target)
        try:
            get_service().cag.refresh_documents()
        except Exception:
            log.error("post-rollback reconcile failed; run a forced refresh")
        return jsonify({"error": "indexing failed; upload was rolled back"}), 500

    if backup is not None:
        backup.unlink(missing_ok=True)
    log.info("document ingested name=%s type=%s sections=%s",
             safe_name, knowledge_type, report.get("sections"))
    return jsonify({"status": "indexed", "document": safe_name,
                    "knowledge_type": knowledge_type, "cache": report}), 201


@app.delete("/documents/<path:name>")
def delete_document(name: str):
    # Documents are identified by canonical relative path, so a subdirectory is
    # preserved; traversal components are rejected outright.
    requested = Path(name)
    if requested.is_absolute() or ".." in requested.parts:
        return jsonify({"error": "invalid document name"}), 400
    safe = requested.as_posix()
    try:
        svc = get_service()
        target = svc.cag.knowledge.document_path(safe)
        if target is None:
            return jsonify({"error": "not found"}), 404
        # Remove exactly one file, then the index entry. This order is safe: a
        # later index failure is reconciled by refresh, whereas removing the
        # index first could let a refresh resurrect the document.
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            log.error("document unlink failed: %s", type(exc).__name__)
            return jsonify({"error": "delete failed"}), 500
        try:
            svc.cag.remove_document(safe)
        except Exception:
            log.exception("index removal failed; reconciling from disk")
            svc.cag.refresh_documents()
        return jsonify({"status": "removed", "document": safe}), 200
    except Exception:
        return jsonify({"error": "delete failed"}), 500


# ---------------------------------------------------------------------------
# Sessions (all ownership comes from the verified principal)
# ---------------------------------------------------------------------------
@app.get("/sessions")
def list_sessions():
    principal = _principal()
    try:
        svc = get_service()
        svc.archive.ensure_session(principal.user_id, principal.session_id)
        sessions = svc.archive.list_sessions(principal.user_id)
        return jsonify({"sessions": sessions,
                        "permanent_session_id": principal.session_id}), 200
    except Exception as exc:
        log.error("session list failed: %s", type(exc).__name__)
        return jsonify({"error": "sessions unavailable"}), 503


@app.post("/sessions")
def create_session():
    principal = _principal()
    try:
        session = get_service().archive.create_session(principal.user_id)
        return jsonify({"status": "created", "session": session}), 201
    except Exception as exc:
        log.error("session creation failed: %s", type(exc).__name__)
        return jsonify({"error": "session could not be persisted"}), 503


@app.get("/sessions/<session_id>")
def get_session_detail(session_id: str):
    principal = _principal()
    try:
        archive = get_service().archive
        if not archive.owns_session(principal.user_id, session_id):
            return jsonify({"error": "session not found"}), 404
        messages = archive.fetch_page(principal.user_id, session_id, 0, 1000)
        msg_list = [
            {"role": m.role, "content": m.content, "created_at": m.created_at,
             "message_id": m.message_id, "sequence_number": m.sequence_number}
            for m in messages
        ]
        return jsonify({"session_id": session_id, "messages": msg_list}), 200
    except Exception as exc:
        log.error("session read failed: %s", type(exc).__name__)
        return jsonify({"error": "session unavailable"}), 503


@app.delete("/sessions/<session_id>")
def delete_session(session_id: str):
    principal = _principal()
    try:
        svc = get_service()
        if not svc.archive.owns_session(principal.user_id, session_id):
            return jsonify({"error": "session not found"}), 404
        # Remove only memories whose attributed evidence came exclusively from
        # this session. Legacy unattributed memories are retained rather than
        # guessed; account deletion still removes all memory.
        forget_session = getattr(svc.profile, "forget_session", None)
        memory_outcome = {}
        if callable(forget_session):
            memory_outcome = forget_session(principal.user_id, session_id) or {}
        svc.clear_user(principal.user_id)
        if not svc.archive.delete_conversation(principal.user_id, session_id):
            return jsonify({"error": "session not found"}), 404
        # Deletion outcomes are reported rather than implied. `quarantined` is
        # deliberately distinct from `removed`: those records still exist in
        # storage, so the flag below states that plainly for any caller.
        if memory_outcome:
            memory_outcome["quarantined_still_stored"] = bool(
                memory_outcome.get("quarantined"))
        return jsonify({"status": "deleted", "derived_memory": memory_outcome}), 200
    except Exception as exc:
        log.error("session deletion failed: %s", type(exc).__name__)
        return jsonify({"error": "delete failed"}), 503


_DELETION_STEPS = ("archive", "memory", "feedback", "caches")


@app.delete("/account")
def delete_account():
    principal = _principal()
    user_id = principal.user_id
    try:
        svc = get_service()
    except Exception as exc:
        log.error("account deletion unavailable: %s", type(exc).__name__)
        return jsonify({"error": "account deletion failed"}), 503

    # Durable per-step state, so a retry resumes instead of restarting a
    # partially applied deletion across independently failing stores.
    try:
        state = svc.archive.start_deletion_job(user_id, _DELETION_STEPS)
    except Exception as exc:
        log.error("deletion job could not be recorded: %s", type(exc).__name__)
        return jsonify({"error": "account deletion failed"}), 503

    # Archive first: the tombstone stops any worker committing new turns while
    # the remaining stores are cleared. Every step is idempotent on retry.
    # `forget_user` is unconditional and removes quarantined records too, so
    # account deletion deliberately does not consult the ISSUE-018 boundary.
    actions = {
        "archive": lambda: svc.archive.delete_user(user_id),
        "memory": lambda: svc.profile.forget_user(user_id),
        "feedback": lambda: get_feedback().delete_user(user_id),
        "caches": lambda: svc.clear_user(user_id),
    }

    failed = []
    for step in _DELETION_STEPS:
        if str(state.get(step, "")).startswith("completed"):
            continue
        try:
            actions[step]()
        except Exception as exc:
            failed.append(step)
            log.error("account deletion step %s failed: %s", step, type(exc).__name__)
            _record_deletion_step(svc, user_id, step, "failed", type(exc).__name__)
        else:
            _record_deletion_step(svc, user_id, step, "completed")

    receipt = _deletion_receipt(svc, user_id)
    if failed:
        # The identity stays revoked and the retained steps are named, so the
        # caller can retry this idempotent endpoint until it converges.
        return jsonify({"error": "account deletion incomplete",
                        "pending": failed, "receipt": receipt}), 503
    try:
        svc.archive.finish_deletion_job(user_id)
    except Exception as exc:
        log.error("deletion completion not recorded: %s", type(exc).__name__)
    response = jsonify({"status": "deleted",
                        "receipt": _deletion_receipt(svc, user_id) or receipt})
    response.delete_cookie(_identity.COOKIE_NAME, path="/", samesite="Strict")
    return response, 200


def _record_deletion_step(svc, user_id: str, step: str, status: str,
                          error: Optional[str] = None) -> None:
    recorder = getattr(svc.archive, "record_deletion_step", None)
    if not callable(recorder):
        return
    try:
        recorder(user_id, step, status, error=error)
    except Exception as exc:
        # Losing a checkpoint only costs a repeated (idempotent) step later.
        log.error("deletion checkpoint failed for %s: %s", step, type(exc).__name__)


def _deletion_receipt(svc, user_id: str) -> Optional[dict]:
    reader = getattr(svc.archive, "deletion_job", None)
    if not callable(reader):
        return None
    try:
        return reader(user_id)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Feedback (Layer 3 - isolated from chat)
# ---------------------------------------------------------------------------
@app.post("/feedback")
def submit_feedback():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    if not isinstance(message, str) or not message.strip():
        return jsonify({"error": "message is required"}), 400
    user_id = _principal().user_id
    category = str(data.get("category") or "other")
    try:
        item = get_feedback().submit(user_id=user_id, message=message.strip(), category=category)
    except Exception as exc:
        log.error("feedback persistence failed: %s", type(exc).__name__)
        return jsonify({"error": "could not save feedback"}), 500
    log.info("feedback stored category=%s", item.category)
    return jsonify({"status": "received", "feedback_id": item.feedback_id,
                    "category": item.category}), 201


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Explicit initialization for WSGI servers (gunicorn). ISSUE-038: startup owns
# initialization so a probe never triggers it. Failures leave the process alive
# and answering /live, while /health stays fail-closed at 503 until a real
# request succeeds in initializing.
# ---------------------------------------------------------------------------
def _warm_on_import() -> None:
    if os.getenv("SOULENE_SKIP_WARM", "").lower() in {"1", "true", "yes"}:
        return
    if not os.getenv("OPENAI_API_KEY", "").strip():
        log.warning("OPENAI_API_KEY not set at import; deferring initialisation")
        return
    if not initialize_service():
        log.error("startup initialization failed; readiness stays unavailable "
                  "and will retry on first request")


# Detect gunicorn/uwsgi: warm only when not running as a plain script or under tests.
if not any(a.endswith(("unittest", "pytest")) or a in ("--cli",) for a in sys.argv) \
        and os.getenv("SERVER_SOFTWARE", "").startswith("gunicorn"):
    _warm_on_import()


def run_cli() -> None:
    # ISSUE-005: the CLI bypasses identity, authorization and rate limiting by
    # design (it calls the service directly). That is only acceptable as a local
    # developer tool, so it refuses to run against shared production storage or
    # in a deployment that requires authentication, unless explicitly overridden.
    reasons = []
    if _settings.storage_backend == "mongo":
        reasons.append("STORAGE_BACKEND=mongo (shared production storage)")
    if _settings.require_api_auth:
        reasons.append("REQUIRE_API_AUTH=true (deployment requires authenticated access)")
    if reasons and os.getenv("SOULENE_ALLOW_UNSAFE_CLI", "").lower() not in {"1", "true", "yes"}:
        print("Refusing to start the CLI: it has no authentication, rate limiting "
              "or identity revocation.")
        for reason in reasons:
            print(f"  - {reason}")
        print("Set SOULENE_ALLOW_UNSAFE_CLI=1 only for a deliberate local session.")
        raise SystemExit(2)

    service = get_service()
    session_id = os.getenv("SOULENE_SESSION_ID", "").strip() or f"cli-{uuid.uuid4().hex[:8]}"
    print("=" * 62)
    print("  SOULENE AI - your mental wellbeing companion  (CAG)")
    print("  /clear reset  |  /stats cache  |  /quit exit")
    print("=" * 62)
    while True:
        try:
            raw = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nTake care. I'm here whenever you need me.\n")
            break
        if not raw:
            continue
        if raw.lower() == "/quit":
            print("\nTake care. I'm here whenever you need me.\n")
            break
        if raw.lower() == "/clear":
            service.clear(session_id)
            print("\n(conversation cleared)\n")
            continue
        if raw.lower() == "/stats":
            print(json.dumps(service.stats(), indent=2))
            continue
        t0 = time.time()
        res = service.handle(session_id, raw, user_id=session_id)
        tag = "cache" if "cache_hit=True" in " ".join(res.notes) else res.intent.value
        print(f"\nSoulene [{tag} {int((time.time()-t0)*1000)}ms]: {res.reply}\n")


if __name__ == "__main__":
    if "--retention" in sys.argv:
        # Operator entry point: run one sweep now regardless of the interval.
        print(json.dumps(run_retention_sweep(force=True), indent=2))
    elif "--cli" in sys.argv:
        run_cli()
    else:
        port = int(os.getenv("PORT", "5000"))
        # ISSUE-038: explicit initialization before the first request, and loud
        # on failure here because a developer is watching this terminal.
        get_service()
        app.run(host="0.0.0.0", port=port)
