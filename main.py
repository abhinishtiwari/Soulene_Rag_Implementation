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

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from app.cag.document_processor import SUPPORTED_EXTENSIONS
from app.chatbot import build_chatbot
from app.config.settings import Settings
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
_feedback: FeedbackStore | None = None
_WEB_SESSION = os.getenv("SOULENE_SESSION_ID", "").strip() or f"web-{uuid.uuid4().hex[:12]}"


def get_service():
    global _service
    if _service is None:
        t0 = time.time()
        _settings.require_api_key()
        _service = build_chatbot(_settings)
        stats = _service.cag.stats()["knowledge_cache"]
        log.info("chatbot ready in %.2fs | docs=%s sections=%s tokens=%s full_preload=%s",
                 time.time() - t0, stats["documents"], stats["sections"],
                 stats["approx_tokens"], stats["full_preload"])
    return _service


def get_feedback() -> FeedbackStore:
    global _feedback
    if _feedback is None:
        _feedback = FeedbackStore(_settings.root / "data" / "feedback.sqlite3")
    return _feedback


def _ids(data: dict) -> tuple[str, str]:
    session_id = str(data.get("session_id") or _WEB_SESSION).strip()
    user_id = str(data.get("user_id") or session_id).strip()
    return session_id, user_id


# ---------------------------------------------------------------------------
# Security: optional API-key auth + rate limiting (both off unless configured)
# ---------------------------------------------------------------------------
_auth = ApiAuth(_settings.api_key, _settings.admin_api_key)
_limiter = RateLimiter(_settings.rate_limit_per_minute)

# Endpoints that never require auth (probes + UI shell).
_OPEN_PATHS = {"/health", "/", "/sessions"}


def _client_identity() -> str:
    """Rate-limit key: prefer the API key, else the client IP."""
    key = ApiAuth.extract_key(request.headers, request.args)
    if key:
        return f"key:{key[:12]}"
    fwd = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return f"ip:{fwd or request.remote_addr or 'unknown'}"


@app.before_request
def _guard_request():
    if request.method == "OPTIONS" or request.path in _OPEN_PATHS:
        return None
    # Allow session sub-routes and chat without auth for the UI
    if request.path.startswith("/sessions"):
        return None
    if request.path.startswith("/chat"):
        data = request.get_json(silent=True) or {}
        if data.get("user_id"):
            return None

    if _auth.enabled:
        presented = ApiAuth.extract_key(request.headers, request.args)
        # Document writes require the admin key when one is configured.
        is_write = request.path.startswith("/documents") and request.method in ("POST", "DELETE")
        ok = _auth.check_admin(presented) if is_write else _auth.check(presented)
        if not ok:
            log.warning("auth rejected path=%s", request.path)
            return jsonify({"error": "unauthorized"}), 401

    allowed, retry = _limiter.check(_client_identity())
    if not allowed:
        return jsonify({"error": "rate limit exceeded", "retry_after": retry}), 429
    return None


# ---------------------------------------------------------------------------
# Health / metrics
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "soulene-cag"}), 200


@app.get("/metrics")
def metrics():
    try:
        return jsonify(get_service().stats()), 200
    except Exception as exc:
        log.error("metrics failed: %s", type(exc).__name__)
        return jsonify({"error": "metrics unavailable"}), 503


@app.get("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------
@app.post("/chat")
def chat():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    if not isinstance(message, str) or not message.strip():
        return jsonify({"reply": "Please enter a message."}), 400
    session_id, user_id = _ids(data)
    t0 = time.time()
    try:
        result = get_service().handle(session_id=session_id,
                                      user_message=message.strip(), user_id=user_id)
    except Exception as exc:
        log.error("chat failed: %s", type(exc).__name__)
        return jsonify({"reply": "Sorry, something went wrong. Please try again."}), 500
    log.info("chat ok intent=%s safety=%s latency=%.2fs",
             result.intent.value, result.safety_level.value, time.time() - t0)
    return jsonify({
        "reply": result.reply,
        "route": result.route.value,
        "intent": result.intent.value,
        "safety_level": result.safety_level.value,
        "used_knowledge": result.used_rag,
        "latency_ms": int((time.time() - t0) * 1000),
    })


@app.post("/chat/stream")
def chat_stream():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    if not isinstance(message, str) or not message.strip():
        return jsonify({"reply": "Please enter a message."}), 400
    session_id, user_id = _ids(data)

    def generate():
        try:
            for chunk in get_service().handle_stream(
                    session_id=session_id, user_message=message.strip(), user_id=user_id):
                yield f"data: {json.dumps({'delta': chunk})}\n\n"
        except Exception as exc:
            log.error("stream failed: %s", type(exc).__name__)
            yield f"data: {json.dumps({'delta': 'Sorry, something went wrong.'})}\n\n"
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
# Sessions (JSON-backed multi-session management)
# ---------------------------------------------------------------------------
@app.get("/sessions")
def list_sessions():
    """List all sessions for a user."""
    user_id = request.args.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    try:
        svc = get_service()
        sessions = svc.archive.list_sessions(user_id)
        return jsonify({"user_id": user_id, "sessions": sessions}), 200
    except Exception:
        return jsonify({"user_id": user_id, "sessions": []}), 200


@app.post("/sessions")
def create_session():
    """Create a new chat session for a user."""
    data = request.get_json(silent=True) or {}
    _, user_id = _ids(data)
    try:
        svc = get_service()
        session = svc.archive.create_session(user_id)
        return jsonify({"status": "created", "session": session}), 201
    except Exception:
        session_id = f"{user_id}-{uuid.uuid4().hex[:12]}"
        return jsonify({"status": "created", "session": {
            "session_id": session_id, "user_id": user_id,
            "title": "New Chat", "created_at": time.time(),
            "updated_at": time.time(), "last_message": ""
        }}), 201


@app.get("/sessions/<session_id>")
def get_session_detail(session_id: str):
    """Get a specific session with its messages."""
    user_id = request.args.get("user_id", "").strip()
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    try:
        svc = get_service()
        messages = svc.archive.fetch_recent(user_id, session_id, limit=100)
        msg_list = [
            {"role": m.role, "content": m.content, "created_at": m.created_at,
             "message_id": m.message_id}
            for m in messages
        ]
        return jsonify({"session_id": session_id, "messages": msg_list}), 200
    except Exception:
        return jsonify({"session_id": session_id, "messages": []}), 200


@app.delete("/sessions/<session_id>")
def delete_session(session_id: str):
    """Delete a session and its messages."""
    user_id = request.args.get("user_id", "").strip()
    if not user_id:
        data = request.get_json(silent=True) or {}
        _, user_id = _ids(data)
    try:
        svc = get_service()
        svc.archive.delete_conversation(user_id, session_id)
        svc.clear(session_id)
        return jsonify({"status": "deleted"}), 200
    except Exception:
        return jsonify({"error": "delete failed"}), 500


# ---------------------------------------------------------------------------
# Feedback (Layer 3 - isolated from chat)
# ---------------------------------------------------------------------------
@app.post("/feedback")
def submit_feedback():
    data = request.get_json(silent=True) or {}
    message = data.get("message", "")
    if not isinstance(message, str) or not message.strip():
        return jsonify({"error": "message is required"}), 400
    _, user_id = _ids(data)
    category = str(data.get("category") or "other")
    try:
        item = get_feedback().submit(user_id=user_id, message=message.strip(), category=category)
    except Exception:
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
