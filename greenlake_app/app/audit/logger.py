"""Structured audit logging to JSON file + SQLite for the admin viewer."""
import os
import json
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(os.path.join(os.path.dirname(__file__), "../../logs"))
LOG_DIR.mkdir(exist_ok=True)

AUDIT_JSON_LOG = LOG_DIR / "audit.log"
AUDIT_DB = LOG_DIR / "audit.db"

# ── JSON file logger ───────────────────────────────────────────────────────────
_json_logger = logging.getLogger("audit")
_json_logger.setLevel(logging.INFO)
_fh = logging.FileHandler(AUDIT_JSON_LOG)
_fh.setFormatter(logging.Formatter("%(message)s"))
_json_logger.addHandler(_fh)
_json_logger.propagate = False


# ── SQLite setup ───────────────────────────────────────────────────────────────
def _get_db():
    conn = sqlite3.connect(str(AUDIT_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT NOT NULL,
            username    TEXT NOT NULL,
            display_name TEXT NOT NULL,
            role        TEXT NOT NULL,
            operation   TEXT NOT NULL,
            endpoint    TEXT NOT NULL,
            dry_run     INTEGER NOT NULL DEFAULT 0,
            input_rows  INTEGER,
            workspace   TEXT,
            total       INTEGER,
            success     INTEGER,
            failed      INTEGER,
            status      TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


# ── Public API ─────────────────────────────────────────────────────────────────
def log_operation(
    user: dict,
    operation: str,
    endpoint: str,
    dry_run: bool = False,
    input_rows: int = None,
    workspace: str = None,
    total: int = None,
    success: int = None,
    failed: int = None,
    status: str = "ok",
    extra: dict = None,
):
    """Write one audit event to both JSON log file and SQLite DB."""
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "ts": now,
        "username": user.get("username", "unknown"),
        "display_name": user.get("display_name", "unknown"),
        "role": user.get("role", "unknown"),
        "operation": operation,
        "endpoint": endpoint,
        "dry_run": dry_run,
        "input_rows": input_rows,
        "workspace": workspace,
        "total": total,
        "success": success,
        "failed": failed,
        "status": status,
    }
    if extra:
        record.update(extra)

    # Write to JSON log
    _json_logger.info(json.dumps(record))

    # Write to SQLite
    try:
        conn = _get_db()
        conn.execute(
            """INSERT INTO audit_log
               (ts, username, display_name, role, operation, endpoint, dry_run,
                input_rows, workspace, total, success, failed, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                now, record["username"], record["display_name"], record["role"],
                operation, endpoint, int(dry_run),
                input_rows, workspace, total, success, failed, status,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        _json_logger.error(json.dumps({"error": str(e), "context": "audit_db_write"}))


def get_recent_logs(limit: int = 200) -> list:
    """Fetch recent audit log rows for the admin viewer."""
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []
