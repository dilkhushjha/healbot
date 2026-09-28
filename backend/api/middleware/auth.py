"""
auth.py — API key authentication middleware.

Accepts the key two ways:
  1. Header:  Authorization: Bearer hb_live_...  (standard fetch calls)
  2. Query:   ?api_key=hb_live_...               (EventSource/SSE — browsers
                                                  cannot send headers with EventSource)

Public routes: /health, /docs, /openapi.json, /auth/register
OPTIONS preflight always passes through (required for CORS to work).
"""
from core.database import get_auth_context_by_key
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse
import sys
import os

# ── sys.path fix ──────────────────────────────────────────────────────────────
_BACKEND_DIR = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
# ─────────────────────────────────────────────────────────────────────────────


PUBLIC_PATHS = {"/health", "/meta", "/docs", "/openapi.json", "/redoc",
                "/auth/register", "/auth/login"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Always let OPTIONS through — these are CORS preflight requests
        if request.method == "OPTIONS":
            return await call_next(request)

        # Public routes need no auth
        if request.url.path in PUBLIC_PATHS or request.url.path.startswith("/static"):
            return await call_next(request)

        # 1. Authorization header (standard)
        api_key = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            api_key = auth_header[7:].strip()

        # 2. Query param fallback (EventSource cannot send headers)
        if not api_key:
            api_key = request.query_params.get("api_key", "").strip()

        if not api_key:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": (
                        "Missing API key. Send header: Authorization: Bearer hb_live_... "
                        "or query param: ?api_key=hb_live_..."
                    )
                },
            )

        auth_context = get_auth_context_by_key(api_key)
        if not auth_context:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or inactive API key"},
            )

        request.state.tenant = auth_context["tenant"]
        request.state.user = auth_context["user"]
        request.state.role = auth_context["role"]
        return await call_next(request)
