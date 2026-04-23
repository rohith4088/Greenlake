"""Session management using itsdangerous signed cookies (no Redis needed for this approach)."""
import os
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, Response
from typing import Optional

SECRET_KEY = os.environ.get("SESSION_SECRET_KEY", "dev-secret-change-in-production")
SESSION_COOKIE = "gl_session"
SESSION_MAX_AGE = 8 * 3600  # 8 hours

_serializer = URLSafeTimedSerializer(SECRET_KEY)


def create_session_cookie(user: dict) -> str:
    """Create a signed session token containing user info."""
    return _serializer.dumps(user)


def read_session(request: Request) -> Optional[dict]:
    """Read and verify the session cookie. Returns user dict or None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        user = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        return user
    except (BadSignature, SignatureExpired):
        return None


def set_session(response: Response, user: dict):
    """Write the signed session cookie to the response."""
    token = create_session_cookie(user)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=SESSION_MAX_AGE,
    )


def clear_session(response: Response):
    """Delete the session cookie."""
    response.delete_cookie(key=SESSION_COOKIE)
