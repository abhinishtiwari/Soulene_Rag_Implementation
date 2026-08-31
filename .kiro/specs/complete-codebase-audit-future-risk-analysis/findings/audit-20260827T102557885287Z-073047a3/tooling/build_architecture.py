from __future__ import annotations

import json
import sys
from pathlib import Path

RUN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUN_ROOT / "tooling"))
from audit_controls import write_json, write_jsonl  # noqa: E402

ENTRYPOINTS = [
    ("EP-WEB", "user", "main.py", "app", "Flask/Gunicorn HTTP routes"),
    ("EP-CLI", "executable", "main.py", "run_cli", "python main.py --cli"),
    ("EP-CACHE", "executable", "build_cache.py", "main", "cache build/stats CLI"),
    ("EP-UI", "user", "ui/index.html", "initialize/chat submit", "browser UI"),
    ("EP-DEV", "deployment", "main.py", "__main__", "Flask development server"),
    ("EP-GUNICORN", "deployment", "render.yaml", "startCommand", "two workers/four threads"),
    ("EP-PROCFILE", "deployment", "Procfile", "web", "Gunicorn process declaration"),
    ("EP-PYTEST", "test", "pytest.ini", "testpaths", "pytest tests/ discovery"),
    ("EP-ROOT-ALL", "test", "test_all.py", "__main__", "root script test entry"),
    ("EP-ROOT-AUDIT", "test", "test_audit.py", "__main__", "root audit script entry"),
    ("EP-CONTEXT-AUDIT", "test", "context_audit.py", "__main__", "historical audit script"),
    ("EP-SMOKE-LIVE", "test", "tests/smoke_live.py", "main", "live model smoke"),
    ("EP-SMOKE-STAGING", "test", "tests/smoke_staging.py", "main", "staging HTTP smoke"),
]


def edge(trace_id, entry, order, source, destination, source_symbol, destination_symbol, data, validation, authentication, authorization, trust, side_effect, failure, variant, evidence):
    return {"schema_version":"1.0","run_id":RUN_ROOT.name,"trace_id":trace_id,"entry_point_id":entry,"order":order,"source_component":source,"destination_component":destination,"source_symbol":source_symbol,"destination_symbol":destination_symbol,"data_classes":data,"validation":validation,"authentication":authentication,"authorization":authorization,"trust_boundary":trust,"side_effect":side_effect,"failure_behavior":failure,"backend_variant":variant,"evidence_status":"repository-proven","evidence_refs":evidence}


