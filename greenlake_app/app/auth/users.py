"""User loading and authentication against users.yaml."""
import os
import yaml
import bcrypt
from typing import Optional

USERS_FILE = os.path.join(os.path.dirname(__file__), "../config/users.yaml")

# Role hierarchy: higher index = more permissions
ROLE_HIERARCHY = {"viewer": 0, "operator": 1, "admin": 2}


def _load_users() -> list:
    try:
        with open(USERS_FILE, "r") as f:
            data = yaml.safe_load(f)
            return data.get("users", [])
    except Exception:
        return []


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """Verify username+password. Returns user dict on success, None on failure."""
    users = _load_users()
    for user in users:
        if user.get("username") == username and user.get("enabled", True):
            stored_hash = user.get("password_hash", "")
            try:
                if bcrypt.checkpw(password.encode(), stored_hash.encode()):
                    return {
                        "username": user["username"],
                        "display_name": user.get("display_name", username),
                        "role": user.get("role", "viewer"),
                    }
            except Exception:
                pass
    return None


def get_user(username: str) -> Optional[dict]:
    """Retrieve user info by username (no password check)."""
    users = _load_users()
    for user in users:
        if user.get("username") == username and user.get("enabled", True):
            return {
                "username": user["username"],
                "display_name": user.get("display_name", username),
                "role": user.get("role", "viewer"),
            }
    return None


def role_gte(user_role: str, required_role: str) -> bool:
    """Return True if user_role >= required_role in hierarchy."""
    return ROLE_HIERARCHY.get(user_role, -1) >= ROLE_HIERARCHY.get(required_role, 999)


def hash_password(plain: str) -> str:
    """Helper to generate bcrypt hash for a new password."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(12)).decode()
