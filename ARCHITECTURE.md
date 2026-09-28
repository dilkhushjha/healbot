# Healbot Architecture

Healbot is organized as a product platform with four boundaries:

1. **Frontend** - QA workflow UI, live run theatre, trust/evidence, setup, team settings.
2. **Backend API** - authenticated tenant API, run ingestion, analytics, projects, runners, and MCP discovery.
3. **SDK / Adapters** - plug-and-play framework hooks for Selenium, Playwright, Robot, and pytest.
4. **MCP Surface** - discoverable tool contracts for future agents, IDE plugins, CI bots, and hosted integrations.

## Backend Layers

- `backend/api/routers`: HTTP resources only. Routers validate input and delegate work.
- `backend/core`: persistence, queueing, tenancy, permissions, runner capability primitives.
- `backend/healing`: selector repair, DOM scoring, intent, LLM, and vision reasoning.
- `backend/services`: cross-router product services such as runtime health.
- `backend/mcp`: stable integration contracts that map product capabilities to tools.
- `backend/sdk`: installable customer-facing Python package.

## LLM Provider Boundary

- `backend/healing/llm_reasoner.py` is the stable facade used by the healing engine.
- `backend/healing/llm_providers.py` owns provider-specific request and response formats.
- Supported selector-healing providers are `ollama`, `openai`, `openai-compatible`, `anthropic`, and `gemini`.
- Switching providers should require config changes only: `HEALBOT_LLM_PROVIDER`, a model, and the matching API key for hosted providers.
- The healing engine receives the same normalized selector result regardless of provider.

## Frontend Layers

- `frontend/src/features/dashboard`: product dashboard feature module.
- `api.js`: backend client and persistence helpers.
- `Dashboard.jsx`: workflow composition and screen state.
- `dashboard.css`: product styling and responsive behavior.

## Scaling Direction

- Move SQLite to Postgres with the same table boundaries.
- Move in-process `_sessions` and `RunContext` to Redis/pub-sub for multi-instance streaming.
- Move artifacts to object storage and keep only URLs in SQL.
- Promote `backend/mcp/registry.py` into a real MCP server package when external tools need direct tool execution.
- Keep SDK config file based, with dashboard-created keys and project/environment IDs.

## Product Workflow

The UI should lead with the QA workflow:

Run -> Observe -> Heal -> Trust Evidence -> Share Report

Internal plumbing such as API keys, runner capabilities, and LLM health should be available, but not dominate the first screen.
