"""Runner capability catalog for local and cloud-ready execution targets."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
import uuid

from api.permissions import PROJECT_ADMIN_ROLES, require_role
from core.database import audit_events, engine, now, runner_capabilities
from core.runner_capabilities import SYSTEM_CAPABILITIES, capability_health


router = APIRouter(prefix="/runners", tags=["Runners"])


class CapabilityRequest(BaseModel):
    name: str
    provider: str = "local"
    framework: str = "selenium"
    browser: str = "chrome"
    browser_version: str = ""
    platform: str = "web"
    os: str = ""
    device: str = ""
    viewport: str = "desktop"
    region: str = ""
    concurrency: int = 1
    status: str = "available"
    tags: list[str] = Field(default_factory=list)


class CapabilityUpdateRequest(BaseModel):
    name: str | None = None
    provider: str | None = None
    framework: str | None = None
    browser: str | None = None
    browser_version: str | None = None
    platform: str | None = None
    os: str | None = None
    device: str | None = None
    viewport: str | None = None
    region: str | None = None
    concurrency: int | None = None
    status: str | None = None
    tags: list[str] | None = None
    is_active: bool | None = None


def _actor_email(request: Request) -> str:
    user = getattr(request.state, "user", {}) or {}
    tenant = getattr(request.state, "tenant", {}) or {}
    return user.get("email") or tenant.get("email") or "system"


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


def _to_response(row) -> dict:
    item = dict(row)
    item["scope"] = "tenant"
    item["tags"] = item.get("tags") or []
    item["health"] = capability_health(item)
    return item


def _with_health(item: dict) -> dict:
    payload = dict(item)
    payload["health"] = capability_health(payload)
    return payload


@router.get("/capabilities")
def list_capabilities(request: Request):
    tenant = request.state.tenant
    with engine.connect() as conn:
        rows = conn.execute(
            select(runner_capabilities)
            .where(
                runner_capabilities.c.tenant_id == tenant["id"],
                runner_capabilities.c.is_active == True,
            )
            .order_by(runner_capabilities.c.created_at.asc())
        ).mappings().all()
    return [_with_health(item) for item in SYSTEM_CAPABILITIES] + [_to_response(row) for row in rows]


@router.get("/health")
def runner_health(request: Request):
    tenant = request.state.tenant
    with engine.connect() as conn:
        rows = conn.execute(
            select(runner_capabilities)
            .where(
                runner_capabilities.c.tenant_id == tenant["id"],
                runner_capabilities.c.is_active == True,
            )
            .order_by(runner_capabilities.c.created_at.asc())
        ).mappings().all()
    capabilities = [_with_health(item) for item in SYSTEM_CAPABILITIES] + [_to_response(row) for row in rows]
    return {
        "ready": sum(1 for item in capabilities if item["health"]["ready"]),
        "blocked": sum(1 for item in capabilities if not item["health"]["ready"]),
        "capabilities": [
            {
                "id": item["id"],
                "name": item["name"],
                "provider": item["provider"],
                "framework": item["framework"],
                "browser": item["browser"],
                "platform": item["platform"],
                "health": item["health"],
            }
            for item in capabilities
        ],
    }


@router.post("/capabilities")
def create_capability(req: CapabilityRequest, request: Request):
    require_role(request, PROJECT_ADMIN_ROLES)
    tenant = request.state.tenant
    name = req.name.strip()
    if not name:
        raise HTTPException(422, "Capability name is required")
    if req.concurrency < 1:
        raise HTTPException(422, "Concurrency must be at least 1")

    capability_id = str(uuid.uuid4())[:8]
    values = {
        "id": capability_id,
        "tenant_id": tenant["id"],
        "name": name,
        "provider": req.provider.strip() or "local",
        "framework": req.framework.strip() or "selenium",
        "browser": req.browser.strip() or "chrome",
        "browser_version": req.browser_version.strip() or None,
        "platform": req.platform.strip() or "web",
        "os": req.os.strip() or None,
        "device": req.device.strip() or None,
        "viewport": req.viewport.strip() or None,
        "region": req.region.strip() or None,
        "concurrency": req.concurrency,
        "status": req.status.strip() or "available",
        "tags": req.tags,
        "created_at": now(),
        "updated_at": now(),
        "is_active": True,
    }
    with engine.begin() as conn:
        conn.execute(runner_capabilities.insert().values(**values))
        _audit(conn, tenant["id"], _actor_email(request), "runner_capability.created", capability_id, {"name": name})
    return _to_response(values)


@router.patch("/capabilities/{capability_id}")
def update_capability(capability_id: str, req: CapabilityUpdateRequest, request: Request):
    require_role(request, PROJECT_ADMIN_ROLES)
    if capability_id in {item["id"] for item in SYSTEM_CAPABILITIES}:
        raise HTTPException(400, "System capabilities cannot be edited")

    tenant = request.state.tenant
    updates = {}
    for field in (
        "name", "provider", "framework", "browser", "browser_version",
        "platform", "os", "device", "viewport", "region", "status",
    ):
        value = getattr(req, field)
        if value is not None:
            cleaned = value.strip()
            if field == "name" and not cleaned:
                raise HTTPException(422, "Capability name cannot be empty")
            updates[field] = cleaned or None
    if req.concurrency is not None:
        if req.concurrency < 1:
            raise HTTPException(422, "Concurrency must be at least 1")
        updates["concurrency"] = req.concurrency
    if req.tags is not None:
        updates["tags"] = req.tags
    if req.is_active is not None:
        updates["is_active"] = req.is_active
    if not updates:
        raise HTTPException(422, "No capability changes supplied")
    updates["updated_at"] = now()

    with engine.begin() as conn:
        row = conn.execute(
            select(runner_capabilities).where(
                runner_capabilities.c.id == capability_id,
                runner_capabilities.c.tenant_id == tenant["id"],
            )
        ).mappings().first()
        if not row:
            raise HTTPException(404, "Capability not found")
        conn.execute(
            update(runner_capabilities)
            .where(
                runner_capabilities.c.id == capability_id,
                runner_capabilities.c.tenant_id == tenant["id"],
            )
            .values(**updates)
        )
        _audit(conn, tenant["id"], _actor_email(request), "runner_capability.updated", capability_id, updates)
        updated = conn.execute(
            select(runner_capabilities).where(runner_capabilities.c.id == capability_id)
        ).mappings().first()
    return _to_response(updated)


@router.delete("/capabilities/{capability_id}")
def deactivate_capability(capability_id: str, request: Request):
    require_role(request, PROJECT_ADMIN_ROLES)
    if capability_id in {item["id"] for item in SYSTEM_CAPABILITIES}:
        raise HTTPException(400, "System capabilities cannot be deactivated")

    tenant = request.state.tenant
    with engine.begin() as conn:
        row = conn.execute(
            select(runner_capabilities).where(
                runner_capabilities.c.id == capability_id,
                runner_capabilities.c.tenant_id == tenant["id"],
            )
        ).mappings().first()
        if not row:
            raise HTTPException(404, "Capability not found")
        conn.execute(
            update(runner_capabilities)
            .where(
                runner_capabilities.c.id == capability_id,
                runner_capabilities.c.tenant_id == tenant["id"],
            )
            .values(is_active=False, updated_at=now())
        )
        _audit(conn, tenant["id"], _actor_email(request), "runner_capability.deactivated", capability_id)
    return {"status": "deactivated", "capability_id": capability_id}
