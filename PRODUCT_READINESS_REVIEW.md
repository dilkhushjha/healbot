# Healbot Product Readiness Review

Date: 2026-07-28

## Current Rating

Overall: 6.8 / 10

Healbot is no longer just an idea demo. It has a usable product spine: tenant-aware API keys, SDK profile persistence, projects, environments, runner capability records, batch/session ingestion, live SSE streaming, healing evidence, LLM provider abstraction, and a real dashboard shell.

It is not yet an industry-grade SaaS product. The remaining gap is mostly operational hardening: durable queues, horizontally scalable live streams, production auth, migrations, artifact storage, observability, and clean packaging.

## Strengths

- Clear product niche: self-healing automation for QA engineers.
- Works with existing frameworks through SDK/adapters rather than asking teams to rewrite tests.
- Captures healing evidence, selectors, strategies, screenshots, and run state.
- Has multi-tenant data boundaries and role-aware API surfaces.
- LLM selector healing is now provider-swappable across Ollama, OpenAI-compatible APIs, Anthropic, and Gemini.
- Dashboard now presents a stakeholder-facing control plane instead of an internal debugging console.

## Scalability Gaps

- Queueing is in-process with `queue.Queue`; jobs are lost on restart and cannot be shared across API replicas.
- Live sessions and run contexts are in-memory; SSE only works reliably when the user lands on the same process that owns the run.
- SQLite is fine for local use, but production needs Postgres plus migrations.
- Screenshots/artifacts are local files/base64 payloads; cloud use needs object storage and signed URLs.
- API keys are stored directly; production should store hashed key material and show only prefixes.
- The SDK streams full screenshot frames synchronously; long suites need throttling, compression, retry/backoff, and async buffering.
- Observability is still basic; production needs structured logs, traces, metrics, and alerting.
- Multi-platform runner records exist, but real cloud/device execution is still a planned integration boundary.

## Target Architecture

- API: FastAPI behind an API gateway or load balancer.
- Database: Postgres with Alembic migrations.
- Queue: Redis/RQ, Celery, Dramatiq, or a cloud queue.
- Live events: Redis pub/sub, managed WebSocket/SSE fanout, or event broker.
- Artifacts: S3-compatible object storage with tenant-scoped paths and signed URLs.
- Runners: local SDK runners now, cloud runner providers later through capability adapters.
- LLM: keep `backend/healing/llm_providers.py` as the only provider-specific boundary.

## Next Product Readiness Score Targets

- 7.5 / 10: durable queue, hashed API keys, Alembic migrations, object storage abstraction.
- 8.2 / 10: Redis-backed live events, multi-replica API readiness, SDK retry/backoff, signed artifacts.
- 9.0 / 10: billing, org/user lifecycle, cloud runners, enterprise audit/export, deployable infrastructure templates.
