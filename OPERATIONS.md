# Soulene — Operations Runbook

Scope: what an on-call operator needs. This document is **procedure, not
automation** — the checks it references are implemented and exposed on
`/metrics`, but nothing here pages anyone by itself. Wiring alerts to a paging
system is an external gate (see ISSUE-039 in `issue.md`).

## 1. What to watch

`GET /metrics` (requires `API_KEY`) returns:

| Field | Alarm when | Why it matters |
|---|---|---|
| `operational.counters.safety_classifier_unavailable` | rising | Semantic risk review is failing; safety is running on the deterministic floor |
| `operational.counters.safety_degraded_escalations` | rising | Degraded review is escalating to check-ins — real users are affected |
| `operational.counters.output_blocked_*` | sudden spike | The model is producing harmful output more often, or a prompt change regressed |
| `operational.model_budget.exhausted` | `true` | Provider calls are being refused; replies have degraded to deterministic fallbacks |
| `operational.disk.low_space` | `true` | Durable volume is filling; uploads and commits will start failing |
| `storage_at_rest.encryption_attested` | `false` in production | Startup should have blocked this; investigate configuration drift |
| `provider_transmission.total_calls` | unexpected growth | Cost and data-egress signal |

### Probes (ISSUE-038)

Two separate endpoints, both unauthenticated and both side-effect-free:

| Probe | Question | Behaviour |
|---|---|---|
| `GET /live` | Is the process alive? | Always 200 while the process responds. Reads no configuration, contacts no backend, never initializes the service. Point restart/liveness checks and uptime monitors here. |
| `GET /health` | Should this process get traffic? | Readiness. 200 only when initialization has completed **and** a storage probe succeeds within `READINESS_PROBE_TIMEOUT_SECONDS`. Otherwise 503. Point the platform health check here. |

`/health` never initializes anything. Initialization happens explicitly at
startup (gunicorn import warm-up, or `python main.py`). Readiness bodies carry
`status`, `reason`, and coarse `dependencies` states only — exception detail is
logged, never returned, because the route is open.

Readiness `reason` values:

| `reason` | Meaning | Action |
|---|---|---|
| `awaiting_initialization` | cold start, still inside `READINESS_STARTUP_GRACE_SECONDS` | wait |
| `startup_deadline_exceeded` | grace elapsed and nothing initialized it | check whether warm-up was skipped (`SOULENE_SKIP_WARM`) or the API key is missing |
| `initialization_failed` | startup initialization raised; see logs for the exception type | fix the dependency and **restart** — readiness does not retry initialization by design |
| `storage_failed` / `storage_timeout` | store unreachable or wedged past the probe deadline | treat as a storage incident |

## 2. Incident: safety review degraded

1. Check `safety_classifier_unavailable` and provider status.
2. Confirm replies are still safe: the deterministic floor and the therapeutic
   output wall run regardless, and crisis routing does not depend on the model.
3. If sustained, consider `ENABLE_SEMANTIC_SAFETY=false` to stop retry latency —
   detection becomes deterministic-only, which is degraded but fail-safe.

## 3. Incident: budget exhausted

Replies fall back to deterministic text. Either raise
`MODEL_DAILY_CALL_BUDGET` after confirming spend is legitimate, or investigate
abuse (see `provider_transmission.calls_by_purpose` for which path is consuming).

## 4. Incident: disk filling

1. Check `operational.disk`.
2. Enable retention if approved (`RETENTION_ENABLED=true`) or run one sweep:
   `python main.py --retention`.
3. Knowledge documents and the built cache live on the same volume; large
   uploads are the usual cause.

## 5. Backup and restore

**Not automated. Must be arranged before production.**

- SQLite deployments: the durable mount holds `data/*.sqlite3`. Back up with
  `sqlite3 <db> ".backup <target>"` (safe while running), not a raw file copy.
- Mongo deployments: use the provider's backup facility.
- Restore drill: restore into a scratch environment and start normally, then
  confirm `/health` is 200 and a session reads back. Note that
  `SOULENE_SKIP_WARM=1` suppresses startup initialization, so `/health` stays
  503 (`startup_deadline_exceeded`) until a real request initializes the
  service — `/live` is the liveness signal in that state.
- Retention deletes data permanently; verify backup retention is at least as
  long as the longest configured window before enabling it.

## 6. Deployment invariants

- **One worker.** `--workers 1 --threads 8`. Turn locks, rate-limit buckets and
  caches are process-local; `tests/test_deployment.py` enforces this.
- **All writable paths inside the mount.** `PERSISTENT_ROOT` makes startup fail
  otherwise.
- **Fail-closed startup.** Missing API/admin keys, an unattested encryption
  requirement, or an unattested provider disclosure all prevent boot.

## 7. Dependency locking (ISSUE-037)

Direct dependencies are exactly pinned and the build toolchain is pinned, both
enforced by `tests/test_deployment.py`. **No hash-locked transitive lock file is
committed yet** — generating one needs network access to the package index:

```bash
pip install "pip-tools==7.4.1"
pip-compile --generate-hashes --output-file requirements.lock requirements.txt
# then add --require-hashes to the Render buildCommand
```

Review the generated file before committing. Once present, the existing test
asserts it carries `--hash=sha256:` entries.

## 8. Deployment promotion (ISSUE-040)

`autoDeploy: false`. Nothing reaches users because it landed on main; a human
promotes a **named commit** after this checklist passes. `tests/test_deployment.py`
fails if automatic deployment is re-enabled.

Before promoting:

1. `.github/workflows/gate.yml` is green for that exact commit — it runs the
   hermetic suite on the production interpreter with the production safety
   configuration, from a clean checkout with no local `.env`.
2. No open P0/P1 finding in `issue.md` is regressed by the change.
3. Data-shape changes: `assert_schema_supported` covers the new version, and a
   restore point exists (section 5). Retention is irreversible — confirm
   `RETENTION_ENABLED` is still the intended value.
4. Dependency changes: `requirements.txt` still exactly pinned; note that a
   transitive change is possible without a hash-locked file (section 7).
5. Each attestation env var (`STORAGE_ENCRYPTION_ATTESTED`,
   `PROVIDER_DISCLOSURE_ATTESTED`) still names a person and a date. Startup
   fails without them, so an empty value turns into a failed deploy.
6. Record the previous deployed commit **before** promoting — that is the
   rollback target.

Promote, then within the first minutes:

- `/health` reaches 200 (readiness, section 1). If it stays
  `initialization_failed`, the release is broken — roll back, do not wait.
- `/metrics` counters: no jump in `output_blocked_*` or
  `safety_classifier_unavailable`.

Roll back by promoting the previously recorded commit. Data written by the new
release is **not** reverted by a rollback, which is why step 3 matters.

**Not enforceable from this repository (external gate):** making the gate a
*required* status check on main (branch protection), immutable artifact promotion
rather than rebuild-from-source, staged/canary rollout, and automated rollback
triggers. Until those exist, promotion discipline is procedural.

## 9. Known gaps

No SLOs, no alert routing, no automated backup verification, no load-tested
capacity envelope, and no defined incident ownership. These are recorded as the
ISSUE-039 external gate.
