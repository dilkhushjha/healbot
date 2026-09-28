# HealBot SaaS — AI Self-Healing Automation Platform

## Folder Structure

```
healbot_saas/
├── backend/
│   ├── api/
│   │   ├── middleware/
│   │   │   └── auth.py              API key auth (Bearer token)
│   │   └── routers/
│   │       ├── auth.py              Tenant registration + key management
│   │       ├── batches.py           Batch submission, queries, reports
│   │       ├── analytics.py         Flakiness, trends, selector breakage
│   │       ├── stream.py            SSE: per-run + per-batch live streams
│   │       └── intent_maps.py       Client custom keyword→intent maps
│   │
│   ├── core/
│   │   ├── config.py                All tunable constants + env vars
│   │   ├── database.py              Multi-tenant SQLAlchemy schema
│   │   ├── batch_scheduler.py       Worker pool, tier enforcement, batch exec
│   │   ├── run_context.py           Per-run isolated log/metric buffer
│   │   └── logger.py               stdout + SSE push
│   │
│   ├── healing/
│   │   ├── healing_engine.py        Pipeline: memory→DOM→LLM→vision→fallback
│   │   ├── dom_healer.py            Keyword confidence scorer
│   │   ├── intent_engine.py         3-tier intent: step > client map > built-in
│   │   ├── learning_engine.py       Per-tenant + global cross-run memory
│   │   ├── llm_reasoner.py          Provider-neutral LLM facade
│   │   ├── llm_providers.py         Ollama/OpenAI/Anthropic/Gemini adapters
│   │   ├── vision_analyzer.py       Ollama llava visual confirmation
│   │   └── vision_capture.py        Screenshots → artifacts/<run_id>/
│   │
│   ├── context/
│   │   └── element_context_extractor.py
│   │
│   ├── sdk/
│   │   └── healbot_sdk.py           Python SDK (pip install)
│   │
│   ├── data/                        Auto-created — healbot_saas.db
│   ├── memory/                      Auto-created — per-tenant + global memory
│   │   ├── global.json              Cross-tenant anonymous heal pool
│   │   └── <tenant_id>.json         Per-tenant isolated memory
│   ├── artifacts/                   Auto-created — screenshots per run
│   │
│   ├── main.py                      FastAPI entrypoint
│   ├── journey_runner.py            Per-script executor
│   ├── journey_schema.py            Journey JSON validator
│   ├── journey.py                   Built-in demo journey
│   ├── driver_factory.py            Selenium Chrome factory
│   └── requirements.txt
│
└── frontend/
    └── src/
        └── Dashboard.jsx            SaaS dashboard (batches, analytics, register)
```

## Quickstart

```bash
cd backend
pip install -r requirements.txt
ollama pull llama3
ollama pull llava     # optional — visual confirmation
uvicorn main:app --reload --port 8000
```

## SDK Usage (recommended for clients)

```python
from sdk.healbot_sdk import HealBotClient

hb = HealBotClient(api_key="hb_live_...", base_url="http://localhost:8000")

# Submit 100 scripts as a batch
scripts = [journey_1, journey_2, ..., journey_100]   # list of journey dicts
batch   = hb.submit_batch("Sprint 42 regression", scripts=scripts)

# Wait for completion (polls every 2s)
result = batch.wait()
print(f"Passed: {result['passed']}  Healed: {result['healed']}  Failed: {result['failed']}")

# Get detailed report
report = batch.report()
print(report["strategy_breakdown"])   # {"dom": 45, "llm": 12, "memory": 38}
print(report["heal_rate_pct"])        # 91.2

# Analytics
print(hb.analytics())
print(hb.flakiness())
```

## REST API Reference

### Auth
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/register` | Create tenant + first API key |
| POST | `/auth/keys` | Generate additional key |
| GET  | `/auth/keys` | List all keys |
| DELETE | `/auth/keys/{prefix}` | Revoke a key |

### Batches
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/batches` | Submit batch of scripts |
| GET  | `/batches` | List batches |
| GET  | `/batches/{id}` | Batch + runs summary |
| GET  | `/batches/{id}/runs` | All script runs |
| GET  | `/batches/{id}/report` | Full analytics report |

### Analytics
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/analytics/overview` | Heal rate, strategy breakdown, 14-day trend |
| GET | `/analytics/flakiness` | Flaky scripts ranked by fail rate |
| GET | `/analytics/selectors` | Most broken selectors |
| GET | `/analytics/usage` | Daily usage vs tier limits |

### Streaming
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/stream/{run_id}` | SSE: live logs + metrics for a run |
| GET | `/stream/batch/{id}` | SSE: batch progress counter |

### Config
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/set-ollama` | Override Ollama model/URL |
| POST | `/intent-maps` | Register custom intent keywords |
| GET  | `/intent-maps` | Get current intent map |
| GET  | `/tiers` | View tier limits |

## Batch Submission Payload

```json
{
  "name": "Sprint 42 regression",
  "project_id": "proj_abc",
  "scripts": [
    {
      "name": "Login flow",
      "client_id": "acme",
      "steps": [
        {
          "id": "login", "description": "Click login",
          "url": "https://myapp.com/login",
          "action": "click",
          "selector": "//button[@id='login-btn']",
          "value": null, "intent": "login submit button", "critical": true
        }
      ]
    }
  ]
}
```

## Cross-Run Learning

Every successful heal is written to two places:
1. `memory/<tenant_id>.json` — tenant-specific memory
2. `memory/global.json` — anonymised cross-tenant pool

On the next run, memory is checked before any DOM/LLM work:
- Tenant memory checked first (exact match)
- Global pool checked second (benefits from other tenants' heals)

This means repeated selector failures get cheaper and faster over time.

## Tier Limits

| Tier | Scripts/day | Workers | History |
|------|-------------|---------|---------|
| Free | 10 | 1 | 7 days |
| Starter | 100 | 2 | 30 days |
| Pro | 1,000 | 4 | 90 days |
| Enterprise | Unlimited | 8 | Forever |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HEALBOT_DB_URL` | SQLite in `data/` | Set to `postgresql://...` for Postgres |
| `HEALBOT_WORKERS` | `8` | Concurrent batch workers |
| `HEALBOT_MAX_QUEUED` | `200` | Max queued batches before 429 |
| `HEALBOT_CONFIDENCE` | `3` | DOM confidence threshold |
| `HEALBOT_LLM_PROVIDER` | `ollama` | Selector-healing LLM provider: `ollama`, `openai`, `openai-compatible`, `anthropic`, `gemini` |
| `HEALBOT_LLM_MODEL` | blank | Optional provider-agnostic model override |
| `OLLAMA_URL` | `http://localhost:11434/api/generate` | Ollama endpoint |
| `OLLAMA_MODEL` | `llama3` | Local text LLM when using Ollama |
| `OPENAI_API_KEY` | blank | Required when `HEALBOT_LLM_PROVIDER=openai` |
| `OPENAI_MODEL` | blank | OpenAI chat model |
| `ANTHROPIC_API_KEY` | blank | Required when `HEALBOT_LLM_PROVIDER=anthropic` |
| `ANTHROPIC_MODEL` | blank | Anthropic messages model |
| `GEMINI_API_KEY` | blank | Required when `HEALBOT_LLM_PROVIDER=gemini` |
| `GEMINI_MODEL` | blank | Gemini generateContent model |
| `LLAVA_MODEL` | `llava` | Vision LLM |
| `HEALBOT_MEMORY` | `./memory` | Memory file directory |
| `HEALBOT_ARTIFACTS` | `./artifacts` | Screenshot directory |
