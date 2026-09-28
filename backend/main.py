"""Healbot API entrypoint."""
import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from api.middleware.auth import AuthMiddleware
from api.routers import analytics, auth, batches, heal, intent_maps, mcp, projects, runners, sessions, stream
from core.config import (
    ALLOW_CREDENTIALS,
    ALLOWED_ORIGINS,
    API_VERSION,
    PRODUCT_NAME,
    PRODUCT_TAGLINE,
    TIER_LIMITS,
)
from services.runtime_status import product_meta


app = FastAPI(
    title=f"{PRODUCT_NAME} API",
    description=PRODUCT_TAGLINE,
    version=API_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)

app.include_router(auth.router)
app.include_router(batches.router)
app.include_router(projects.router)
app.include_router(runners.router)
app.include_router(analytics.router)
app.include_router(stream.router)
app.include_router(intent_maps.router)
app.include_router(heal.router)
app.include_router(sessions.router)
app.include_router(mcp.router)


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok", **product_meta()}


@app.get("/meta")
def meta():
    return product_meta()


@app.get("/tiers")
def tiers():
    return TIER_LIMITS
