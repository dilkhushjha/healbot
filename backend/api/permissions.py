"""Role-based access helpers for API routers."""
from fastapi import HTTPException, Request

VALID_ROLES = {"owner", "admin", "qa_lead", "qa_engineer", "viewer"}
TEAM_ADMIN_ROLES = {"owner", "admin"}
PROJECT_ADMIN_ROLES = {"owner", "admin", "qa_lead"}
TEST_RUNNER_ROLES = {"owner", "admin", "qa_lead", "qa_engineer"}


def current_role(request: Request) -> str:
    return getattr(request.state, "role", "viewer")


def require_role(request: Request, allowed: set[str]) -> str:
    role = current_role(request)
    if role not in allowed:
        raise HTTPException(403, f"Requires one of: {', '.join(sorted(allowed))}")
    return role


def permissions_for(role: str) -> dict:
    return {
        "can_manage_users": role in TEAM_ADMIN_ROLES,
        "can_manage_api_keys": role in TEAM_ADMIN_ROLES,
        "can_manage_projects": role in PROJECT_ADMIN_ROLES,
        "can_run_tests": role in TEST_RUNNER_ROLES,
        "can_view_dashboard": role in VALID_ROLES,
    }
