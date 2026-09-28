"""Projects and environments for tenant-scoped QA automation."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
import uuid

from api.permissions import PROJECT_ADMIN_ROLES, require_role
from core.database import audit_events, engine, environments, now, projects as projects_table
from core.runner_capabilities import resolve_capability


router = APIRouter(prefix="/projects", tags=["Projects"])


class ProjectRequest(BaseModel):
    name: str
    description: str = ""


class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


class EnvironmentRequest(BaseModel):
    name: str
    base_url: str = ""
    framework: str = "playwright"
    browser: str = "chromium"
    platform: str = "web"
    runner_capability_id: str = ""
    variables: dict = Field(default_factory=dict)


class EnvironmentUpdateRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    framework: str | None = None
    browser: str | None = None
    platform: str | None = None
    runner_capability_id: str | None = None
    variables: dict | None = None
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


def _project_or_404(conn, tenant_id: str, project_id: str) -> dict:
    project = conn.execute(
        select(projects_table).where(
            projects_table.c.id == project_id,
            projects_table.c.tenant_id == tenant_id,
        )
    ).mappings().first()
    if not project:
        raise HTTPException(404, "Project not found")
    return dict(project)


def _environment_or_404(conn, tenant_id: str, project_id: str, environment_id: str) -> dict:
    environment = conn.execute(
        select(environments).where(
            environments.c.id == environment_id,
            environments.c.tenant_id == tenant_id,
            environments.c.project_id == project_id,
        )
    ).mappings().first()
    if not environment:
        raise HTTPException(404, "Environment not found")
    return dict(environment)


def _validate_capability(conn, tenant_id: str, capability_id: str):
    if capability_id and not resolve_capability(conn, tenant_id, capability_id):
        raise HTTPException(422, "Runner capability not found")


def _rows_with_environments(conn, tenant_id: str, project_rows) -> list[dict]:
    project_ids = [row["id"] for row in project_rows]
    env_rows = []
    if project_ids:
        env_rows = conn.execute(
            select(environments).where(
                environments.c.tenant_id == tenant_id,
                environments.c.project_id.in_(project_ids),
                environments.c.is_active == True,
            ).order_by(environments.c.created_at.asc())
        ).mappings().all()

    grouped = {project_id: [] for project_id in project_ids}
    for row in env_rows:
        grouped.setdefault(row["project_id"], []).append(dict(row))

    result = []
    for row in project_rows:
        item = dict(row)
        item["environments"] = grouped.get(row["id"], [])
        item["environment_count"] = len(item["environments"])
        result.append(item)
    return result


@router.get("")
def list_projects(request: Request):
    tenant = request.state.tenant
    with engine.connect() as conn:
        rows = conn.execute(
            select(projects_table)
            .where(projects_table.c.tenant_id == tenant["id"])
            .order_by(projects_table.c.created_at.desc())
        ).mappings().all()
        return _rows_with_environments(conn, tenant["id"], rows)


@router.post("")
def create_project(req: ProjectRequest, request: Request):
    require_role(request, PROJECT_ADMIN_ROLES)
    tenant = request.state.tenant
    name = req.name.strip()
    if not name:
        raise HTTPException(422, "Project name is required")

    project_id = str(uuid.uuid4())[:8]
    with engine.begin() as conn:
        conn.execute(projects_table.insert().values(
            id=project_id,
            tenant_id=tenant["id"],
            name=name,
            description=req.description.strip() or None,
            created_at=now(),
        ))
        _audit(conn, tenant["id"], _actor_email(request), "project.created", project_id, {"name": name})
        project = _project_or_404(conn, tenant["id"], project_id)
    return {**project, "environments": [], "environment_count": 0}


@router.get("/{project_id}")
def get_project(project_id: str, request: Request):
    tenant = request.state.tenant
    with engine.connect() as conn:
        project = _project_or_404(conn, tenant["id"], project_id)
        return _rows_with_environments(conn, tenant["id"], [project])[0]


@router.patch("/{project_id}")
def update_project(project_id: str, req: ProjectUpdateRequest, request: Request):
    require_role(request, PROJECT_ADMIN_ROLES)
    tenant = request.state.tenant
    updates = {}
    if req.name is not None:
        name = req.name.strip()
        if not name:
            raise HTTPException(422, "Project name cannot be empty")
        updates["name"] = name
    if req.description is not None:
        updates["description"] = req.description.strip() or None
    if not updates:
        raise HTTPException(422, "No project changes supplied")

    with engine.begin() as conn:
        _project_or_404(conn, tenant["id"], project_id)
        conn.execute(
            update(projects_table)
            .where(projects_table.c.id == project_id, projects_table.c.tenant_id == tenant["id"])
            .values(**updates)
        )
        _audit(conn, tenant["id"], _actor_email(request), "project.updated", project_id, updates)
        project = _project_or_404(conn, tenant["id"], project_id)
        return _rows_with_environments(conn, tenant["id"], [project])[0]


@router.post("/{project_id}/environments")
def create_environment(project_id: str, req: EnvironmentRequest, request: Request):
    require_role(request, PROJECT_ADMIN_ROLES)
    tenant = request.state.tenant
    name = req.name.strip()
    if not name:
        raise HTTPException(422, "Environment name is required")

    environment_id = str(uuid.uuid4())[:8]
    with engine.begin() as conn:
        _project_or_404(conn, tenant["id"], project_id)
        runner_capability_id = req.runner_capability_id.strip()
        _validate_capability(conn, tenant["id"], runner_capability_id)
        conn.execute(environments.insert().values(
            id=environment_id,
            tenant_id=tenant["id"],
            project_id=project_id,
            name=name,
            base_url=req.base_url.strip() or None,
            framework=req.framework.strip() or "playwright",
            browser=req.browser.strip() or "chromium",
            platform=req.platform.strip() or "web",
            runner_capability_id=runner_capability_id or None,
            variables=req.variables or {},
            created_at=now(),
            updated_at=now(),
            is_active=True,
        ))
        _audit(
            conn,
            tenant["id"],
            _actor_email(request),
            "environment.created",
            environment_id,
            {"project_id": project_id, "name": name},
        )
        environment = _environment_or_404(conn, tenant["id"], project_id, environment_id)
    return environment


@router.patch("/{project_id}/environments/{environment_id}")
def update_environment(project_id: str, environment_id: str, req: EnvironmentUpdateRequest, request: Request):
    require_role(request, PROJECT_ADMIN_ROLES)
    tenant = request.state.tenant
    updates = {}
    for field in ("name", "base_url", "framework", "browser", "platform", "runner_capability_id"):
        value = getattr(req, field)
        if value is not None:
            cleaned = value.strip()
            if field == "name" and not cleaned:
                raise HTTPException(422, "Environment name cannot be empty")
            updates[field] = cleaned or None
    if req.variables is not None:
        updates["variables"] = req.variables
    if req.is_active is not None:
        updates["is_active"] = req.is_active
    if not updates:
        raise HTTPException(422, "No environment changes supplied")
    updates["updated_at"] = now()

    with engine.begin() as conn:
        _project_or_404(conn, tenant["id"], project_id)
        _environment_or_404(conn, tenant["id"], project_id, environment_id)
        if updates.get("runner_capability_id"):
            _validate_capability(conn, tenant["id"], updates["runner_capability_id"])
        conn.execute(
            update(environments)
            .where(
                environments.c.id == environment_id,
                environments.c.tenant_id == tenant["id"],
                environments.c.project_id == project_id,
            )
            .values(**updates)
        )
        _audit(conn, tenant["id"], _actor_email(request), "environment.updated", environment_id, updates)
        return _environment_or_404(conn, tenant["id"], project_id, environment_id)


@router.delete("/{project_id}/environments/{environment_id}")
def deactivate_environment(project_id: str, environment_id: str, request: Request):
    require_role(request, PROJECT_ADMIN_ROLES)
    tenant = request.state.tenant
    with engine.begin() as conn:
        _project_or_404(conn, tenant["id"], project_id)
        _environment_or_404(conn, tenant["id"], project_id, environment_id)
        conn.execute(
            update(environments)
            .where(
                environments.c.id == environment_id,
                environments.c.tenant_id == tenant["id"],
                environments.c.project_id == project_id,
            )
            .values(is_active=False, updated_at=now())
        )
        _audit(conn, tenant["id"], _actor_email(request), "environment.deactivated", environment_id)
    return {"status": "deactivated", "environment_id": environment_id}
