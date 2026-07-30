# Soulene AI 💛

A warm, production-grade **mental-health companion** built on **Cache-Augmented Generation (CAG)**.

Not a general assistant — Soulene supports emotional wellbeing: stress, anxiety, low mood,
burnout, loneliness, motivation, confidence, relationships, work/student stress, overthinking,
sleep, habits, self-care and personal growth.

```
You : mujhe aaj thoda low feel ho raha hai
Bot : Kabhi kabhi aise din aate hain jab sab kuch thoda heavy lagta hai.
      Kya koi specific wajah hai jo aaj zyada low feel karwa rahi hai?

You : python = hello correct hai?
Bot : Arre yaar, coding ke mamle mein main thodi si out of league hoon! 😊
      Lekin batao, koi aur baat hai jo dimag pe hai?
```

---

## Why CAG instead of RAG

The knowledge corpus is ~8.6k tokens, so it fits entirely in one context window. There is
**no vector database and no embedding model** in the request path.

| | RAG | **CAG (this build)** |
|---|---|---|
| Retrieval | embed query → FAISS top-k | knowledge preloaded in memory |
| Hot path | ~200 ms embedding | **~0.5 ms** |
| Deps | faiss + sentence-transformers + torch (~2 GB) | none |
| Accuracy | top-4 chunks only | full corpus visible |
| Repeat question | full LLM call | **0 LLM calls** (response cache) |

Above `KNOWLEDGE_TOKEN_BUDGET` the cache automatically narrows using an in-memory BM25-lite
lexical index — still no embeddings.

## Highlights

- **Cache-first pipeline** — response cache → knowledge cache → single LLM call.
- **Human tone** — 2–4 sentences, warm, gently playful, natural emojis (never during distress),
  English / Hindi / Hinglish matching, varied wording every turn.
- **Lightweight prompt** — ~200-token core prompt; behaviour lives in code, not a wall of rules.
- **Four separated memory layers** — full chat archive · ≤50 profile memories · isolated
  feedback DB · knowledge cache. *Storage ≠ what the model sees.*
- **Graded safety** — `SAFE → EMOTIONAL_DISTRESS → SELF_HARM_CONCERN → IMMINENT_SELF_HARM →
  HARM_TO_OTHERS → ABUSE_OR_DANGER`; crisis outranks everything, no humour.
- **Hardened** — injection/extraction detection, document cache-poisoning defence, memory
  poisoning limits, cross-user isolation, deterministic prompt-leak scrub.
- **Domain boundary** — off-topic asks get a warm redirect, enforced deterministically.
- **Auto-updating knowledge** — per-document hashing detects new/changed/removed files and
  invalidates stale cached answers.
- **Real streaming** — SSE token streaming.
- **Legacy parity** — medication handling, repeat-frustration, diagnosis humility, competitor-app
  blocking, deterministic helpline numbers, session strict-mode and the 7 response families were
  all ported from the original `project/` bot (see the guide's parity table).
- **Emotionally attuned** — happy/excited get celebration and matched energy; sad, angry, anxious,
  lonely and confused each get their own tone; grief and trauma permanently disable humour and emojis.
- **Production security** — optional API-key auth, a separate admin key for knowledge uploads,
  and per-caller rate limiting.
- **Obfuscation-resistant guardrails** — Unicode homoglyphs, zero-width splits, leetspeak,
  letter-spacing and Hindi/Hinglish phrasings of injection and self-harm are all folded before
  matching (`app/normalize.py`).
- **254 automated tests** in ~10 s, no network required.

---

## Quick start

```bash
cd rag_implementation
python -m pip install -r requirements.txt
cp .env.example .env          # add OPENAI_API_KEY
python build_cache.py         # build the knowledge cache (optional; auto on boot)
python main.py                # http://localhost:5000
python main.py --cli          # terminal chat (/stats, /clear, /quit)
```

Add knowledge by dropping files into `knowledge/<type>/` (`.pdf .docx .xlsx .csv .txt .md`)
and running `python build_cache.py` — or upload at runtime via `POST /documents`.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | health check |
| `GET` | `/metrics` | cache stats + hit rate |
| `POST` | `/chat` | JSON reply |
| `POST` | `/chat/stream` | SSE stream |
| `GET` `POST` | `/documents` | list / upload knowledge |
| `DELETE` | `/documents/<name>` | remove document |
| `POST` | `/feedback` | submit feedback (isolated store) |

## Tests

```bash
python -m unittest discover -s tests -p "test_*.py"   # 254 tests, ~10s
python -m tests.smoke_live                             # live conversational check
python -m tests.smoke_staging                          # live staging gate (11 assertions)
```

## Deploy to Render

`render.yaml` is complete: push to GitHub → **New → Blueprint** → set `OPENAI_API_KEY` → deploy.
Includes gunicorn config, `/health` check, and a 1 GB persistent disk for `data/`.

## Documentation

See **[DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md)** for architecture, CAG cache lifecycle,
ingestion pipeline, memory layers, DB schema, API reference, deployment, security review
and troubleshooting.

> ⚠️ **Before public exposure:** set `API_KEY` and `ADMIN_API_KEY` (auth is off by default for
> local dev) and a non-zero `RATE_LIMIT_PER_MINUTE`. Rotate your OpenAI key if it was ever
> committed. Note `user_id` still comes from the request body — for real multi-tenancy, derive
> it from a per-user token instead.
