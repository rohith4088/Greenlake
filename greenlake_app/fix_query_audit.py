with open("app/api/routers/ccs_manager.py", "r") as f:
    lines = f.readlines()

out = []
audit_block = []
in_audit = False

for line in lines:
    if "    # ── Audit log ──────────────────────────────────────────────" in line and "def _run_device_batch" not in "".join(lines[max(0, lines.index(line)-30):lines.index(line)]):
        pass

# Actually, let's just use Python re to carefully extract and replace.
import re

with open("app/api/routers/ccs_manager.py", "r") as f:
    code = f.read()

# Find the audit log inside _run_device_batch
pattern = re.compile(
    r'(    # ── Audit log ──[^\n]*\n'
    r'    try:\n'
    r'        _au = _get_session_user\(request\)\n'
    r'(?:        [^\n]*\n)+'
    r'    except Exception as _ae:\n'
    r'        print\(f\'Audit log error: \{_ae\}\'\)\n)'
)

# We want to remove it from where it is right now.
# But only the one inside `_run_device_batch`. Let's just find the one for "Query Devices".
match = re.search(
    r'(    # ── Audit log ──[^\n]*\n'
    r'    try:\n'
    r'        _au = _get_session_user\(request\)\n'
    r'(?:        [^\n]*\n)*'
    r'        log_operation\(\n'
    r'            user=_au, operation="Query Devices",\n'
    r'(?:            [^\n]*\n)*'
    r'        \)\n'
    r'    except Exception as _ae:\n'
    r'        print\(f\'Audit log error: \{_ae\}\'\)\n)', code)

if match:
    audit_block = match.group(1)
    # Remove it
    code = code.replace(audit_block, "")
    
    # Indent it by 8 spaces (since it's inside event_generator)
    new_audit_block = "\n".join("    " + line if line.strip() else line for line in audit_block.split("\n"))
    
    # Put it before `yield json.dumps({"type": "complete", "results": results}) + "\n"`
    target = '        results["elapsed_seconds"] = round(time.time() - start_time, 2)\n        yield json.dumps({"type": "complete", "results": results}) + "\\n"'
    
    replacement = f'        results["elapsed_seconds"] = round(time.time() - start_time, 2)\n\n{new_audit_block}\n        yield json.dumps({{"type": "complete", "results": results}}) + "\\n"'
    
    code = code.replace(target, replacement)

with open("app/api/routers/ccs_manager.py", "w") as f:
    f.write(code)

print("Fixed Query Devices audit log!")
