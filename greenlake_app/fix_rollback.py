import sqlite3
import json

conn = sqlite3.connect('/Users/rohithr/Desktop/Greenlake_Everything/greenlake_app/logs/audit.db')
c = conn.cursor()
c.execute("SELECT id, operation, dry_run, rollback_data FROM audit_log WHERE operation IN ('Delete Users', 'Transfer Devices', 'Transfer Subscriptions') ORDER BY id DESC LIMIT 10")
for row in c.fetchall():
    print(f"ID={row[0]} OP={row[1]} DRY={row[2]} RB_DATA_LEN={len(row[3]) if row[3] else 'None'}")