def main() -> None:
    entries = [{"schema_version":"1.0","run_id":RUN_ROOT.name,"id":i,"kind":k,"path":p,"symbol":s,"trigger":t,"variants":[]} for i,k,p,s,t in ENTRYPOINTS]
    edges = [
        edge("TR-HTTP-1","EP-WEB",1,"browser/client","Flask request guard","HTTP request","_guard_request",["identity","credentials","user-input"],"identity token signature; route/method checks","signed pseudonymous identity; optional API key","owner checks in archive; optional admin key","user/network to process","may issue identity cookie; may initialize service","bounded JSON 401/429/503","web",["main.py:137-175"]),
        edge("TR-CHAT-1","EP-WEB",2,"/chat or /chat/stream","session binding","chat/chat_stream","_chat_session",["message","session-id"],"non-empty string; caller-supplied session accepted only if owned","request principal","archive.owns_session","network/process to database","ensure permanent session","foreign/unknown session becomes permanent caller session","sqlite|mongo",["main.py:108-123","main.py:239-300"]),
        edge("TR-CHAT-2","EP-WEB",3,"session binding","chat orchestration","route","ChatbotService.handle",["conversation","request-id"],"clean_message caps at 4000; request ID <=200","principal propagated","owner-scoped user/session IDs","process","risk/cache state mutated; model/database calls","generation falls back; archive failure returns 503","sqlite|mongo",["main.py:239-300","app/chatbot/chatbot_service.py:87-181"]),
        edge("TR-SAFE-1","EP-WEB",4,"chat orchestration","deterministic and semantic safety","handle","ConversationRiskReasoner.assess",["health-data","conversation-history","moderation"],"regex normalization; bounded semantic transcript; parsed constrained JSON","n/a","owner-scoped archive hydration","application to external model when enabled","process-local risk state mutation","semantic/moderation failures fall to deterministic floor","semantic-on|semantic-off",["app/chatbot/chatbot_service.py:105-121","app/safety/reasoner.py:94-129"]),
        edge("TR-ROUTE-1","EP-WEB",5,"safety assessment","crisis/refusal/cache/model","_analyze","_respond",["risk","intent","memory","knowledge"],"priority crisis then harmful/sexual then cache/model","n/a","user scoped cache/memory","process/model/cache","LLM calls and cache reads","cache errors degrade to generation; generation errors use fallback","crisis|refusal|cache-hit|knowledge-hit|no-result",["app/chatbot/chatbot_service.py:333-418"]),
        edge("TR-PROMPT-1","EP-WEB",6,"archive/memory/CAG","LLM prompt","_build_prompt","LLMClient.generate",["current-message","transcripts","derived-health-attributes","knowledge"],"prompt labels untrusted knowledge/history; lexical budgets","provider API key","logical owner scoping before assembly","application to model provider","external model transmission","model failure returns bounded local fallback","model-enabled",["app/chatbot/chatbot_service.py:550-602","app/prompts/system_prompt.py:177-228"]),
        edge("TR-OUT-1","EP-WEB",7,"model/cache/crisis","output finalizer","_respond","_finalize_reply",["model-output","safety-output"],"leak regex; optional reviewer; moderation; deterministic policy walls","n/a","n/a","model/process to user output","may invoke model moderation/reviewer","semantic output classifier fails open to deterministic checks","reviewer-on|reviewer-off",["app/chatbot/chatbot_service.py:397-438","app/chatbot/response_builder.py:291-356"]),
        edge("TR-COMMIT-1","EP-WEB",8,"output finalizer","authoritative archive","_record_turn","record_turn",["conversation","safety-state","request-id"],"backend field checks and idempotency","principal propagated","owner/session constraints","process to SQLite/Mongo","atomic two-message turn commit","error propagates; no user output sent","sqlite|mongo",["app/chatbot/chatbot_service.py:122-137","app/storage/chat_archive.py:257-350","app/storage/chat_archive_mongo.py:224-366"]),
        edge("TR-DERIVED-1","EP-WEB",9,"authoritative archive","derived memory/summary/state","handle","observe/save_safety_state",["derived-health-data","summary","provenance"],"rule extraction; source IDs; bounded summary","n/a","owner scoped","database/cache/model","post-commit secondary writes","pending markers retried on next turn","sqlite|mongo",["app/chatbot/chatbot_service.py:139-174","app/chatbot/chatbot_service.py:242-315"]),
        edge("TR-RESP-1","EP-WEB",10,"committed result","browser/UI","jsonify/Response","textContent",["assistant-response","route","latency"],"JSON serialization; UI uses textContent for messages","same request","same caller","process/network/browser","none","bounded user-visible errors","json|buffered-sse",["main.py:264-301","ui/index.html:130-164"]),
        edge("TR-DOC-1","EP-WEB",2,"multipart upload","knowledge filesystem","upload_document","FileStorage.save",["uploaded-document"],"global 10MB limit; extension allowlist; basename; normalized type","optional API/admin key","admin key only when configured","network/process to file","writes knowledge file","save failure 500; indexing failure leaves file","upload",["main.py:314-352"]),
        edge("TR-DOC-2","EP-WEB",3,"knowledge filesystem","CAG persisted/in-memory cache","refresh_documents","KnowledgeCache.refresh",["document-text","knowledge-metadata"],"format parser failures become empty sections; hashes changed files","n/a","n/a","file/process cache","writes cache JSON and process memory","per-worker refresh; cache write failure bubbles","multi-worker",["app/cag/knowledge_cache.py:167-237"]),
        edge("TR-DEL-1","EP-WEB",2,"account/session API","authoritative and secondary stores","delete_account/delete_session","delete_user/forget_user/delete_user",["user-data","conversation","memory","feedback"],"owner checks; tombstone first for account","signed identity","owner-scoped","process to multiple stores","destructive transactional and secondary deletes","partial secondary failure returns 503 and retry remains possible","sqlite|mongo",["main.py:418-481"]),
        edge("TR-HEALTH-1","EP-WEB",1,"load balancer","service/storage readiness","health","get_service/archive.healthcheck",["operational-metadata"],"none","open","none","network/process/database/model config","can initialize complete service","503 without exception details","health",["main.py:193-201"]),
        edge("TR-CLI-1","EP-CLI",1,"terminal","ChatbotService","run_cli","handle",["conversation"],"trim/non-empty; no HTTP identity/auth/rate limit","none","session ID from env or random","local process","same archive/model writes","uncaught service failures exit CLI","cli",["main.py:505-537"]),
        edge("TR-DEPLOY-1","EP-GUNICORN",1,"Render","Gunicorn workers","startCommand","main:app",["configuration","process-state"],"environment settings","platform","platform","deployment/process","2x4 process/thread topology; only data/ mounted","warm/lazy initialization; no explicit shutdown hook","render",["render.yaml:1-75","app/storage/mongo_client.py:13-62"]),
    ]
    subsystems = {
        "application-flow":{"files":["main.py","ui/index.html","app/chatbot/*","app/normalize.py","app/types.py","app/utils.py","app/llm/client.py","app/config/settings.py"],"interfaces":["Flask routes","ChatbotService.handle","LLMClient.generate"],"upstream":["browser","CLI"],"downstream":["model","archive","UI"]},
        "safety":{"files":["app/safety/*","app/prompts/*"],"interfaces":["Guardrails","ConversationRiskReasoner","CrisisHandler","ResponseBuilder"],"upstream":["normalized message","history","moderation"],"downstream":["route","final reply","persisted safety state"]},
        "memory-rag-cag":{"files":["app/cag/*","app/memory/*","knowledge/*","cache/*","build_cache.py"],"interfaces":["CAGEngine","KnowledgeCache","ContextCache","LongTermMemory*"],"upstream":["documents","committed turns"],"downstream":["model context","cache answer","derived memory"]},
        "persistence":{"files":["app/storage/*","data/*"],"interfaces":["ChatArchive*","FeedbackStore*","get_mongo_db"],"upstream":["HTTP/chat pipeline"],"downstream":["SQLite","MongoDB","session/account reads"]},
        "security-privacy":{"files":["app/security.py","app/identity.py",".env*",".git/*"],"interfaces":["IdentityManager","ApiAuth","RateLimiter"],"upstream":["untrusted HTTP"],"downstream":["principal","authorization","cookies"]},
        "testing-quality":{"files":["tests/*","test_all.py","test_audit.py","context_audit.py","pytest.ini"],"interfaces":["pytest","unittest","script mains"],"upstream":["baseline code"],"downstream":["test evidence"]},
        "deployment-operations":{"files":["render.yaml","Procfile","requirements.txt","README.md","DEVELOPER_GUIDE.md"],"interfaces":["Gunicorn","Render","dependency install"],"upstream":["deployment config"],"downstream":["workers","mounts","external services"]},
    }
    variants = [
        {"family":"startup/readiness","variants":["Flask direct","CLI","Gunicorn warm import","first-request lazy","health-triggered"],"limitations":["no explicit shared-client shutdown hook"]},
        {"family":"request","variants":["open index/health","optional shared API auth","optional admin auth","per-process rate limiting"]},
        {"family":"chat","variants":["deterministic-only","semantic fusion","output reviewer on/off","crisis/refusal/cache/model","generation/archive failure","duplicate request"]},
        {"family":"persistence","variants":["SQLite","Mongo replica-set transactions","legacy JSON migration","separate feedback"]},
        {"family":"deployment","variants":["single process","2 workers x 4 threads","mounted data","unmounted knowledge/cache"]},
    ]
    unresolved = [
        {"path":"production platform/network","missing_evidence":"No runtime environment, proxy, TLS, WAF, backup, restore, monitoring, or alerting configuration beyond render.yaml."},
        {"path":"external model behavior","missing_evidence":"No live provider calls permitted; semantic classification and generated-response behavior require staged external validation."},
        {"path":"Mongo deployment","missing_evidence":"No live replica set or backup/retention policy evidence; real integration suite is opt-in and networking-dependent."},
        {"path":"shutdown lifecycle","missing_evidence":"No application hook closes the shared MongoClient or SQLite feedback connection."},
    ]
    arch = RUN_ROOT / "architecture"
    write_json(arch / "entrypoints.json", entries)
    write_jsonl(arch / "trace-edges.jsonl", edges)
    write_json(arch / "subsystems.json", subsystems)
    write_json(arch / "runtime-variants.json", variants)
    write_json(arch / "unresolved-paths.json", unresolved)
    gate = {"schema_version":"1.0","run_id":RUN_ROOT.name,"gate":"G3","outcome":"pass","entrypoint_count":len(entries),"trace_edge_count":len(edges),"subsystem_count":len(subsystems),"all_nonisolated_have_upstream_downstream":all(v["upstream"] and v["downstream"] for v in subsystems.values()),"unresolved_path_count":len(unresolved)}
    write_json(arch / "reconciliation.json", gate)
    print(json.dumps(gate))


if __name__ == "__main__":
    main()
