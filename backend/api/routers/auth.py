"""
auth.py router — Tenant registration and API key management.
POST /auth/register   → create tenant + first API key
POST /auth/keys       → generate additional key
GET  /auth/keys       → list keys
DELETE /auth/keys/{k} → revoke a key
"""
from core.database import audit_events, engine, tenant_users, tenants, api_keys, now
from sqlalchemy import select, update
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request
from pathlib import Path
from api.permissions import TEAM_ADMIN_ROLES, VALID_ROLES, permissions_for, require_role
import secrets
import uuid
import json
import sys
import os

# ── sys.path fix ──────────────────────────────────────────────────────────────
_BACKEND_DIR = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
# ─────────────────────────────────────────────────────────────────────────────


router = APIRouter(prefix="/auth", tags=["Auth"])


class RegisterRequest(BaseModel):
    name:  str
    email: str
    tier:  str = "free"


class KeyRequest(BaseModel):
    name: str = "default"


class InviteUserRequest(BaseModel):
    email: str
    name: str = ""
    role: str = "qa_engineer"


class LocalProfileRequest(BaseModel):
    api_url: str = "http://localhost:8000"
    dashboard_url: str = ""


def local_profile_path() -> Path:
    override = os.environ.get("HEALBOT_PROFILE")
    if override:
        return Path(override).expanduser()

    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Healbot" / "profile.json"

    return Path.home() / ".healbot" / "profile.json"


def _audit(conn, tenant_id: str, actor: str, action: str, target: str = "", details: dict | None = None):
    conn.execute(audit_events.insert().values(
        id=str(uuid.uuid4())[:12],
        tenant_id=tenant_id,
        actor=actor,
        action=action,
        target=target,
        details=details or {},
        created_at=now(),
    ))


def _actor_email(request: Request) -> str:
    user = getattr(request.state, "user", {}) or {}
    tenant = getattr(request.state, "tenant", {}) or {}
    return user.get("email") or tenant.get("email") or "system"


def _ensure_owner_user(conn, tenant: dict):
    existing = conn.execute(
        select(tenant_users).where(
            tenant_users.c.tenant_id == tenant["id"],
            tenant_users.c.email == tenant["email"],
        )
    ).mappings().first()
    if existing:
        return existing

    user_id = str(uuid.uuid4())[:8]
    conn.execute(tenant_users.insert().values(
        id=user_id,
        tenant_id=tenant["id"],
        email=tenant["email"],
        name=tenant["name"],
        role="owner",
        status="active",
        created_at=now(),
        updated_at=now(),
        is_active=True,
    ))
    return conn.execute(
        select(tenant_users).where(tenant_users.c.id == user_id)
    ).mappings().first()


@router.post("/register")
def register(req: RegisterRequest):
    tenant_id = str(uuid.uuid4())[:8]
    key = f"hb_live_{secrets.token_urlsafe(24)}"

    with engine.begin() as conn:
        existing = conn.execute(
            select(tenants).where(tenants.c.email == req.email)
        ).first()
        if existing:
            raise HTTPException(400, f"Email {req.email} already registered")

        conn.execute(tenants.insert().values(
            id=tenant_id, name=req.name, email=req.email,
            tier=req.tier, created_at=now(), is_active=True,
        ))
        conn.execute(api_keys.insert().values(
            key=key, tenant_id=tenant_id, name="default",
            created_at=now(), is_active=True,
        ))
        conn.execute(tenant_users.insert().values(
            id=str(uuid.uuid4())[:8],
            tenant_id=tenant_id,
            email=req.email,
            name=req.name,
            role="owner",
            status="active",
            created_at=now(),
            updated_at=now(),
            is_active=True,
        ))
        _audit(conn, tenant_id, req.email, "tenant.registered", tenant_id, {"tier": req.tier})

    return {
        "tenant_id": tenant_id,
        "api_key":   key,
        "tier":      req.tier,
        "message":   "Keep your API key safe. Send it as: Authorization: Bearer <key>",
    }


@router.post("/local-profile")
def persist_local_profile(req: LocalProfileRequest, request: Request):
    """Persist this authenticated API key for local SDK and pytest runners."""
    auth_header = request.headers.get("Authorization", "")
    api_key = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    if not api_key:
        api_key = request.query_params.get("api_key", "").strip()
    if not api_key:
        raise HTTPException(401, "Missing API key")

    path = local_profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "api_key": api_key,
        "api_url": req.api_url.rstrip("/"),
        "dashboard_url": req.dashboard_url.rstrip("/") if req.dashboard_url else "",
        "tenant_id": request.state.tenant["id"],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with engine.begin() as conn:
        _audit(
            conn,
            request.state.tenant["id"],
            _actor_email(request),
            "sdk_profile.saved",
            str(path),
            {"api_url": payload["api_url"]},
        )
    return {
        "status": "saved",
        "profile_path": str(path),
        "api_url": payload["api_url"],
    }


@router.get("/me")
def me(request: Request):
    tenant = request.state.tenant
    role = getattr(request.state, "role", "viewer")
    with engine.begin() as conn:
        _ensure_owner_user(conn, tenant)
    actor = getattr(request.state, "user", None) or {}
    return {
        "tenant": {
            "id": tenant["id"],
            "name": tenant["name"],
            "email": tenant["email"],
            "tier": tenant["tier"],
        },
        "user": dict(actor),
        "role": role,
        "permissions": permissions_for(role),
        "roles": sorted(VALID_ROLES),
    }


