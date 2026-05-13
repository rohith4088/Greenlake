import json

dry_run = False
results = {"details": [{"key": "yashas.shetty@hpe.com", "success": True, "status": "Success", "detail": "User deleted successfully (0f80846829e411f1842cae...)"}]}
rb_users = []
for d in results["details"]:
    print("Evaluating:", d)
    if d.get("success") and "Skipped" not in d.get("status", "") and "Would" not in d.get("status", ""):
        wid_str = d.get("detail", "").split()[-1].strip("()")
        print("Extracted wid_str:", wid_str)
        if wid_str:
            rb_users.append({"username": d["key"], "workspace_id": wid_str})

rollback_payload = {"action": "invite_user", "users": rb_users} if not dry_run and rb_users else None
print("Rollback payload:", json.dumps(rollback_payload) if rollback_payload else None)
