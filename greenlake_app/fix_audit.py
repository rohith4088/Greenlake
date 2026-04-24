import re

with open("app/api/routers/ccs_manager.py", "r") as f:
    code = f.read()

audit_pattern = re.compile(
    r'(    # ── Audit log ──[^\n]*\n'
    r'    try:\n'
    r'        _au = _get_session_user\(request\)\n'
    r'        log_operation\(\n'
    r'            user=_au, operation="([^"]+)",\n'
    r'            endpoint="([^"]+)",\n'
    r'            dry_run=bool\(dry_run\),\n'
    r'            input_rows=([^,]+),\n'
    r'            workspace=([^,]+),\n'
    r'            total=results\.get\(\'total\'\), success=results\.get\(\'successful\'\),\n'
    r'            failed=results\.get\(\'failed\'\), status=\'ok\'\n'
    r'        \)\n'
    r'    except Exception as _ae:\n'
    r'        print\(f\'Audit log error: \{_ae\}\'\)\n\n'
    r'    return JSONResponse\(content=\{\*\*results, "dry_run": True\}\)\n)'
)

def fix_dryrun_block(match):
    full_block = match.group(1)
    operation = match.group(2)
    endpoint = match.group(3)
    input_rows = match.group(4)
    workspace = match.group(5)

    indented = ""
    for line in full_block.split('\n'):
        if line:
            indented += "    " + line + "\n"
        else:
            indented += "\n"
    return indented

# Replace the dry run blocks with indented versions
code = audit_pattern.sub(fix_dryrun_block, code)

# Now, we need to add the real audit log block before each `return JSONResponse(content=results)`
# Wait! Instead of doing it blindly, let's just do a specific regex for the end of each endpoint.
# Actually, the endpoints are exactly defined by `return JSONResponse(content=results)`.
# Let's do it per endpoint.

endpoints_info = [
    ("Transfer Devices", "/api/ccs/transfer-devices", "len(serials)", "dest_workspace_id", "    results[\"elapsed_seconds\"] = round(time.time() - start_time, 2)\n    return JSONResponse(content=results)"),
    ("Bulk Move Devices", "/api/ccs/bulk-move-devices", "len(rows)", "''", "    results[\"elapsed_seconds\"] = round(time.time() - start_time, 2)\n    return JSONResponse(content=results)"),
    ("Transfer Subscriptions", "/api/ccs/transfer-subscriptions", "len(keys)", "dest_workspace_id", "    results[\"elapsed_seconds\"] = round(time.time() - start_time, 2)\n    return JSONResponse(content=results)"),
    ("Unclaim Devices", "/api/ccs/unclaim-devices", "len(serials)", "workspace_id", "    results[\"elapsed_seconds\"] = round(time.time() - start_time, 2)\n    return JSONResponse(content=results)"),
    ("Claim Devices", "/api/ccs/claim-devices", "len(serials)", "workspace_id", "    results[\"elapsed_seconds\"] = round(time.time() - start_time, 2)\n    return JSONResponse(content=results)"),
]

for op, ep, irows, ws, target_return in endpoints_info:
    real_audit_block = f"""    # ── Audit log ─────────────────────────────────────────
    try:
        _au = _get_session_user(request)
        log_operation(
            user=_au, operation="{op}",
            endpoint="{ep}",
            dry_run=False,
            input_rows={irows},
            workspace={ws},
            total=results.get('total'), success=results.get('successful'),
            failed=results.get('failed'), status='ok'
        )
    except Exception as _ae:
        print(f'Audit log error: {{_ae}}')

{target_return}"""
    code = code.replace(target_return, real_audit_block)

with open("app/api/routers/ccs_manager.py", "w") as f:
    f.write(code)

print("Done fixing audit blocks.")
