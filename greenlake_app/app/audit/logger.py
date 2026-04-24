"""Structured audit logging to JSON file + SQLite for the admin viewer.

Schema additions over v1:
  - op_category  : 'device' | 'subscription' | 'user' | 'session' | 'system'
  - query_input  : comma-joined list of keys/patterns that were queried
  - elapsed_sec  : how long the operation took (seconds, float)
  - detail       : free-text summary of what happened
  - base_url     : which API base was used (aquila vs global)
"""
import os
import json
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

LOG_DIR = Path(os.path.join(os.path.dirname(__file__), "../../logs"))
LOG_DIR.mkdir(exist_ok=True)

AUDIT_JSON_LOG = LOG_DIR / "audit.log"
AUDIT_DB       = LOG_DIR / "audit.db"

# ── JSON file logger ───────────────────────────────────────────────────────────
_json_logger = logging.getLogger("audit")
_json_logger.setLevel(logging.INFO)
if not _json_logger.handlers:
    _fh = logging.FileHandler(AUDIT_JSON_LOG)
    _fh.setFormatter(logging.Formatter("%(message)s"))
    _json_logger.addHandler(_fh)
    _json_logger.propagate = False


# ── SQLite setup ───────────────────────────────────────────────────────────────
def _get_db():
    conn = sqlite3.connect(str(AUDIT_DB))
    conn.row_factory = sqlite3.Row
    # Create / migrate table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            ts           TEXT NOT NULL,
            username     TEXT NOT NULL,
            display_name TEXT NOT NULL,
            role         TEXT NOT NULL,
            op_category  TEXT NOT NULL DEFAULT 'other',
            operation    TEXT NOT NULL,
            endpoint     TEXT NOT NULL,
            dry_run      INTEGER NOT NULL DEFAULT 0,
            input_rows   INTEGER,
            query_input  TEXT,
            workspace    TEXT,
            base_url     TEXT,
            total        INTEGER,
            success      INTEGER,
            failed       INTEGER,
            elapsed_sec  REAL,
            status       TEXT NOT NULL,
            detail       TEXT,
            rollback_data TEXT
        )
    """)
    # Add new columns to existing DBs gracefully
    existing = {row[1] for row in conn.execute("PRAGMA table_info(audit_log)")}
    migrations = {
        "op_category": "TEXT NOT NULL DEFAULT 'other'",
        "query_input": "TEXT",
        "base_url":    "TEXT",
        "elapsed_sec": "REAL",
        "detail":      "TEXT",
        "rollback_data": "TEXT",
    }
    for col, typedef in migrations.items():
        if col not in existing:
            try:
                conn.execute(f"ALTER TABLE audit_log ADD COLUMN {col} {typedef}")
            except Exception:
                pass
    conn.commit()
    return conn


# ── Category inference ─────────────────────────────────────────────────────────
def _infer_category(operation: str) -> str:
    op = operation.lower()
    if any(k in op for k in ("device", "unclaim", "claim")):
        return "device"
    if any(k in op for k in ("subscription", "order")):
        return "subscription"
    if any(k in op for k in ("user", "delete user")):
        return "user"
    if any(k in op for k in ("workspace",)):
        return "workspace"
    if "session" in op or "validate" in op:
        return "session"
    if any(k in op for k in ("snapshot", "audit", "app")):
        return "system"
    return "other"


# ── Public API ─────────────────────────────────────────────────────────────────
def log_operation(
    user: dict,
    operation: str,
    endpoint: str,
    dry_run: bool = False,
    input_rows: int = None,
    query_input: str = None,   # CSV of keys/patterns actually queried
    workspace: str = None,
    base_url: str = None,
    total: int = None,
    success: int = None,
    failed: int = None,
    elapsed_sec: float = None,
    status: str = "ok",
    detail: str = None,
    rollback_data: str = None,
    extra: dict = None,
):
    """Write one audit event to both the JSON log file and SQLite DB."""
    now = datetime.now(timezone.utc).isoformat()
    category = _infer_category(operation)

    record = {
        "ts":           now,
        "username":     user.get("username", "unknown"),
        "display_name": user.get("display_name", "unknown"),
        "role":         user.get("role", "unknown"),
        "op_category":  category,
        "operation":    operation,
        "endpoint":     endpoint,
        "dry_run":      dry_run,
        "input_rows":   input_rows,
        "query_input":  query_input,
        "workspace":    workspace,
        "base_url":     base_url,
        "total":        total,
        "success":      success,
        "failed":       failed,
        "elapsed_sec":  elapsed_sec,
        "status":       status,
        "detail":       detail,
        "rollback_data": rollback_data,
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
               (ts, username, display_name, role, op_category, operation, endpoint,
                dry_run, input_rows, query_input, workspace, base_url,
                total, success, failed, elapsed_sec, status, detail, rollback_data)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                now,
                record["username"], record["display_name"], record["role"],
                category, operation, endpoint,
                int(dry_run),
                input_rows, query_input, workspace, base_url,
                total, success, failed, elapsed_sec,
                status, detail, rollback_data,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        _json_logger.error(json.dumps({"error": str(e), "context": "audit_db_write"}))


def get_log_by_id(audit_id: int) -> dict:
    """Fetch a specific log entry by ID."""
    try:
        conn = _get_db()
        row = conn.execute("SELECT * FROM audit_log WHERE id = ?", (audit_id,)).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def get_recent_logs(limit: int = 500) -> list:
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


def get_log_stats() -> dict:
    """Return summary statistics for the dashboard."""
    try:
        conn = _get_db()
        total     = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today     = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE ts LIKE ?", (today_str + "%",)
        ).fetchone()[0]
        by_cat = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT op_category, COUNT(*) FROM audit_log GROUP BY op_category"
            ).fetchall()
        }
        by_user = conn.execute(
            "SELECT username, COUNT(*) as cnt FROM audit_log "
            "GROUP BY username ORDER BY cnt DESC LIMIT 5"
        ).fetchall()
        
        # Dashboard additions
        timeline = conn.execute(
            "SELECT substr(ts, 1, 10) as day, COUNT(*) as cnt FROM audit_log "
            "WHERE day >= date('now', '-7 days') "
            "GROUP BY day ORDER BY day ASC"
        ).fetchall()
        timeline_data = {row[0]: row[1] for row in timeline}
        
        success_fail = conn.execute(
            "SELECT op_category, "
            "SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) as success_cnt, "
            "SUM(CASE WHEN status != 'ok' THEN 1 ELSE 0 END) as fail_cnt "
            "FROM audit_log GROUP BY op_category"
        ).fetchall()
        success_fail_data = {row[0]: {"success": row[1], "fail": row[2]} for row in success_fail}

        conn.close()
        return {
            "total": total, "today": today,
            "by_category": by_cat,
            "top_users": [dict(r) for r in by_user],
            "timeline": timeline_data,
            "success_fail": success_fail_data,
        }
    except Exception:
        return {}
