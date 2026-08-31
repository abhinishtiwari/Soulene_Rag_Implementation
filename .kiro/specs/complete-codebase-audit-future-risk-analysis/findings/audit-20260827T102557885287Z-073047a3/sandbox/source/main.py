"""Soulene AI - CAG mental-health companion. Flask entry point.

Run:
    python main.py            # web UI + API   (http://localhost:5000)
    python main.py --cli      # terminal chat

Endpoints:
    GET  /                 chat UI
    GET  /health           health check (Render)
    GET  /metrics          cache / performance stats
    POST /chat             JSON reply
    POST /chat/stream      SSE token stream
    POST /documents        upload a knowledge document (multipart)
    GET  /documents        list cached documents
    DELETE /documents/<n>  remove a document from the knowledge cache
    POST /feedback         submit feedback (isolated store)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path

from flask import Flask, Response, g, jsonify, render_template, request, stream_with_context

from app.cag.document_processor import SUPPORTED_EXTENSIONS
from app.chatbot import build_chatbot
from app.config.settings import Settings
from app.identity import IdentityManager, InvalidIdentity, Principal
from app.security import ApiAuth, RateLimiter
from app.storage.feedback_store import FeedbackStore

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
app.config["MAX_CONTENT_LENGTH"] = _settings.max_upload_mb * 1024 * 1024

_service = None
_feedback = None
_identity = IdentityManager.from_config(
    _settings.identity_secret,
    _settings.root / "data",
    require_configured=_settings.storage_backend == "mongo",
)


def get_service():
    global _service
    if _service is None:
        t0 = time.time()
        _settings.require_api_key()
        _settings.validate_storage()
        _service = build_chatbot(_settings)
        stats = _service.cag.stats()["knowledge_cache"]
        log.info("chatbot ready in %.2fs | docs=%s sections=%s tokens=%s full_preload=%s",
                 time.time() - t0, stats["documents"], stats["sections"],
                 stats["approx_tokens"], stats["full_preload"])
    return _service


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
_OPEN_PATHS = {"/health", "/"}


def _client_identity() -> str:
    principal = getattr(g, "principal", None)
    if principal is not None:
        return f"user:{principal.user_id}"
    fwd = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return f"ip:{fwd or request.remote_addr or 'unknown'}"


@app.before_request
def _guard_request():
    if request.method == "OPTIONS" or request.path == "/health":
        return None
    try:
        g.principal = _identity.from_request(request.headers, request.cookies)
    except InvalidIdentity:
        return jsonify({"error": "invalid identity"}), 401

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
    return None


@app.after_request
def _set_identity_cookie(response):
    principal = getattr(g, "principal", None)
    if principal is not None and principal.is_new:
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
@app.get("/health")
def health():
    try:
        get_service().archive.healthcheck()
        return jsonify({"status": "ok", "service": "soulene-cag",
                        "storage": _settings.storage_backend}), 200
    except Exception as exc:
        log.error("readiness failed: %s", type(exc).__name__)
        return jsonify({"status": "unavailable", "service": "soulene-cag"}), 503


@app.get("/metrics")
def metrics():
    # ISS-18 FIX: Require authentication for metrics endpoint.
    if _auth.enabled:
        presented = ApiAuth.extract_key(request.headers, request.args)
        if not _auth.check(presented):
            return jsonify({"error": "unauthorized"}), 401
    try:
        return jsonify(get_service().stats()), 200
    except Exception as exc:
        log.error("metrics failed: %s", type(exc).__name__)
        return jsonify({"error": "metrics unavailable"}), 503


@app.get("/")
def index():
    return render_template("index.html")


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
    })


@app.post("/chat/stream")
def chat_stream():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    if not isinstance(message, str) or not message.strip():
        return jsonify({"reply": "Please enter a message."}), 400
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
    try:
        f.save(str(target))
    except Exception as exc:
        log.error("upload save failed: %s", type(exc).__name__)
        return jsonify({"error": "could not save file"}), 500

    try:
        report = get_service().cag.refresh_documents()
    except Exception as exc:
        log.error("upload ingest failed: %s", type(exc).__name__)
        return jsonify({"error": "file saved but indexing failed"}), 500

    log.info("document ingested name=%s type=%s sections=%s",
             safe_name, knowledge_type, report.get("sections"))
    return jsonify({"status": "indexed", "document": safe_name,
                    "knowledge_type": knowledge_type, "cache": report}), 201


@app.delete("/documents/<path:name>")
def delete_document(name: str):
    safe = Path(name).name
    try:
        svc = get_service()
        removed = svc.cag.remove_document(safe)
        if not removed:
            return jsonify({"error": "not found"}), 404
        # Delete the underlying file so a refresh won't resurrect it.
        for p in _settings.knowledge_path.rglob(safe):
            if p.is_file():
                p.unlink(missing_ok=True)
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
        if callable(forget_session):
            forget_session(principal.user_id, session_id)
        svc.clear_user(principal.user_id)
        if not svc.archive.delete_conversation(principal.user_id, session_id):
            return jsonify({"error": "session not found"}), 404
        return jsonify({"status": "deleted"}), 200
    except Exception as exc:
        log.error("session deletion failed: %s", type(exc).__name__)
        return jsonify({"error": "delete failed"}), 503


@app.delete("/account")
def delete_account():
    principal = _principal()
    try:
        svc = get_service()
        # Revoke first so no worker can commit new turns while secondary data is
        # being removed. A revoked token may retry only this idempotent endpoint
        # if a secondary store is temporarily unavailable.
        svc.archive.delete_user(principal.user_id)
        svc.profile.forget_user(principal.user_id)
        get_feedback().delete_user(principal.user_id)
        svc.clear_user(principal.user_id)
        response = jsonify({"status": "deleted"})
        response.delete_cookie(_identity.COOKIE_NAME, path="/", samesite="Strict")
        return response, 200
    except Exception as exc:
        log.error("account deletion failed: %s", type(exc).__name__)
        return jsonify({"error": "account deletion failed"}), 503


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
# Eager warm-up for WSGI servers (gunicorn) so the first real request is fast.
# Failures are swallowed: /health must stay responsive even if warm-up fails.
# ---------------------------------------------------------------------------
def _warm_on_import() -> None:
    if os.getenv("SOULENE_SKIP_WARM", "").lower() in {"1", "true", "yes"}:
        return
    if not os.getenv("OPENAI_API_KEY", "").strip():
        log.warning("OPENAI_API_KEY not set at import; deferring initialisation")
        return
    try:
        get_service()
    except Exception as exc:
        log.error("warm-up failed (%s); will retry on first request", type(exc).__name__)


# Detect gunicorn/uwsgi: warm only when not running as a plain script or under tests.
if not any(a.endswith(("unittest", "pytest")) or a in ("--cli",) for a in sys.argv) \
        and os.getenv("SERVER_SOFTWARE", "").startswith("gunicorn"):
    _warm_on_import()


def run_cli() -> None:
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
    if "--cli" in sys.argv:
        run_cli()
    else:
        port = int(os.getenv("PORT", "5000"))
        get_service()
        app.run(host="0.0.0.0", port=port)
