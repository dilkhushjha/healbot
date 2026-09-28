# Healbot deployment

Healbot can be deployed as a React dashboard and a separate FastAPI API.

## Backend: Render

1. Create a new Blueprint in Render and select this repository. Render reads `render.yaml`.
2. Set `HF_TOKEN` to a Hugging Face user access token and `HF_MODEL` to a model supported by your selected Inference Provider.
3. Set `HEALBOT_ALLOWED_ORIGINS` to the exact dashboard origin, for example `https://your-dashboard.vercel.app` (no trailing slash). For local development, include `http://localhost:3000` as needed.
4. Set `HEALBOT_DB_URL` to a persistent PostgreSQL connection URL. Do not rely on the container's local SQLite file for production data.
5. Deploy and verify `/health`.

The Docker image installs Chromium and ChromeDriver for Selenium. The service must have sufficient memory for browser sessions. The Render free instance may sleep and has resource limits; use a paid instance or a separate browser runner for sustained/parallel execution. Local artifacts and memory files are not durable across container replacement unless mounted on persistent storage.

## Frontend: Vercel

1. Import this repository into Vercel.
2. Set the project root directory to `frontend`.
3. Set `REACT_APP_HEALBOT_API_URL` to the deployed API base URL (for example, `https://your-healbot-api.onrender.com`).
4. Deploy and add the resulting frontend origin to the backend's `HEALBOT_ALLOWED_ORIGINS`, then redeploy the backend.

The React app uses Create React App, so the API URL must use the `REACT_APP_` prefix and is embedded at build time.

## Local setup

Copy `backend/.env.example` to `backend/.env`, fill in the values, and install `backend/requirements.txt`. For the dashboard, copy `frontend/.env.example` to `frontend/.env.local` and set the API URL. Never commit real credentials.
