"""FastAPI RBAC dependencies."""
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse
from app.auth.session import read_session
from app.auth.users import role_gte
from typing import Optional


def get_current_user(request: Request) -> dict:
    """Dependency: return current user or redirect to login."""
    user = read_session(request)
    if not user:
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return user


def require_role(min_role: str):
    """Dependency factory: require at least the given role."""
    def _check(request: Request) -> dict:
        user = read_session(request)
        if not user:
            raise HTTPException(status_code=307, headers={"Location": "/login"})
        if not role_gte(user.get("role", "viewer"), min_role):
            raise HTTPException(
                status_code=403,
                detail=f"Role '{min_role}' or higher required. You have '{user.get('role')}'.",
            )
        return user
    return _check


def get_current_user_optional(request: Request) -> Optional[dict]:
    """Dependency: return current user or None (no redirect)."""
    return read_session(request)