@router.get("/users")
def list_users(request: Request):
    tenant = request.state.tenant
    with engine.begin() as conn:
        _ensure_owner_user(conn, tenant)
        rows = conn.execute(
            select(tenant_users)
            .where(tenant_users.c.tenant_id == tenant["id"])
            .order_by(tenant_users.c.created_at.asc())
        ).mappings().all()
    return [dict(row) for row in rows]


@router.post("/users")
def invite_user(req: InviteUserRequest, request: Request):
    require_role(request, TEAM_ADMIN_ROLES)
    tenant = request.state.tenant
    email = req.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(422, "A valid email is required")
    if req.role not in VALID_ROLES or req.role == "owner":
        raise HTTPException(422, "Role must be one of: admin, qa_lead, qa_engineer, viewer")

    with engine.begin() as conn:
        _ensure_owner_user(conn, tenant)
        existing = conn.execute(
            select(tenant_users).where(
                tenant_users.c.tenant_id == tenant["id"],
                tenant_users.c.email == email,
            )
        ).mappings().first()
        if existing:
            conn.execute(
                update(tenant_users)
                .where(tenant_users.c.id == existing["id"])
                .values(
                    name=req.name.strip() or existing["name"],
                    role=req.role,
                    status="active" if existing["status"] == "active" else "invited",
                    updated_at=now(),
                    is_active=True,
                )
            )
            user_id = existing["id"]
            action = "tenant_user.updated"
        else:
            user_id = str(uuid.uuid4())[:8]
            conn.execute(tenant_users.insert().values(
                id=user_id,
                tenant_id=tenant["id"],
                email=email,
                name=req.name.strip() or email.split("@")[0],
                role=req.role,
                status="invited",
                created_at=now(),
                updated_at=now(),
                is_active=True,
            ))
            action = "tenant_user.invited"

        _audit(conn, tenant["id"], _actor_email(request), action, email, {"role": req.role})
        row = conn.execute(
            select(tenant_users).where(tenant_users.c.id == user_id)
        ).mappings().first()
    return dict(row)


@router.delete("/users/{user_id}")
def deactivate_user(user_id: str, request: Request):
    require_role(request, TEAM_ADMIN_ROLES)
    tenant = request.state.tenant
    with engine.begin() as conn:
        _ensure_owner_user(conn, tenant)
        user = conn.execute(
            select(tenant_users).where(
                tenant_users.c.id == user_id,
                tenant_users.c.tenant_id == tenant["id"],
            )
        ).mappings().first()
        if not user:
            raise HTTPException(404, "User not found")
        if user["role"] == "owner":
            raise HTTPException(400, "Owner user cannot be deactivated")
        conn.execute(
            update(tenant_users)
            .where(tenant_users.c.id == user_id)
            .values(status="disabled", is_active=False, updated_at=now())
        )
        _audit(conn, tenant["id"], _actor_email(request), "tenant_user.deactivated", user["email"])
    return {"status": "deactivated", "user_id": user_id}


@router.post("/keys")
def create_key(req: KeyRequest, request: Request):
    require_role(request, TEAM_ADMIN_ROLES)
    tenant = request.state.tenant
    key = f"hb_live_{secrets.token_urlsafe(24)}"
    with engine.begin() as conn:
        conn.execute(api_keys.insert().values(
            key=key, tenant_id=tenant["id"], name=req.name,
            created_at=now(), is_active=True,
        ))
        _audit(conn, tenant["id"], _actor_email(request), "api_key.created", req.name, {"prefix": key[:12]})
    return {"api_key": key, "name": req.name}


@router.get("/keys")
def list_keys(request: Request):
    require_role(request, TEAM_ADMIN_ROLES)
    tenant = request.state.tenant
    with engine.connect() as conn:
        rows = conn.execute(
            select(api_keys).where(api_keys.c.tenant_id == tenant["id"])
        ).mappings().all()
    return [
        {"key": r["key"], "name": r["name"],
         "created_at": r["created_at"], "last_used_at": r["last_used_at"],
         "is_active": r["is_active"]}
        for r in rows
    ]


@router.delete("/keys/{key_prefix}")
def revoke_key(key_prefix: str, request: Request):
    require_role(request, TEAM_ADMIN_ROLES)
    tenant = request.state.tenant
    with engine.begin() as conn:
        rows = conn.execute(
            select(api_keys).where(api_keys.c.tenant_id == tenant["id"])
        ).mappings().all()
        matched = [r for r in rows if r["key"].startswith(key_prefix)]
        if not matched:
            raise HTTPException(404, "Key not found")
        conn.execute(
            update(api_keys).where(api_keys.c.key == matched[0]["key"])
            .values(is_active=False)
        )
        _audit(conn, tenant["id"], _actor_email(request), "api_key.revoked", key_prefix)
    return {"status": "revoked"}


@router.get("/audit")
def list_audit_events(request: Request, limit: int = 50):
    require_role(request, TEAM_ADMIN_ROLES)
    tenant = request.state.tenant
    with engine.connect() as conn:
        rows = conn.execute(
            select(audit_events)
            .where(audit_events.c.tenant_id == tenant["id"])
            .order_by(audit_events.c.created_at.desc())
            .limit(limit)
        ).mappings().all()
    return [dict(row) for row in rows]
