from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse, StreamingResponse
from typing import Optional, List
import csv
import io
import time
import json
import requests
import httpx
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed

router = APIRouter()

API_BASE = "https://global.api.greenlake.hpe.com"
AQUILA_BASE = "https://aquila-user-api.common.cloud.hpe.com"



# ============================================================
# HELPERS
# ============================================================

def is_aquila_url(base_url: str) -> bool:
    """True if the base URL is the aquila-user-api domain (NOT the frontend portal)."""
    return "aquila-user-api" in base_url


def _extract_csrf(cookie: str) -> str:
    """Extract ccs-csrftoken value from the cookie string."""
    for part in cookie.split(";"):
        part = part.strip()
        if part.lower().startswith("ccs-csrftoken="):
            return part.split("=", 1)[1].strip()
    return ""


def make_headers(
    bearer_token: str,
    cookie: str = "",
    content_type: str = "application/json",
    base_url: str = ""
) -> dict:
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": content_type,
        "Accept": "application/json",
    }
    if cookie:
        headers["Cookie"] = cookie
    # Aquila ui-doorway / support-assistant endpoints require Origin + Referer + CSRF
    if base_url and is_aquila_url(base_url):
        headers["Origin"] = "https://common.cloud.hpe.com"
        headers["Referer"] = "https://common.cloud.hpe.com/"
        csrf = _extract_csrf(cookie)
        if csrf:
            headers["X-CSRF-Token"] = csrf
    return headers


def parse_csv_column(file_content: bytes, columns: List[str]) -> List[str]:
    """Generic CSV parser that tries a list of column names and returns the first match."""
    try:
        # Use TextIOWrapper which natively handles universal newlines and decodes correctly
        text_stream = io.TextIOWrapper(io.BytesIO(file_content), encoding="utf-8-sig")
        reader = csv.DictReader(text_stream)
        values = []
        for row in reader:
            for col in columns:
                if col in row and row[col].strip():
                    values.append(row[col].strip())
                    break
        return values
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"CSV parse error: {str(e)}")


def get_device_id_by_serial(
    bearer_token: str, cookie: str, serial: str, base_url: str
) -> Optional[str]:
    """
    Look up a device UUID/resource_id by serial number.
    - Aquila base URL → ui-doorway path
      Response: {"devices": [{"resource_id": "...", "serial_number": "..."}]}
    - Public GLP URL  → devices/v1beta1 path
      Response: {"items": [{"id": "...", "serialNumber": "..."}]}
    """
    headers = make_headers(bearer_token, cookie, base_url=base_url)

    if is_aquila_url(base_url):
        url = f"{base_url}/ui-doorway/ui/v1/devices"
        params = {"serial_number": serial, "limit": 100}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            print(f"[CCS] Device lookup {serial}: HTTP {resp.status_code} — {resp.text[:300]}")
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("devices", data.get("items", []))
                if isinstance(items, list):
                    for item in items:
                        sn = item.get("serial_number") or item.get("serialNumber", "")
                        if sn.upper() == serial.upper():
                            return (
                                item.get("resource_id")
                                or item.get("id")
                                or item.get("device_id")
                            )
                    if len(items) == 1:
                        item = items[0]
                        return (
                            item.get("resource_id")
                            or item.get("id")
                            or item.get("device_id")
                        )
        except Exception as e:
            print(f"[CCS] Error looking up device {serial}: {e}")
        return None

    else:
        url = f"{base_url}/devices/v1beta1/devices"
        params = {"filter": f"serialNumber eq '{serial}'", "limit": 5}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            print(f"[CCS] Device lookup {serial}: HTTP {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                if items:
                    return items[0].get("id")
        except Exception as e:
            print(f"[CCS] Error looking up device {serial}: {e}")
        return None


def poll_async(
    bearer_token: str, cookie: str, location_url: str,
    max_wait: int = 60, base_url: str = ""
) -> dict:
    """Poll an async operation URL until done or timeout."""
    if not location_url.lower().startswith("http"):
        fallback = base_url if base_url else API_BASE
        location_url = f"{fallback}{location_url if location_url.startswith('/') else '/' + location_url}"

    for _ in range(max_wait // 5):
        time.sleep(5)
        try:
            resp = requests.get(
                location_url,
                headers=make_headers(bearer_token, cookie, base_url=base_url),
                timeout=30
            )
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("status", "").upper()
                print(f"[CCS] Async poll status: {status}")
                if status in ["SUCCEEDED", "COMPLETED", "SUCCESS"]:
                    return {"success": True, "status": status, "details": "Completed"}
                elif status in ["FAILED", "ERROR", "TIMEOUT"]:
                    result = data.get("result", {})
                    reason = result.get("reason", data.get("message", "Unknown error"))
                    return {"success": False, "status": status, "details": reason}
        except Exception as e:
            print(f"[CCS] Poll error: {e}")

    return {"success": None, "status": "TIMEOUT", "details": "Operation still processing — check manually"}


# ============================================================
# VALIDATE SESSION
# ============================================================

@router.post("/validate-session")
async def validate_session(
    bearer_token: str = Form(...),
    cookie: str = Form(""),
    base_url: str = Form(API_BASE)
):
    """
    Smart session validation — auto-detects token type from base URL:
    - aquila-user-api.common.cloud.hpe.com → tests via ui-doorway (browser session token)
    - global.api.greenlake.hpe.com         → tests via platform/workspace API (API client token)
    """
    headers = make_headers(bearer_token, cookie, base_url=base_url)

    if is_aquila_url(base_url):
        test_url = f"{base_url}/ui-doorway/ui/v1/devices"
        print(f"[CCS] Validating AQUILA session via: {test_url}")
        try:
            resp = requests.get(test_url, headers=headers, params={"limit": 1}, timeout=15)
            print(f"[CCS] Aquila validate: HTTP {resp.status_code} — {resp.text[:200]}")

            # Detect if the response is HTML (wrong base URL — frontend portal instead of API)
            content_type = resp.headers.get("Content-Type", "")
            is_html = "text/html" in content_type or resp.text.strip().startswith("<!DOCTYPE")

            if resp.status_code == 200 and is_html:
                return JSONResponse(
                    status_code=400,
                    content={"valid": False, "error":
                        f"Wrong Base URL — got an HTML page instead of API JSON. "
                        f"Please set Base URL to 'https://aquila-user-api.common.cloud.hpe.com' (not the portal URL)."}
                )

            if resp.status_code == 200:
                try:
                    data = resp.json()
                except Exception:
                    return JSONResponse(
                        status_code=400,
                        content={"valid": False, "error": "Response was not JSON — check your Base URL setting."}
                    )
                total = data.get("total", data.get("count", len(data.get("devices", []))))
                return JSONResponse(content={
                    "valid": True,
                    "mode": "aquila-ui-doorway",
                    "workspace_count": 1,
                    "workspaces": [],
                    "message": f"Aquila session valid — ui-doorway accessible ({total} device(s) in context)"
                })
            else:
                hint = ""
                if resp.status_code == 401:
                    hint = " — Token expired or session cookie missing"
                elif resp.status_code == 403:
                    hint = " — CSRF token missing (ensure ccs-csrftoken is in your cookie)"
                return JSONResponse(
                    status_code=401,
                    content={"valid": False, "error": f"HTTP {resp.status_code}{hint}: {resp.text[:300]}"}
                )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Request failed: {str(e)}")

    else:
        test_url = f"{base_url}/platform/workspace/v1/workspaces"
        print(f"[CCS] Validating GLP session via: {test_url}")
        try:
            resp = requests.get(test_url, headers=headers, params={"limit": 5}, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                workspaces = data.get("items", [])
                return JSONResponse(content={
                    "valid": True,
                    "mode": "greenlake-api",
                    "workspace_count": len(workspaces),
                    "workspaces": [
                        {"id": w.get("id"), "name": w.get("name", w.get("displayName", "Unknown"))}
                        for w in workspaces
                    ]
                })
            else:
                return JSONResponse(
                    status_code=401,
                    content={"valid": False, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
                )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Request failed: {str(e)}")


# ============================================================
# QUERY WORKSPACES — bulk CSV, streaming NDJSON
# ============================================================

def _parse_workspace(cust: dict, search_string: str) -> dict:
    """Extract a clean workspace profile from a raw customer API object."""
    contact = cust.get("contact", {})
    address = contact.get("address", {})
    account = cust.get("account", {})
    prefs   = cust.get("preferences", {})
    return {
        "search_string":        search_string,
        "customer_id":          cust.get("customer_id", ""),
        "company_name":         contact.get("company_name", ""),
        "email":                contact.get("email", ""),
        "created_by":           contact.get("created_by", ""),
        "phone_number":         contact.get("phone_number", ""),
        "account_type":         cust.get("account_type", account.get("account_type", "")),
        "msp_id":               cust.get("msp_id", ""),
        "status":               account.get("status", ""),
        "operational_mode":     account.get("operational_mode", cust.get("operational_mode", "")),
        "region":               cust.get("region", ""),
        "organization_id":      cust.get("organization_id", ""),
        "activate_customer_id": cust.get("activate_customer_id"),
        "multi_fa_enabled":     prefs.get("multi_fa_enabled", False),
        "created_at":           account.get("created_at", ""),
        "updated_at":           account.get("updated_at", ""),
        "address": {
            "street":  contact.get("street_address", address.get("street_address", "")),
            "city":    address.get("city", ""),
            "state":   address.get("state_or_region", ""),
            "zip":     address.get("zip", ""),
            "country": address.get("country_code", ""),
        },
    }


def _fetch_workspaces_for_string(
    search_string: str, headers_: dict, endpoint: str, limit: int
) -> dict:
    """Synchronous worker: query the customers API for one search_string."""
    try:
        resp = requests.get(
            endpoint,
            headers=headers_,
            params={"limit": limit, "offset": 0, "search_string": search_string.strip()},
            timeout=30,
        )
        print(f"[CCS] QueryWS '{search_string}': HTTP {resp.status_code}")
        if resp.status_code != 200:
            error_msg = f"HTTP {resp.status_code}"
            try:
                err = resp.json()
                error_msg = err.get("message", err.get("detail", str(err)))
            except Exception:
                error_msg = resp.text[:200] or error_msg
            return {"search_string": search_string, "workspaces": [], "error": error_msg}
        raw = resp.json().get("customers", [])
        return {"search_string": search_string, "workspaces": [_parse_workspace(c, search_string) for c in raw], "error": None}
    except Exception as e:
        return {"search_string": search_string, "workspaces": [], "error": str(e)}


@router.post("/query-workspaces")
async def ccs_query_workspaces(
    request: Request,
    bearer_token: str = Form(...),
    cookie:       str = Form(""),
    base_url:     str = Form(API_BASE),
    limit:        int = Form(10),
    file: UploadFile = File(...),
):
    """
    Bulk workspace lookup from a CSV file.
    Accepted column names: Search String | Platform Customer ID | Customer ID | ID | Email | Company | Name
    Each row = one search string. Deduplicates automatically.
    Streams NDJSON: progress events per row, then a final 'complete' event with all results.
    Requires an Aquila session base URL.
    """
    use_aquila = is_aquila_url(base_url)
    if not use_aquila:
        raise HTTPException(
            status_code=400,
            detail="Query Workspaces requires an Aquila session base URL (aquila-user-api.common.cloud.hpe.com)"
        )

    content = await file.read()
    raw_strings = parse_csv_column(
        content,
        ["Search String", "search_string", "Platform Customer ID", "platform_customer_id",
         "Customer ID", "customer_id", "ID", "id", "Email", "email",
         "Company", "company", "Name", "name", "Workspace", "workspace"]
    )
    # Deduplicate while preserving order
    seen: set = set()
    unique_strings: List[str] = []
    for s in raw_strings:
        if s and s not in seen:
            seen.add(s)
            unique_strings.append(s)

    if not unique_strings:
        raise HTTPException(
            status_code=400,
            detail="No search strings found in CSV. Expected column: Search String, Platform Customer ID, ID, Email, or Company."
        )

    headers_  = make_headers(bearer_token, cookie, base_url=base_url)
    endpoint  = f"{base_url}/support-assistant/v1alpha1/customers"
    capped_limit = max(1, min(limit, 200))

    async def event_generator():
        start_time = time.time()
        all_workspaces: list = []
        found_count = 0
        not_found_count = 0
        error_count = 0
        processed = 0
        total = len(unique_strings)

        yield json.dumps({
            "type": "progress", "current": 0, "total": total,
            "message": f"Starting bulk workspace query for {total} search string(s)\u2026"
        }) + "\n"

        MINI_BATCH = 50
        MAX_WORKERS = 20
        loop = asyncio.get_running_loop()

        def _run_batch(b, h, ep, lim):
            futures_map = {}
            results_ = [None] * len(b)
            with ThreadPoolExecutor(max_workers=min(len(b), MAX_WORKERS)) as ex:
                for i, s in enumerate(b):
                    futures_map[ex.submit(_fetch_workspaces_for_string, s, h, ep, lim)] = i
                for fut in futures_map:
                    idx = futures_map[fut]
                    try:
                        results_[idx] = fut.result()
                    except Exception as e:
                        results_[idx] = {"search_string": b[idx], "workspaces": [], "error": str(e)}
            return results_

        for batch_start in range(0, total, MINI_BATCH):
            if await request.is_disconnected():
                print(f"[CCS] Query Workspaces aborted at {processed}/{total}")
                break

            batch = unique_strings[batch_start: batch_start + MINI_BATCH]

            batch_results = await loop.run_in_executor(
                None, _run_batch, batch, headers_, endpoint, capped_limit
            )

            for res in batch_results:
                processed += 1
                ws_list = res["workspaces"]
                err     = res["error"]
                ss      = res["search_string"]

                if err:
                    error_count += 1
                elif not ws_list:
                    not_found_count += 1
                else:
                    found_count += len(ws_list)
                    all_workspaces.extend(ws_list)

                yield json.dumps({
                    "type":          "progress",
                    "current":       processed,
                    "total":         total,
                    "search_string": ss,
                    "found":         len(ws_list),
                    "error":         err,
                    "message":       (f"[{processed}/{total}] '{ss}' \u2192 {len(ws_list)} workspace(s)"
                                      if not err else f"[{processed}/{total}] '{ss}' \u2192 ERROR: {err}"),
                }) + "\n"

            if batch_start + MINI_BATCH < total:
                await asyncio.sleep(0.5)

        yield json.dumps({
            "type":            "complete",
            "total_searched":  processed,
            "found_count":     found_count,
            "not_found_count": not_found_count,
            "error_count":     error_count,
            "elapsed_seconds": round(time.time() - start_time, 2),
            "workspaces":      all_workspaces,
        }) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")

@router.post("/query-workspaces-csv-direct")
async def ccs_query_workspaces_csv_direct(
    request: Request,
    bearer_token: str = Form(...),
    cookie: str = Form(""),
    base_url: str = Form(API_BASE),
    limit: int = Form(10),
    file: UploadFile = File(...)
):
    """Direct CSV download fallback for Query Workspaces."""
    if not is_aquila_url(base_url):
        raise HTTPException(status_code=400, detail="Query Workspaces requires an Aquila session base URL.")

    content = await file.read()
    raw_strings = parse_csv_column(
        content,
        ["Search String", "search_string", "Platform Customer ID", "platform_customer_id",
         "Customer ID", "customer_id", "ID", "id", "Email", "email",
         "Company", "company", "Name", "name", "Workspace", "workspace"]
    )
    
    seen: set = set()
    unique_strings: List[str] = []
    for s in raw_strings:
        if s and s not in seen:
            seen.add(s)
            unique_strings.append(s)

    if not unique_strings:
        raise HTTPException(status_code=400, detail="No search strings found in CSV.")

    headers_  = make_headers(bearer_token, cookie, base_url=base_url)
    endpoint  = f"{base_url}/support-assistant/v1alpha1/customers"
    capped_limit = max(1, min(limit, 200))

    def _run_batch_sync(b):
        results = []
        with ThreadPoolExecutor(max_workers=min(len(b), 20)) as ex:
            futures = {ex.submit(_fetch_workspaces_for_string, s, headers_, endpoint, capped_limit): s for s in b}
            for fut in as_completed(futures):
                try:
                    res = fut.result()
                    if res["workspaces"]:
                        results.extend(res["workspaces"])
                except Exception:
                    pass
        return results

    loop = asyncio.get_running_loop()
    all_workspaces = await loop.run_in_executor(None, _run_batch_sync, unique_strings)

    if not all_workspaces:
        return JSONResponse(status_code=404, content={"message": "No workspaces found or session expired. Please verify your bearer token."})

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(all_workspaces[0].keys()))
    writer.writeheader()
    writer.writerows(all_workspaces)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=workspaces_result.csv"}
    )



# ============================================================
# TRANSFER DEVICES (Real CCS-Manager endpoint from DevTools)
def _transfer_batch_with_retry(
    headers: dict, 
    endpoint: str, 
    base_payload: dict, 
    batch: List[str], 
    results: dict,
    level: int = 1
):
    """
    Recursively attempts to transfer a batch of devices.
    If a 409 Conflict occurs, splits the batch in half and retries.
    """
    if not batch:
        return
        
    payload = base_payload.copy()
    payload["devices"] = [{"serial_number": s} for s in batch]
    
    print(f"[CCS] retry-level-{level} Transfer POST for {len(batch)} devices")
    try:
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=45)
        
        if resp.status_code in [200, 201]:
            results["successful"] += len(batch)
            for serial in batch:
                results["details"].append({"serial": serial, "success": True, "status": "Transferred"})
                        
        elif resp.status_code == 202:
            results["successful"] += len(batch)
            for serial in batch:
                results["details"].append({"serial": serial, "success": True, "status": "Accepted (async)"})
                
        elif resp.status_code == 409:
            # If batch has more than 1 item, split and retry
            if len(batch) > 1:
                print(f"[CCS] 409 Conflict on batch of {len(batch)}. Splitting and retrying...")
                mid = len(batch) // 2
                _transfer_batch_with_retry(headers, endpoint, base_payload, batch[:mid], results, level + 1)
                _transfer_batch_with_retry(headers, endpoint, base_payload, batch[mid:], results, level + 1)
            else:
                # Base case: exactly 1 item failed with 409
                error_msg = "Conflict: Device cannot be transferred (e.g., active subscription or locked)."
                try:
                    err = resp.json()
                    error_msg = err.get("message", err.get("detail", err.get("error", error_msg)))
                except Exception:
                    pass
                results["failed"] += 1
                results["details"].append({"serial": batch[0], "success": False, "error": error_msg})
                
        else:
            error_msg = f"HTTP {resp.status_code}"
            try:
                err = resp.json()
                error_msg = err.get("message", err.get("detail", err.get("error", str(err))))
            except Exception:
                error_msg = resp.text[:300] or error_msg
            results["failed"] += len(batch)
            for serial in batch:
                results["details"].append({"serial": serial, "success": False, "error": error_msg})
                
    except Exception as e:
        results["failed"] += len(batch)
        for serial in batch:
            results["details"].append({"serial": serial, "success": False, "error": str(e)})


# ============================================================

@router.post("/transfer-devices")
async def ccs_transfer_devices(
    bearer_token: str = Form(...),
    cookie: str = Form(""),
    source_workspace_id: str = Form(...),
    dest_workspace_id: str = Form(...),   # workspace NAME or ID for destination
    base_url: str = Form(API_BASE),
    folder: str = Form("default"),        # folder name — 'default' matches CCS UI dropdown
    dry_run: bool = Form(False),
    file: UploadFile = File(...)
):
    """
    Transfer devices (by serial) using the real CCS-Manager endpoint discovered from DevTools:
      POST /support-assistant/v1alpha1/devices-to-customer   (aquila session)
      PATCH /devices/v1beta1/devices                         (public API fallback)
    """
    start_time = time.time()
    content = await file.read()
    serials = parse_csv_column(
        content,
        ["Serial Number", "SerialNumber", "Serial", "SN", "serial", "SERIAL"]
    )

    if not serials:
        raise HTTPException(status_code=400, detail="No serial numbers found in CSV")

    results = {"total": len(serials), "successful": 0, "failed": 0, "details": [], "elapsed_seconds": 0}
    use_aquila = is_aquila_url(base_url)

    # ── Dry-Run Mode: lookup only, no actual transfer ───────────────────────────
    if dry_run:
        print(f"[CCS] DRY-RUN transfer-devices: {len(serials)} serials → {dest_workspace_id}")
        h = make_headers(bearer_token, cookie, "application/json", base_url)
        for serial in serials:
            try:
                if use_aquila:
                    lurl = f"{base_url}/support-assistant/v1alpha1/activate-devices"
                    r = requests.get(lurl, headers=h, params={"serial_number": serial, "limit": 5}, timeout=30)
                    if r.status_code == 200:
                        items = r.json().get("devices", r.json().get("items", []))
                        m = next((d for d in items if d.get("serial_number", "").upper() == serial.upper()), items[0] if items else None)
                        if m:
                            current_ws = m.get("platform_customer_id", m.get("pcid", "Unknown"))
                            results["successful"] += 1
                            results["details"].append({
                                "serial": serial, "success": True, "status": "Would Transfer",
                                "detail": f"Current WS: {current_ws} → Dest: {dest_workspace_id} | {m.get('device_model','?')} | {m.get('status','?')}"
                            })
                        else:
                            results["failed"] += 1
                            results["details"].append({"serial": serial, "success": False, "error": "Not found in global search"})
                    else:
                        results["failed"] += 1
                        results["details"].append({"serial": serial, "success": False, "error": f"Lookup HTTP {r.status_code}"})
                else:
                    did = get_device_id_by_serial(bearer_token, cookie, serial, base_url)
                    if did:
                        results["successful"] += 1
                        results["details"].append({"serial": serial, "success": True, "status": "Would Transfer", "detail": f"Device {did} → Dest: {dest_workspace_id}"})
                    else:
                        results["failed"] += 1
                        results["details"].append({"serial": serial, "success": False, "error": "Device not found"})
            except Exception as e:
                results["failed"] += 1
                results["details"].append({"serial": serial, "success": False, "error": str(e)})
            time.sleep(0.15)
        results["elapsed_seconds"] = round(time.time() - start_time, 2)
        return JSONResponse(content={**results, "dry_run": True})

    if use_aquila:
        # ── Real support-assistant endpoint ─────────────────────────────
        endpoint = f"{base_url}/support-assistant/v1alpha1/devices-to-customer"
        headers = make_headers(bearer_token, cookie, "application/json", base_url)

        # 1. Fetch folder ID dynamically based on folder name
        folder_id = ""
        try:
            folder_url = f"{base_url}/support-assistant/v1alpha1/user-folders"
            f_params = {"limit": 50, "page": 0, "platform_customer_id": dest_workspace_id}
            print(f"[CCS] Fetching folders for {dest_workspace_id}...")
            f_resp = requests.get(folder_url, headers=headers, params=f_params, timeout=15)
            if f_resp.status_code == 200:
                f_data = f_resp.json()
                items = f_data if isinstance(f_data, list) else f_data.get("items", f_data.get("folders", f_data.get("data", [])))
                for f in items:
                    name = f.get("name", f.get("folder_name", f.get("folderName", "")))
                    if name.lower() == folder.lower():
                        folder_id = f.get("id", f.get("folder_id", f.get("folderId", "")))
                        break
                # Fallback to first folder if exact match not found but folders exist
                if not folder_id and items:
                    folder_id = items[0].get("id", items[0].get("folder_id", items[0].get("folderId", "")))
                    folder = items[0].get("name", items[0].get("folder_name", folder))
        except Exception as e:
            print(f"[CCS] Could not fetch folder ID: {e}")

        print(f"[CCS] Using folder: {folder} (ID: {folder_id})")

        fid: int = 0
        if folder_id:
            try:
                fid = int(folder_id)
            except ValueError:
                pass

        batch_size = 250
        endpoint = f"{base_url}/support-assistant/v1alpha1/devices-to-customer"

        for i in range(0, len(serials), batch_size):
            batch = serials[i:i+batch_size]
            
            base_payload = {
                "folder_name": folder,
                "folder_id": fid,
                "platform_customer_id": dest_workspace_id
            }
            if not fid:
                base_payload.pop("folder_id", None)

            _transfer_batch_with_retry(headers, endpoint, base_payload, batch, results)

            time.sleep(1.0)

    else:
        # ── Public GreenLake API fallback ───────────────────────────────
        for serial in serials:
            device_id = get_device_id_by_serial(bearer_token, cookie, serial, base_url)
            if not device_id:
                results["failed"] += 1
                results["details"].append({"serial": serial, "success": False, "error": "Device not found"})
                continue
            try:
                patch_url = f"{base_url}/devices/v1beta1/devices"
                headers = make_headers(bearer_token, cookie, "application/merge-patch+json", base_url)
                payload = {"workspace": {"id": dest_workspace_id}}
                resp = requests.patch(
                    patch_url, headers=headers, params={"id": device_id}, json=payload, timeout=30
                )
                print(f"[CCS] GLP Transfer {serial}: HTTP {resp.status_code} — {resp.text[:200]}")
                if resp.status_code in [200, 202]:
                    results["successful"] += 1
                    results["details"].append({"serial": serial, "success": True, "status": "Transferred"})
                else:
                    error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    results["failed"] += 1
                    results["details"].append({"serial": serial, "success": False, "error": error_msg})
            except Exception as e:
                results["failed"] += 1
                results["details"].append({"serial": serial, "success": False, "error": str(e)})
            time.sleep(0.3)

    results["elapsed_seconds"] = round(time.time() - start_time, 2)
    return JSONResponse(content=results)


# ============================================================
# BULK MOVE DEVICES (multi-workspace CSV: workspace_id + serial_number per row)
# ============================================================


def _parse_bulk_move_csv(file_content: bytes) -> List[dict]:
    """
    Parse a 2-column file (CSV or TSV) where each row has a destination workspace ID
    and a device serial number.

    Robustness built-in:
    - Auto-detects delimiter: prefers TAB if found on first line, otherwise sniffs
    - Normalises Unicode whitespace (EM SPACE U+2003, NBSP, etc.) in column headers
    - Skips blank rows silently
    - Positional fallback if column names are unrecognised (col0=workspace, col1=serial)

    Accepted column names (case-insensitive after normalisation):
      workspace : Workspace ID | workspace_id | Customer ID | PCID | Destination | Dest
      serial    : Serial Number | SerialNumber | Serial | SN
    Returns list of dicts: [{"workspace_id": "...", "serial": "..."}, ...]
    """
    import re

    WORKSPACE_COLS = {"workspace id", "workspace_id", "customer id", "customer_id",
                      "platform customer id", "platform_customer_id", "pcid",
                      "destination", "dest"}
    SERIAL_COLS    = {"serial number", "serialnumber", "serial", "sn"}

    def _norm(h: str) -> str:
        """Collapse any Unicode whitespace (incl. U+2003 EM SPACE) to single ASCII space."""
        return re.sub(r'[\s\u00a0\u2000-\u200b\u202f\u205f\u3000]+', ' ', h).strip().lower()

    try:
        text = file_content.decode("utf-8-sig")

        # ── Step 1: detect delimiter ──────────────────────────────────────────
        # The header may use exotic spacing (e.g. EM SPACE U+2003) as a separator
        # while every data row uses a tab.  Scan the first *data* line for a tab,
        # not just the header line.
        all_lines = text.splitlines()
        header_line = next((l for l in all_lines if l.strip()), "")
        first_data_line = next((l for l in all_lines[1:] if l.strip()), "")
        check_line = first_data_line if first_data_line else header_line

        delimiter = ","
        if "\t" in check_line:
            delimiter = "\t"
        else:
            try:
                delimiter = csv.Sniffer().sniff(check_line, delimiters=",;\t|").delimiter
            except csv.Error:
                pass

        # ── Step 2: parse with DictReader ─────────────────────────────────────
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter, skipinitialspace=True)

        raw_headers = list(reader.fieldnames or [])
        norm_to_raw = {_norm(h): h for h in raw_headers}

        ws_col = next((norm_to_raw[n] for n in norm_to_raw if n in WORKSPACE_COLS), None)
        sn_col = next((norm_to_raw[n] for n in norm_to_raw if n in SERIAL_COLS),    None)

        # ── Step 3: header-split fallback ─────────────────────────────────────
        # If the header itself used a different separator (e.g. EM SPACE) the
        # DictReader may lump both column names into one string.  Re-split it
        # using any Unicode whitespace sequence and try again.
        if (ws_col is None or sn_col is None) and len(raw_headers) == 1:
            # Re-split the single raw header on Unicode whitespace
            header_parts = re.split(r'[\s\u00a0\u2000-\u200b\u202f\u205f\u3000]+', raw_headers[0].strip())
            header_parts = [p for p in header_parts if p]
            if len(header_parts) >= 2:
                # Rebuild norm_to_raw using positional indices from the re-split
                norm_to_raw2 = {_norm(p): p for p in header_parts}
                ws_col = next((norm_to_raw2[n] for n in norm_to_raw2 if n in WORKSPACE_COLS), None)
                sn_col = next((norm_to_raw2[n] for n in norm_to_raw2 if n in SERIAL_COLS), None)
                # Map back to positional access on the raw_headers key
                ws_col = raw_headers[0] if ws_col is not None else None
                sn_col = raw_headers[0] if sn_col is not None else None
                # When both map to index-0 it means the header re-split worked but
                # DictReader sees only one column — fall through to positional mode below.
                ws_col = sn_col = None  # force positional

        # Positional fallback (col 0 = workspace, col 1 = serial)
        pos_ws = raw_headers[0] if len(raw_headers) > 0 else None
        pos_sn = raw_headers[1] if len(raw_headers) > 1 else None

        # When the file has only ONE recognised column we must use positional
        # mode: re-read each data line, split on the data delimiter, treat
        # index-0 as workspace and index-1 as serial.
        use_manual = (ws_col is None or sn_col is None) and delimiter != ","

        rows = []
        if use_manual:
            # Manual split: skip header, split every non-blank line on delimiter
            for line in all_lines[1:]:
                parts = line.split(delimiter)
                if len(parts) < 2:
                    continue
                ws = parts[0].strip()
                sn = parts[1].strip()
                if ws and sn:
                    rows.append({"workspace_id": ws, "serial": sn})
        else:
            for row in reader:
                # Skip blank separator rows
                if all(not v.strip() for v in row.values() if v):
                    continue
                if ws_col and sn_col:
                    ws = (row.get(ws_col) or "").strip()
                    sn = (row.get(sn_col) or "").strip()
                elif pos_ws and pos_sn:
                    ws = (row.get(pos_ws) or "").strip()
                    sn = (row.get(pos_sn) or "").strip()
                else:
                    ws = sn = ""
                if ws and sn:
                    rows.append({"workspace_id": ws, "serial": sn})
        return rows
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"CSV parse error: {str(e)}")


@router.post("/bulk-move-devices")
async def ccs_bulk_move_devices(
    bearer_token: str = Form(...),
    cookie:       str = Form(""),
    base_url:     str = Form(API_BASE),
    folder:       str = Form("default"),
    dry_run:      bool = Form(False),
    file: UploadFile = File(...),
):
    """
    Bulk-move devices to their individual destination workspaces.
    CSV must have TWO columns per row:
      - Destination Workspace ID  (any of: Workspace ID, Customer ID, PCID, …)
      - Device Serial Number      (any of: Serial Number, SN, serial, …)
    Each device is moved to the workspace specified on its row.
    Devices targeting the same workspace are batched together for efficiency.
    """
    start_time = time.time()
    content = await file.read()
    rows = _parse_bulk_move_csv(content)

    if not rows:
        raise HTTPException(
            status_code=400,
            detail=(
                "No valid rows found in CSV. Expected two columns: "
                "'Workspace ID' (destination) and 'Serial Number'."
            )
        )

    # Group serials by destination workspace
    from collections import defaultdict
    workspace_groups: dict = defaultdict(list)
    for r in rows:
        workspace_groups[r["workspace_id"]].append(r["serial"])

    total_devices = len(rows)
    results = {
        "total":            total_devices,
        "successful":       0,
        "failed":           0,
        "workspaces_count": len(workspace_groups),
        "details":          [],
        "elapsed_seconds":  0,
    }
    use_aquila = is_aquila_url(base_url)
    headers = make_headers(bearer_token, cookie, "application/json", base_url)

    # ── Dry-Run ──────────────────────────────────────────────────────────────
    if dry_run:
        print(f"[CCS] DRY-RUN bulk-move-devices: {total_devices} rows → {len(workspace_groups)} workspaces")
        for dest_ws, serials in workspace_groups.items():
            for serial in serials:
                results["successful"] += 1
                results["details"].append({
                    "serial":  serial,
                    "success": True,
                    "status":  "Would Transfer",
                    "detail":  f"→ Workspace {dest_ws}",
                })
        results["elapsed_seconds"] = round(time.time() - start_time, 2)
        return JSONResponse(content={**results, "dry_run": True})

    # ── Real Transfer ────────────────────────────────────────────────────────
    if use_aquila:
        endpoint = f"{base_url}/support-assistant/v1alpha1/devices-to-customer"
        batch_size = 250

        for dest_ws, serials in workspace_groups.items():
            print(f"[CCS] Bulk-move: {len(serials)} device(s) → workspace {dest_ws}")

            # Resolve folder ID for this destination workspace
            folder_id = ""
            folder_name = folder
            try:
                folder_url = f"{base_url}/support-assistant/v1alpha1/user-folders"
                f_params = {"limit": 50, "page": 0, "platform_customer_id": dest_ws}
                f_resp = requests.get(folder_url, headers=headers, params=f_params, timeout=15)
                if f_resp.status_code == 200:
                    f_data = f_resp.json()
                    items = (
                        f_data if isinstance(f_data, list)
                        else f_data.get("items", f_data.get("folders", f_data.get("data", [])))
                    )
                    for fi in items:
                        name = fi.get("name", fi.get("folder_name", fi.get("folderName", "")))
                        if name.lower() == folder.lower():
                            folder_id = fi.get("id", fi.get("folder_id", fi.get("folderId", "")))
                            break
                    if not folder_id and items:
                        folder_id  = items[0].get("id", items[0].get("folder_id", items[0].get("folderId", "")))
                        folder_name = items[0].get("name", items[0].get("folder_name", folder))
            except Exception as e:
                print(f"[CCS] Could not fetch folder ID for {dest_ws}: {e}")

            fid: int = 0
            if folder_id:
                try:
                    fid = int(folder_id)
                except ValueError:
                    pass

            base_payload = {"folder_name": folder_name, "platform_customer_id": dest_ws}
            if fid:
                base_payload["folder_id"] = fid

            for i in range(0, len(serials), batch_size):
                batch = serials[i : i + batch_size]
                _transfer_batch_with_retry(headers, endpoint, base_payload, batch, results)
                time.sleep(1.0)

    else:
        # Public GreenLake API — patch each device individually
        for dest_ws, serials in workspace_groups.items():
            for serial in serials:
                device_id = get_device_id_by_serial(bearer_token, cookie, serial, base_url)
                if not device_id:
                    results["failed"] += 1
                    results["details"].append({"serial": serial, "success": False, "error": "Device not found"})
                    continue
                try:
                    patch_url = f"{base_url}/devices/v1beta1/devices"
                    h2 = make_headers(bearer_token, cookie, "application/merge-patch+json", base_url)
                    payload  = {"workspace": {"id": dest_ws}}
                    resp = requests.patch(patch_url, headers=h2, params={"id": device_id}, json=payload, timeout=30)
                    print(f"[CCS] Bulk-move GLP {serial} → {dest_ws}: HTTP {resp.status_code}")
                    if resp.status_code in [200, 202]:
                        results["successful"] += 1
                        results["details"].append({
                            "serial":  serial, "success": True, "status": "Transferred",
                            "detail":  f"→ Workspace {dest_ws}",
                        })
                    else:
                        error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                        results["failed"] += 1
                        results["details"].append({"serial": serial, "success": False, "error": error_msg})
                except Exception as e:
                    results["failed"] += 1
                    results["details"].append({"serial": serial, "success": False, "error": str(e)})
                time.sleep(0.3)

    results["elapsed_seconds"] = round(time.time() - start_time, 2)
    return JSONResponse(content=results)


# ============================================================
# TRANSFER SUBSCRIPTIONS (CCS-Manager session)
# ============================================================

@router.post("/transfer-subscriptions")
async def ccs_transfer_subscriptions(
    bearer_token: str = Form(...),
    cookie: str = Form(""),
    source_workspace_id: str = Form(...),
    dest_workspace_id: str = Form(...),
    base_url: str = Form(API_BASE),
    dry_run: bool = Form(False),
    file: UploadFile = File(...)
):
    """
    Transfer subscriptions (by key) from source → destination workspace.
    """
    start_time = time.time()
    content = await file.read()
    keys = parse_csv_column(
        content,
        ["Subscription Key", "SubscriptionKey", "Key", "key", "subscription_key"]
    )

    if not keys:
        raise HTTPException(status_code=400, detail="No subscription keys found in CSV")

    results = {"total": len(keys), "successful": 0, "failed": 0, "details": [], "elapsed_seconds": 0}

    # ── Dry-Run Mode: report what would be transferred, no write calls ──────────
    if dry_run:
        print(f"[CCS] DRY-RUN transfer-subscriptions: {len(keys)} keys {source_workspace_id} → {dest_workspace_id}")
        for key in keys:
            results["successful"] += 1
            results["details"].append({
                "key": key, "success": True, "status": "Would Transfer",
                "detail": f"Subscription key from {source_workspace_id} → {dest_workspace_id}"
            })
        results["elapsed_seconds"] = round(time.time() - start_time, 2)
        return JSONResponse(content={**results, "dry_run": True})

    if is_aquila_url(base_url):
        transfer_url = f"{base_url}/support-assistant/v1alpha1/subscription-transfer"
        headers = make_headers(bearer_token, cookie, base_url=base_url)

        for key in keys:
            payload = {
                "subscription_key": key,
                "platform_customer_id": source_workspace_id,
                "new_customer_id": dest_workspace_id
            }

            try:
                # The endpoint might expect a different HTTP method, try POST -> PUT -> PATCH
                resp = requests.post(transfer_url, headers=headers, json=payload, timeout=30)
                if resp.status_code == 405:
                    print(f"[CCS] POST 405, trying PUT for {key}")
                    resp = requests.put(transfer_url, headers=headers, json=payload, timeout=30)
                if resp.status_code == 405:
                    print(f"[CCS] PUT 405, trying PATCH for {key}")
                    resp = requests.patch(transfer_url, headers=headers, json=payload, timeout=30)

                print(f"[CCS] Transfer subscription {key}: HTTP {resp.status_code} — {resp.text[:200]}")

                if resp.status_code in [200, 201, 204]:
                    results["successful"] += 1
                    results["details"].append({"key": key, "success": True, "status": "Transferred"})
                elif resp.status_code == 202:
                    results["successful"] += 1
                    results["details"].append({"key": key, "success": True, "status": "Processing — verify manually"})
                else:
                    error_msg = f"HTTP {resp.status_code}"
                    try:
                        err = resp.json()
                        error_msg = err.get("message", err.get("detail", str(err)))
                    except Exception:
                        error_msg = resp.text[:200] or error_msg
                    results["failed"] += 1
                    results["details"].append({"key": key, "success": False, "error": error_msg})

            except Exception as e:
                results["failed"] += 1
                results["details"].append({"key": key, "success": False, "error": str(e)})

            time.sleep(0.3)
    else:
        subs_base_url = f"{base_url}/subscriptions/v1/subscriptions"

        for key in keys:
            sub_id = None
            try:
                headers = make_headers(bearer_token, cookie, base_url=base_url)
                resp = requests.get(
                    subs_base_url,
                    headers=headers,
                    params={"filter": f"key eq '{key}'", "limit": 5},
                    timeout=30
                )
                if resp.status_code == 200:
                    items = resp.json().get("items", [])
                    if items:
                        sub_id = items[0].get("id")
            except Exception as e:
                print(f"[CCS] Error looking up subscription key {key}: {e}")

            if not sub_id:
                results["failed"] += 1
                results["details"].append({"key": key, "success": False, "error": "Subscription key not found"})
                continue

            try:
                transfer_url = f"{subs_base_url}/{sub_id}/transfer"
                headers = make_headers(bearer_token, cookie, base_url=base_url)
                payload = {"destinationWorkspaceId": dest_workspace_id}

                resp = requests.post(transfer_url, headers=headers, json=payload, timeout=30)
                print(f"[CCS] Transfer subscription {key}: HTTP {resp.status_code} — {resp.text[:200]}")

                if resp.status_code in [200, 201, 204]:
                    results["successful"] += 1
                    results["details"].append({"key": key, "success": True, "status": "Transferred"})
                elif resp.status_code == 202:
                    results["successful"] += 1
                    results["details"].append({"key": key, "success": True, "status": "Processing — verify manually"})
                else:
                    error_msg = f"HTTP {resp.status_code}"
                    try:
                        err = resp.json()
                        error_msg = err.get("message", err.get("detail", str(err)))
                    except Exception:
                        error_msg = resp.text[:200] or error_msg
                    results["failed"] += 1
                    results["details"].append({"key": key, "success": False, "error": error_msg})

            except Exception as e:
                results["failed"] += 1
                results["details"].append({"key": key, "success": False, "error": str(e)})

            time.sleep(0.3)

    results["elapsed_seconds"] = round(time.time() - start_time, 2)
    return JSONResponse(content=results)


# ============================================================
# QUERY USERS (CCS-Manager session)
# ============================================================

@router.post("/query-users")
async def ccs_query_users(
    bearer_token: str = Form(...),
    cookie: str = Form(""),
    base_url: str = Form(API_BASE),
    file: UploadFile = File(...)
):
    """
    Query users by search string from a CSV file.
    Uses the support-assistant API.
    """
    start_time = time.time()
    content = await file.read()
    search_strings = parse_csv_column(
        content,
        ["Email", "email", "Search String", "search_string", "Search", "User", "Username", "username"]
    )

    if not search_strings:
        raise HTTPException(status_code=400, detail="No search strings/emails found in CSV")

    results = {"total": len(search_strings), "successful": 0, "failed": 0, "details": [], "elapsed_seconds": 0}

    use_aquila = is_aquila_url(base_url)
    if not use_aquila:
        raise HTTPException(status_code=400, detail="Query Users requires an Aquila session base URL")

    headers = make_headers(bearer_token, cookie, base_url=base_url)
    endpoint = f"{base_url}/support-assistant/v1alpha1/customers"

    for search_str in search_strings:
        print(f"[CCS] Querying user customers for: {search_str}")
        params = {
            "limit": 1000,
            "offset": 0,
            "username": search_str
        }
        
        try:
            resp = requests.get(endpoint, headers=headers, params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                customers = data.get("customers", [])
                if customers:
                    for cust in customers:
                        comp_name = cust.get("contact", {}).get("company_name", "")
                        created_by = cust.get("contact", {}).get("created_by", "")
                        cust_id = cust.get("customer_id", "")
                        acct_type = cust.get("account_type", "")
                        status = cust.get("account", {}).get("status", "")
                        msp_id = cust.get("msp_id", "")
                        region = cust.get("region", "")
                        
                        detail_str = f"Company: {comp_name} | ID: {cust_id} | Type: {acct_type} | Status: {status}"
                        results["details"].append({
                            "key": search_str, 
                            "success": True, 
                            "status": "Found", 
                            "detail": detail_str,
                            "raw": {
                                "company_name": comp_name,
                                "created_by": created_by,
                                "customer_id": cust_id,
                                "account_type": acct_type,
                                "status": status,
                                "msp_id": msp_id,
                                "region": region
                            }
                        })
                    results["successful"] += 1
                else:
                    results["failed"] += 1
                    results["details"].append({"key": search_str, "success": False, "error": "No mapped workspaces found"})
            else:
                error_msg = f"HTTP {resp.status_code}"
                try:
                    err = resp.json()
                    error_msg = err.get("message", err.get("detail", str(err)))
                except Exception:
                    error_msg = resp.text[:200] or error_msg
                results["failed"] += 1
                results["details"].append({"key": search_str, "success": False, "error": error_msg})
        except Exception as e:
            results["failed"] += 1
            results["details"].append({"key": search_str, "success": False, "error": str(e)})

        time.sleep(0.3)

    results["elapsed_seconds"] = round(time.time() - start_time, 2)
    return JSONResponse(content=results)


# ============================================================
# QUERY DEVICES (CCS-Manager session)
# ============================================================

def _query_single_device(serial: str, base_url: str, headers: dict) -> dict:
    """
    Synchronous helper: query a single device (lookup + detail).
    Returns a result dict for this serial.
    """
    try:
        # Step 1: Global lookup via activate-devices
        lookup_url = f"{base_url}/support-assistant/v1alpha1/activate-devices"
        lookup_params = {"serial_number": serial, "limit": 10}
        lookup_resp = requests.get(lookup_url, headers=headers, params=lookup_params, timeout=30)

        if lookup_resp.status_code != 200:
            return {"key": serial, "success": False, "error": f"Global lookup failed: HTTP {lookup_resp.status_code}"}

        lookup_data = lookup_resp.json()
        lookup_devices = lookup_data.get("devices", lookup_data.get("items", []))

        # Find matching device by serial
        matched_dev = None
        for dev in lookup_devices:
            sn = dev.get("serial_number") or dev.get("serialNumber", "")
            if sn.upper() == serial.upper():
                matched_dev = dev
                break

        if not matched_dev and len(lookup_devices) >= 1:
            matched_dev = lookup_devices[0]

        if not matched_dev:
            return {"key": serial, "success": False, "error": "Device not found in Global Search"}

        # Extract platform_customer_id
        customer_id = matched_dev.get("platform_customer_id", "") or matched_dev.get("customerId", "")
        if not customer_id:
            return {"key": serial, "success": False, "error": "Could not resolve platform_customer_id for device from search"}

        workspace_id = (
            matched_dev.get("workspace_id")
            or matched_dev.get("pcid")
            or matched_dev.get("platform_customer_id")
            or ""
        )
        mac_from_lookup = matched_dev.get("mac_address", "")

        # Step 2: Get detailed device info
        endpoint = f"{base_url}/support-assistant/v1alpha1/device/{serial}"
        params = {
            "devices_history_limit": 3,
            "devices_history_page": 0,
            "orders_limit": 3,
            "orders_page": 0,
            "platform_customer_id": customer_id
        }
        if mac_from_lookup:
            params["mac_address"] = mac_from_lookup

        resp = requests.get(endpoint, headers=headers, params=params, timeout=30)

        if resp.status_code == 200:
            data = resp.json()
            devices = data.get("devices", [])
            orders_data = data.get("orders", {})
            aop_orders = orders_data.get("aop_sales_order_data", [])
            order_info = aop_orders[0] if aop_orders else {}

            if devices:
                dev = devices[0]
                mac = dev.get("mac_address") or "N/A"
                part = dev.get("part_number") or ""
                model = dev.get("device_model") or "N/A"
                status = dev.get("status") or "N/A"

                folder = dev.get("folder") or {}
                folder_name = folder.get("folder_name") or "N/A"

                rule = dev.get("rule") or {}
                rule_name = rule.get("rule_name") or "None"

                dev_workspace_id = (
                    dev.get("workspace_id")
                    or dev.get("pcid")
                    or workspace_id
                    or customer_id
                )

                detail_str = f"MAC: {mac} | Model: {model} | Status: {status} | Folder: {folder_name} | Rule: {rule_name} | Workspace: {dev_workspace_id}"

                return {
                    "key": serial,
                    "success": True,
                    "status": "Found",
                    "detail": detail_str,
                    "raw": {
                        "mac_address": mac,
                        "part_number": part,
                        "device_model": model,
                        "status": status,
                        "platform_customer_id": customer_id,
                        "workspace_id": dev_workspace_id,
                        "folder_name": folder_name,
                        "rule_name": rule_name,
                        "order_obj_key": order_info.get("obj_key"),
                        "order_category": order_info.get("category"),
                        "order_pos_id": order_info.get("pos_id"),
                        "order_serial_number": order_info.get("serial_number"),
                        "order_mac_address": order_info.get("mac_address"),
                        "order_bill_to_name": order_info.get("bill_to_name"),
                        "order_end_user_name": order_info.get("end_user_name"),
                        "order_part_number": order_info.get("part_number"),
                        "order_part_description": order_info.get("part_description"),
                        "order_invoice_date": order_info.get("invoice_date"),
                        "order_ship_date": order_info.get("ship_date"),
                        "order_qty": order_info.get("qty"),
                        "order_ext_cost": order_info.get("ext_cost"),
                        "order_invoice_no": order_info.get("invoice_no"),
                        "order_order_no": order_info.get("order_no"),
                        "order_customer_po": order_info.get("customer_po"),
                        "order_line_no": order_info.get("line_no"),
                        "order_line_type": order_info.get("line_type"),
                        "order_zip_code": order_info.get("zip_code"),
                        "order_source": order_info.get("source"),
                        "order_status": order_info.get("status"),
                        "order_party_id": order_info.get("party_id"),
                        "order_country_party_id": order_info.get("country_party_id"),
                        "order_global_party_id": order_info.get("global_party_id"),
                        "order_created_at": order_info.get("created_at"),
                        "order_updated_at": order_info.get("updated_at")
                    }
                }
            else:
                err_msg = data.get("adi_device_history_data", {}).get("message", "No device detail returned")
                return {"key": serial, "success": False, "error": err_msg}
        else:
            error_msg = f"HTTP {resp.status_code}"
            try:
                err = resp.json()
                raw_msg = err.get("message", err.get("detail", str(err)))
                error_msg = str(raw_msg) if isinstance(raw_msg, (dict, list)) else raw_msg
            except Exception:
                error_msg = resp.text[:200] or error_msg
            return {"key": serial, "success": False, "error": error_msg}

    except Exception as e:
        return {"key": serial, "success": False, "error": str(e)}


@router.post("/query-devices")
async def ccs_query_devices(
    request: Request,
    bearer_token: str = Form(...),
    cookie: str = Form(""),
    base_url: str = Form(API_BASE),
    file: UploadFile = File(...)
):
    """
    Query detailed device configuration from Aquila support-assistant API.
    Auto-resolves the platform_customer_id from the serial number.
    Processes devices in concurrent batches of 250 for speed.
    Uses NDJSON StreamingResponse for live progress and abort support.
    """
    start_time = time.time()
    content = await file.read()
    serials = parse_csv_column(
        content,
        ["Serial Number", "SerialNumber", "Serial", "SN", "serial", "SERIAL", "mac", "MAC"]
    )

    if not serials:
        raise HTTPException(status_code=400, detail="No serial numbers/MACs found in CSV")

    use_aquila = is_aquila_url(base_url)
    if not use_aquila:
        raise HTTPException(status_code=400, detail="Query Devices requires an Aquila session base URL")

    headers = make_headers(bearer_token, cookie, base_url=base_url)

    BATCH_SIZE = 250
    MAX_WORKERS = 10   # concurrent threads per batch

    async def event_generator():
        results = {"total": len(serials), "successful": 0, "failed": 0, "details": [], "elapsed_seconds": 0}
        yield json.dumps({"type": "progress", "current": 0, "total": len(serials), "message": "Starting query..."}) + "\n"

        processed = 0
        loop = asyncio.get_event_loop()

        for batch_start in range(0, len(serials), BATCH_SIZE):
            if await request.is_disconnected():
                print(f"[CCS] Query devices cancelled by client at {processed}/{len(serials)}")
                break

            batch = serials[batch_start:batch_start + BATCH_SIZE]
            batch_num = (batch_start // BATCH_SIZE) + 1
            total_batches = (len(serials) + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"[CCS] Processing batch {batch_num}/{total_batches} ({len(batch)} devices)")

            yield json.dumps({"type": "progress", "current": processed, "total": len(serials), "message": f"Batch {batch_num}/{total_batches} — querying {len(batch)} devices concurrently..."}) + "\n"

            # Run the batch concurrently using ThreadPoolExecutor
            batch_results = await loop.run_in_executor(
                None,
                lambda b=batch: _run_device_batch(b, base_url, headers, MAX_WORKERS)
            )

            # Collect results from this batch
            for res in batch_results:
                results["details"].append(res)
                if res["success"]:
                    results["successful"] += 1
                else:
                    results["failed"] += 1

            processed += len(batch)
            yield json.dumps({"type": "progress", "current": processed, "total": len(serials), "message": f"Batch {batch_num}/{total_batches} complete"}) + "\n"

            # Small pause between batches to be respectful to the API
            if batch_start + BATCH_SIZE < len(serials):
                await asyncio.sleep(1.0)

        results["elapsed_seconds"] = round(time.time() - start_time, 2)
        yield json.dumps({"type": "complete", "results": results}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


def _run_device_batch(serials: list, base_url: str, headers: dict, max_workers: int) -> list:
    """Run a batch of device queries concurrently using ThreadPoolExecutor."""
    results = [None] * len(serials)  # preserve order
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(_query_single_device, serial, base_url, headers): idx
            for idx, serial in enumerate(serials)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = {"key": serials[idx], "success": False, "error": str(e)}
    return results


# ============================================================
# UNCLAIM DEVICES (CCS-Manager session)
# ============================================================

@router.post("/unclaim-devices")
async def ccs_unclaim_devices(
    bearer_token: str = Form(...),
    cookie: str = Form(""),
    workspace_id: str = Form(...),
    base_url: str = Form(API_BASE),
    dry_run: bool = Form(False),
    file: UploadFile = File(...)
):
    """
    Unclaim devices in bulk from a workspace (return to factory).
    Replicates the exact logic of Transfer Devices, but forces destination to Aruba-Factory-CCS-Platform.
    """
    start_time = time.time()
    content = await file.read()
    serials = parse_csv_column(
        content,
        ["Serial Number", "SerialNumber", "Serial", "SN", "serial", "SERIAL"]
    )

    if not serials:
        raise HTTPException(status_code=400, detail="No serial numbers found in CSV")

    results = {"total": len(serials), "successful": 0, "failed": 0, "details": [], "elapsed_seconds": 0}
    use_aquila = is_aquila_url(base_url)

    dest_workspace_id = "Aruba-Factory-CCS-Platform"
    folder = "default"

    # ── Dry-Run Mode: lookup only, no actual unclaim ────────────────────────────
    if dry_run:
        print(f"[CCS] DRY-RUN unclaim-devices: {len(serials)} serials from {workspace_id}")
        h = make_headers(bearer_token, cookie, "application/json", base_url)
        for serial in serials:
            try:
                if use_aquila:
                    lurl = f"{base_url}/support-assistant/v1alpha1/activate-devices"
                    r = requests.get(lurl, headers=h, params={"serial_number": serial, "limit": 5}, timeout=30)
                    if r.status_code == 200:
                        items = r.json().get("devices", r.json().get("items", []))
                        m = next((d for d in items if d.get("serial_number", "").upper() == serial.upper()), items[0] if items else None)
                        if m:
                            current_ws = m.get("platform_customer_id", m.get("pcid", "Unknown"))
                            results["successful"] += 1
                            results["details"].append({
                                "serial": serial, "success": True, "status": "Would Unclaim",
                                "detail": f"Would remove from WS: {current_ws} → Factory | {m.get('device_model','?')} | {m.get('status','?')}"
                            })
                        else:
                            results["failed"] += 1
                            results["details"].append({"serial": serial, "success": False, "error": "Not found in global search"})
                    else:
                        results["failed"] += 1
                        results["details"].append({"serial": serial, "success": False, "error": f"Lookup HTTP {r.status_code}"})
                else:
                    did = get_device_id_by_serial(bearer_token, cookie, serial, base_url)
                    if did:
                        results["successful"] += 1
                        results["details"].append({"serial": serial, "success": True, "status": "Would Unclaim", "detail": f"Device {did} → return to Factory"})
                    else:
                        results["failed"] += 1
                        results["details"].append({"serial": serial, "success": False, "error": "Device not found"})
            except Exception as e:
                results["failed"] += 1
                results["details"].append({"serial": serial, "success": False, "error": str(e)})
            time.sleep(0.15)
        results["elapsed_seconds"] = round(time.time() - start_time, 2)
        return JSONResponse(content={**results, "dry_run": True})

    if use_aquila:
        # ── Real support-assistant endpoint ─────────────────────────────
        endpoint = f"{base_url}/support-assistant/v1alpha1/devices-to-customer"
        headers = make_headers(bearer_token, cookie, "application/json", base_url)

        # 1. Fetch folder ID dynamically based on folder name
        folder_id = ""
        try:
            folder_url = f"{base_url}/support-assistant/v1alpha1/user-folders"
            f_params = {"limit": 50, "page": 0, "platform_customer_id": dest_workspace_id}
            print(f"[CCS] Fetching folders for {dest_workspace_id}...")
            f_resp = requests.get(folder_url, headers=headers, params=f_params, timeout=15)
            if f_resp.status_code == 200:
                f_data = f_resp.json()
                items = f_data if isinstance(f_data, list) else f_data.get("items", f_data.get("folders", f_data.get("data", [])))
                for f in items:
                    name = f.get("name", f.get("folder_name", f.get("folderName", "")))
                    if name.lower() == folder.lower():
                        folder_id = f.get("id", f.get("folder_id", f.get("folderId", "")))
                        break
                # Fallback to first folder if exact match not found but folders exist
                if not folder_id and items:
                    folder_id = items[0].get("id", items[0].get("folder_id", items[0].get("folderId", "")))
                    folder = items[0].get("name", items[0].get("folder_name", folder))
        except Exception as e:
            print(f"[CCS] Could not fetch folder ID: {e}")

        print(f"[CCS] Using folder: {folder} (ID: {folder_id})")

        fid: int = 0
        if folder_id:
            try:
                fid = int(folder_id)
            except ValueError:
                pass

        batch_size = 250

        for i in range(0, len(serials), batch_size):
            batch = serials[i:i+batch_size]
            
            base_payload = {
                "folder_name": folder,
                "folder_id": fid,
                "platform_customer_id": dest_workspace_id
            }
            if not fid:
                base_payload.pop("folder_id", None)

            _transfer_batch_with_retry(headers, endpoint, base_payload, batch, results)

            time.sleep(1.0)

    else:
        # ── Public GreenLake API fallback ───────────────────────────────
        for serial in serials:
            device_id = get_device_id_by_serial(bearer_token, cookie, serial, base_url)
            if not device_id:
                results["failed"] += 1
                results["details"].append({"serial": serial, "success": False, "error": "Device not found"})
                continue
            try:
                patch_url = f"{base_url}/devices/v1beta1/devices"
                headers = make_headers(bearer_token, cookie, "application/merge-patch+json", base_url)
                payload = {"workspace": {"id": dest_workspace_id}}
                resp = requests.patch(
                    patch_url, headers=headers, params={"id": device_id}, json=payload, timeout=30
                )
                print(f"[CCS] GLP Unclaim {serial}: HTTP {resp.status_code} — {resp.text[:200]}")
                if resp.status_code in [200, 202]:
                    results["successful"] += 1
                    results["details"].append({"serial": serial, "success": True, "status": "Transferred"})
                else:
                    error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    results["failed"] += 1
                    results["details"].append({"serial": serial, "success": False, "error": error_msg})
            except Exception as e:
                results["failed"] += 1
                results["details"].append({"serial": serial, "success": False, "error": str(e)})
            time.sleep(0.3)

    results["elapsed_seconds"] = round(time.time() - start_time, 2)
    return JSONResponse(content=results)


# ============================================================
# CLAIM DEVICES FROM FACTORY (CCS-Manager session)
# ============================================================

@router.post("/claim-devices")
async def ccs_claim_devices(
    bearer_token: str = Form(...),
    cookie: str = Form(""),
    workspace_id: str = Form(...),
    folder: str = Form("default"),
    base_url: str = Form(API_BASE),
    dry_run: bool = Form(False),
    file: UploadFile = File(...)
):
    """
    Claim devices from Aruba Factory into a specified workspace.
    Replicates the exact logic of Transfer Devices (source is implicit, dest is workspace_id).
    """
    start_time = time.time()
    content = await file.read()
    serials = parse_csv_column(
        content,
        ["Serial Number", "SerialNumber", "Serial", "SN", "serial", "SERIAL"]
    )

    if not serials:
        raise HTTPException(status_code=400, detail="No serial numbers found in CSV")

    results = {"total": len(serials), "successful": 0, "failed": 0, "details": [], "elapsed_seconds": 0}
    use_aquila = is_aquila_url(base_url)

    dest_workspace_id = workspace_id

    # ── Dry-Run Mode: lookup only, no actual claim ──────────────────────────────
    if dry_run:
        print(f"[CCS] DRY-RUN claim-devices: {len(serials)} serials → {workspace_id}")
        h = make_headers(bearer_token, cookie, "application/json", base_url)
        for serial in serials:
            try:
                if use_aquila:
                    lurl = f"{base_url}/support-assistant/v1alpha1/activate-devices"
                    r = requests.get(lurl, headers=h, params={"serial_number": serial, "limit": 5}, timeout=30)
                    if r.status_code == 200:
                        items = r.json().get("devices", r.json().get("items", []))
                        m = next((d for d in items if d.get("serial_number", "").upper() == serial.upper()), items[0] if items else None)
                        if m:
                            current_ws = m.get("platform_customer_id", m.get("pcid", "Factory"))
                            results["successful"] += 1
                            results["details"].append({
                                "serial": serial, "success": True, "status": "Would Claim",
                                "detail": f"Currently at: {current_ws} → Claim into: {workspace_id} | {m.get('device_model','?')}"
                            })
                        else:
                            results["failed"] += 1
                            results["details"].append({"serial": serial, "success": False, "error": "Not found in global search"})
                    else:
                        results["failed"] += 1
                        results["details"].append({"serial": serial, "success": False, "error": f"Lookup HTTP {r.status_code}"})
                else:
                    did = get_device_id_by_serial(bearer_token, cookie, serial, base_url)
                    if did:
                        results["successful"] += 1
                        results["details"].append({"serial": serial, "success": True, "status": "Would Claim", "detail": f"Device {did} → claim into {workspace_id}"})
                    else:
                        results["failed"] += 1
                        results["details"].append({"serial": serial, "success": False, "error": "Device not found"})
            except Exception as e:
                results["failed"] += 1
                results["details"].append({"serial": serial, "success": False, "error": str(e)})
            time.sleep(0.15)
        results["elapsed_seconds"] = round(time.time() - start_time, 2)
        return JSONResponse(content={**results, "dry_run": True})

    if use_aquila:
        # ── Real support-assistant endpoint ─────────────────────────────
        endpoint = f"{base_url}/support-assistant/v1alpha1/devices-to-customer"
        headers = make_headers(bearer_token, cookie, "application/json", base_url)

        # 1. Fetch folder ID dynamically based on folder name
        folder_id = ""
        try:
            folder_url = f"{base_url}/support-assistant/v1alpha1/user-folders"
            f_params = {"limit": 50, "page": 0, "platform_customer_id": dest_workspace_id}
            print(f"[CCS] Fetching folders for {dest_workspace_id}...")
            f_resp = requests.get(folder_url, headers=headers, params=f_params, timeout=15)
            if f_resp.status_code == 200:
                f_data = f_resp.json()
                items = f_data if isinstance(f_data, list) else f_data.get("items", f_data.get("folders", f_data.get("data", [])))
                for f in items:
                    name = f.get("name", f.get("folder_name", f.get("folderName", "")))
                    if name.lower() == folder.lower():
                        folder_id = f.get("id", f.get("folder_id", f.get("folderId", "")))
                        break
                # Fallback to first folder if exact match not found but folders exist
                if not folder_id and items:
                    folder_id = items[0].get("id", items[0].get("folder_id", items[0].get("folderId", "")))
                    folder = items[0].get("name", items[0].get("folder_name", folder))
        except Exception as e:
            print(f"[CCS] Could not fetch folder ID: {e}")

        print(f"[CCS] Using folder: {folder} (ID: {folder_id})")

        fid: int = 0
        if folder_id:
            try:
                fid = int(folder_id)
            except ValueError:
                pass

        batch_size = 250

        for i in range(0, len(serials), batch_size):
            batch = serials[i:i+batch_size]
            
            base_payload = {
                "folder_name": folder,
                "folder_id": fid,
                "platform_customer_id": dest_workspace_id
            }
            if not fid:
                base_payload.pop("folder_id", None)

            _transfer_batch_with_retry(headers, endpoint, base_payload, batch, results)

            time.sleep(1.0)

    else:
        # ── Public GreenLake API fallback ───────────────────────────────
        for serial in serials:
            device_id = get_device_id_by_serial(bearer_token, cookie, serial, base_url)
            if not device_id:
                results["failed"] += 1
                results["details"].append({"serial": serial, "success": False, "error": "Device not found"})
                continue
            try:
                patch_url = f"{base_url}/devices/v1beta1/devices"
                headers = make_headers(bearer_token, cookie, "application/merge-patch+json", base_url)
                payload = {"workspace": {"id": dest_workspace_id}}
                resp = requests.patch(
                    patch_url, headers=headers, params={"id": device_id}, json=payload, timeout=30
                )
                print(f"[CCS] GLP Claim {serial}: HTTP {resp.status_code} — {resp.text[:200]}")
                if resp.status_code in [200, 202]:
                    results["successful"] += 1
                    results["details"].append({"serial": serial, "success": True, "status": "Transferred"})
                else:
                    error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    results["failed"] += 1
                    results["details"].append({"serial": serial, "success": False, "error": error_msg})
            except Exception as e:
                results["failed"] += 1
                results["details"].append({"serial": serial, "success": False, "error": str(e)})
            time.sleep(0.3)

    results["elapsed_seconds"] = round(time.time() - start_time, 2)
    return JSONResponse(content=results)


# ============================================================
# SNAPSHOT DEVICES — read-only current state capture
# ============================================================

@router.post("/snapshot-devices")
async def ccs_snapshot_devices(
    bearer_token: str = Form(...),
    cookie: str = Form(""),
    base_url: str = Form(API_BASE),
    file: UploadFile = File(...)
):
    """
    Read-only: returns current device state (workspace, model, status).
    Uses activate-devices lookup — no changes made.
    """
    content = await file.read()
    serials = parse_csv_column(
        content,
        ["Serial Number", "SerialNumber", "Serial", "SN", "serial", "SERIAL"]
    )
    if not serials:
        raise HTTPException(status_code=400, detail="No serial numbers found in CSV")

    use_aquila = is_aquila_url(base_url)
    if not use_aquila:
        raise HTTPException(status_code=400, detail="Snapshot requires an Aquila session base URL")

    headers = make_headers(bearer_token, cookie, base_url=base_url)
    snapshot = []

    for serial in serials:
        try:
            lookup_url = f"{base_url}/support-assistant/v1alpha1/activate-devices"
            resp = requests.get(lookup_url, headers=headers, params={"serial_number": serial, "limit": 5}, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("devices", data.get("items", []))
                matched = next(
                    (d for d in items if d.get("serial_number", "").upper() == serial.upper()),
                    items[0] if items else None
                )
                if matched:
                    snapshot.append({
                        "serial_number": serial,
                        "platform_customer_id": matched.get("platform_customer_id", matched.get("pcid", "")),
                        "device_model": matched.get("device_model", matched.get("model", "")),
                        "part_number": matched.get("part_number", ""),
                        "mac_address": matched.get("mac_address", ""),
                        "status": matched.get("status", ""),
                        "found": True
                    })
                else:
                    snapshot.append({"serial_number": serial, "found": False, "error": "Not found in global search"})
            else:
                snapshot.append({"serial_number": serial, "found": False, "error": f"HTTP {resp.status_code}"})
        except Exception as e:
            snapshot.append({"serial_number": serial, "found": False, "error": str(e)})
        time.sleep(0.15)

    return JSONResponse(content={
        "snapshot": snapshot,
        "total": len(serials),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    })


# ============================================================
# SNAPSHOT USERS — read-only workspace membership capture
# ============================================================

@router.post("/snapshot-users")
async def ccs_snapshot_users(
    bearer_token: str = Form(...),
    cookie: str = Form(""),
    base_url: str = Form(API_BASE),
    workspace_id: str = Form(""),
    file: UploadFile = File(...)
):
    """
    Read-only: returns which workspaces each user currently belongs to.
    No deletions made.
    """
    content = await file.read()
    usernames = parse_csv_column(
        content,
        ["Email", "email", "Username", "username", "User", "Search String", "search_string"]
    )
    if not usernames:
        raise HTTPException(status_code=400, detail="No emails/usernames found in CSV")

    use_aquila = is_aquila_url(base_url)
    if not use_aquila:
        raise HTTPException(status_code=400, detail="Snapshot requires an Aquila session base URL")

    headers = make_headers(bearer_token, cookie, base_url=base_url)
    snapshot = []

    for username in usernames:
        if workspace_id:
            snapshot.append({
                "username": username, "workspace_id": workspace_id,
                "company_name": "", "account_type": "", "status": "", "found": True
            })
        else:
            try:
                query_url = f"{base_url}/support-assistant/v1alpha1/customers"
                resp = requests.get(
                    query_url, headers=headers,
                    params={"limit": 1000, "offset": 0, "username": username},
                    timeout=30
                )
                if resp.status_code == 200:
                    customers = resp.json().get("customers", [])
                    if customers:
                        for cust in customers:
                            snapshot.append({
                                "username": username,
                                "workspace_id": cust.get("customer_id", ""),
                                "company_name": cust.get("contact", {}).get("company_name", ""),
                                "account_type": cust.get("account_type", ""),
                                "status": cust.get("account", {}).get("status", ""),
                                "found": True
                            })
                    else:
                        snapshot.append({"username": username, "found": False, "error": "No workspaces found"})
                else:
                    snapshot.append({"username": username, "found": False, "error": f"HTTP {resp.status_code}"})
            except Exception as e:
                snapshot.append({"username": username, "found": False, "error": str(e)})
        time.sleep(0.2)

    return JSONResponse(content={
        "snapshot": snapshot,
        "total": len(usernames),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    })


# ============================================================
# QUERY ORDERS (CCS-Manager session)
# ============================================================

@router.post("/query-orders")
async def ccs_query_orders(
    bearer_token: str = Form(...),
    cookie: str = Form(""),
    base_url: str = Form(API_BASE),
    file: UploadFile = File(...)
):
    """
    Query detailed order information (Subscription Keys, SKUs, etc) using Order Numbers from a CSV file.
    (Requires Aquila session)
    """
    start_time = time.time()
    content = await file.read()
    order_numbers = parse_csv_column(
        content,
        ["Order Number", "OrderNumber", "Order", "order_number", "order", "Quote", "quote"]
    )

    if not order_numbers:
        raise HTTPException(status_code=400, detail="No order numbers found in CSV")

    results = {"total": len(order_numbers), "successful": 0, "failed": 0, "details": [], "elapsed_seconds": 0}

    use_aquila = is_aquila_url(base_url)
    if not use_aquila:
        raise HTTPException(status_code=400, detail="Query Orders requires an Aquila session base URL")

    headers = make_headers(bearer_token, cookie, base_url=base_url)

    for order_num in order_numbers:
        print(f"[CCS] Querying order: {order_num}")
        endpoint = f"{base_url}/support-assistant/v1alpha1/orders-detail/{order_num}"

        try:
            resp = requests.get(endpoint, headers=headers, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                
                # Check if we got a list or a dict containing items
                items = data if isinstance(data, list) else data.get("items", data.get("orders", []))
                
                if items:
                    keys_found = 0
                    for item in items:
                        entitlements = item.get("entitlements", [])
                        for ent in entitlements:
                            product = ent.get("product", {})
                            sku = product.get("sku", "")
                            desc = product.get("description", "")
                            
                            licenses = ent.get("licenses", [])
                            for lic in licenses:
                                sub_key = lic.get("subscription_key", "")
                                if sub_key:
                                    qty = lic.get("qty", "")
                                    avail_qty = lic.get("available_qty", "")
                                    capacity = lic.get("capacity", "")
                                    
                                    detail_str = f"Key: {sub_key} | SKU: {sku} | Qty: {qty} ({avail_qty} avail)"
                                    
                                    results["details"].append({
                                        "key": order_num,
                                        "success": True,
                                        "status": "Found",
                                        "detail": detail_str,
                                        "raw": {
                                            "subscription_key": sub_key,
                                            "sku": sku,
                                            "description": desc,
                                            "qty": qty,
                                            "available_qty": avail_qty,
                                            "capacity": capacity
                                        }
                                    })
                                    keys_found += 1
                                    
                    if keys_found > 0:
                        results["successful"] += 1
                    else:
                        results["failed"] += 1
                        results["details"].append({"key": order_num, "success": False, "error": "Order found but no subscription keys present"})
                else:
                    results["failed"] += 1
                    results["details"].append({"key": order_num, "success": False, "error": "No items in order response"})
            else:
                error_msg = f"HTTP {resp.status_code}"
                try:
                    err = resp.json()
                    raw_msg = err.get("message", err.get("detail", str(err)))
                    error_msg = str(raw_msg) if isinstance(raw_msg, (dict, list)) else raw_msg
                except Exception:
                    error_msg = resp.text[:200] or error_msg
                results["failed"] += 1
                results["details"].append({"key": order_num, "success": False, "error": error_msg})
        except Exception as e:
            results["failed"] += 1
            results["details"].append({"key": order_num, "success": False, "error": str(e)})

        time.sleep(0.3)

    results["elapsed_seconds"] = round(time.time() - start_time, 2)
    return JSONResponse(content=results)


# ============================================================
# DELETE USERS (CCS-Manager session)
# ============================================================

@router.post("/delete-users")
async def ccs_delete_users(
    request: Request,
    bearer_token: str = Form(...),
    cookie: str = Form(""),
    base_url: str = Form(API_BASE),
    workspace_id: str = Form(""),
    dry_run: bool = Form(False),
    file: UploadFile = File(...),
    skip_file: UploadFile = File(None)
):
    """
    Bulk delete (disassociate) users from a workspace via a CSV file.
    Uses NDJSON StreamingResponse for live progress and abort support.
    """
    start_time = time.time()
    content = await file.read()
    usernames = parse_csv_column(
        content,
        ["Email", "email", "Search String", "search_string", "Search", "User", "Username", "username"]
    )

    if not usernames:
        raise HTTPException(status_code=400, detail="No emails/usernames found in CSV")

    use_aquila = is_aquila_url(base_url)
    if not use_aquila:
        raise HTTPException(status_code=400, detail="Delete Users requires an Aquila session base URL")

    headers = make_headers(bearer_token, cookie, base_url=base_url)
    endpoint = f"{base_url}/support-assistant/v1alpha1/user"

    skip_workspaces = set()
    if skip_file and skip_file.filename:
        skip_content = await skip_file.read()
        if skip_content:
            skip_list = parse_csv_column(
                skip_content,
                ["Workspace ID", "Workspace", "customer_id", "Customer ID", "Search String", "Search", "ID", "id"]
            )
            skip_workspaces = {wid.strip().lower().replace("-", "") for wid in skip_list if wid.strip()}

    async def event_generator():
        results = {"total": len(usernames), "successful": 0, "failed": 0, "details": [], "elapsed_seconds": 0}
        yield json.dumps({"type": "progress", "current": 0, "total": len(usernames), "message": "Starting dry-run simulation..." if dry_run else "Starting deletion..."}) + "\n"

        for idx, username in enumerate(usernames):
            if await request.is_disconnected():
                print(f"[CCS] Delete users cancelled by client at {idx}/{len(usernames)}")
                break

            target_workspaces = []
            if workspace_id:
                target_workspaces.append(workspace_id)
            else:
                # Auto-discover all workspaces for this user
                query_url = f"{base_url}/support-assistant/v1alpha1/customers"
                params = {"limit": 1000, "offset": 0, "username": username}
                try:
                    resp = requests.get(query_url, headers=headers, params=params, timeout=30)
                    if resp.status_code == 200:
                        for cust in resp.json().get("customers", []):
                            if cid := cust.get("customer_id"): 
                                target_workspaces.append(cid)
                except Exception as e:
                    print(f"[CCS] Error auto-discovering user workspace {username}: {e}")

            if not target_workspaces:
                results["failed"] += 1
                results["details"].append({"key": username, "success": False, "error": "User not found in any workspaces"})
                yield json.dumps({"type": "progress", "current": idx + 1, "total": len(usernames), "message": f"Processed {username}"}) + "\n"
                continue

            for wid in target_workspaces:
                wid_clean = wid.replace("-", "").lower()

                if wid_clean in skip_workspaces:
                    print(f"[CCS] Skip list triggered: Skipping deletion of {username} from workspace ({wid})")
                    results["successful"] += 1
                    results["details"].append({"key": username, "success": True, "status": "Skipped", "detail": f"User skip list workspace ({wid})"})
                    continue

                if username.lower().endswith("@hpe.com") and wid_clean == "409bbcfa127611ec963d36ef5c5682ad":
                    print(f"[CCS] Safeguard triggered: Skipping deletion of {username} from HPE GreenLake Support workspace ({wid})")
                    results["successful"] += 1
                    results["details"].append({"key": username, "success": True, "status": "Skipped", "detail": f"Protected: @hpe.com employee in {wid}"})
                    continue

                payload = {"username": username, "customer_id": wid}

                try:
                    if dry_run:
                        print(f"[CCS] DRY-RUN: Would delete {username} from workspace {wid}")
                        results["successful"] += 1
                        results["details"].append({"key": username, "success": True, "status": "Would Delete", "detail": f"Would be removed from workspace {wid}"})
                    else:
                        print(f"[CCS] Deleting user: {username} from workspace: {wid}")
                        resp = requests.delete(endpoint, headers=headers, json=payload, timeout=30)
                        if resp.status_code in [200, 201, 204]:
                            results["successful"] += 1
                            detail_str = f"Deleted from {wid}"
                            try:
                                api_msg = resp.json().get("message", "")
                                if api_msg: detail_str = f"{api_msg} ({wid})"
                            except Exception:
                                pass
                            results["details"].append({"key": username, "success": True, "status": "Success", "detail": detail_str})
                        else:
                            error_msg = f"HTTP {resp.status_code}"
                            try:
                                err = resp.json()
                                error_msg = err.get("message", err.get("detail", str(err)))
                            except Exception:
                                error_msg = resp.text[:200] or error_msg
                            results["failed"] += 1
                            results["details"].append({"key": username, "success": False, "error": f"{error_msg} ({wid})"})
                except Exception as e:
                    results["failed"] += 1
                    results["details"].append({"key": username, "success": False, "error": f"{str(e)} ({wid})"})

            yield json.dumps({"type": "progress", "current": idx + 1, "total": len(usernames), "message": f"Processed {username}"}) + "\n"
            await asyncio.sleep(0.3)

        results["elapsed_seconds"] = round(time.time() - start_time, 2)
        yield json.dumps({"type": "complete", "results": results, "dry_run": dry_run}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


# ============================================================
# AUDIT CUSTOMER APP IDs (CCS-Manager session / Aquila)
# ============================================================

def _get_provisions(base_url: str, headers: dict, platform_customer_id: str) -> list:
    """
    Fetch all app provisions for a given workspace (platform_customer_id).
    Returns a list of dicts with at least an 'app_id' key.
    Paginates automatically up to 500 items.
    """
    provisions = []
    offset = 0
    limit = 50
    while True:
        url = f"{base_url}/support-assistant/v1alpha1/customer-provisions"
        params = {
            "limit": limit,
            "offset": offset,
            "platform_customer_id": platform_customer_id,
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            print(f"[CCS] Provisions for {platform_customer_id}: HTTP {resp.status_code}")
            if resp.status_code != 200:
                print(f"[CCS] Provisions error body: {resp.text[:300]}")
                break
            data = resp.json()

            # Log keys + first item to understand the response schema (once per workspace)
            if offset == 0:
                top_keys = list(data.keys()) if isinstance(data, dict) else f"LIST len={len(data)}"
                print(f"[CCS] Provisions response keys: {top_keys}")
                print(f"[CCS] Provisions raw[:800]: {str(data)[:800]}")

            # Try every plausible top-level field name
            if isinstance(data, list):
                items = data
            else:
                items = (
                    data.get("provisions")
                    or data.get("customer_provisions")
                    or data.get("applications")
                    or data.get("app_provisions")
                    or data.get("items")
                    or data.get("data")
                    or data.get("results")
                    or []
                )

            # Log the first provision item so we can see its structure
            if offset == 0 and items:
                print(f"[CCS] First provision item keys: {list(items[0].keys()) if isinstance(items[0], dict) else items[0]}")
                print(f"[CCS] First provision item sample: {str(items[0])[:400]}")

            if not items:
                break
            provisions.extend(items)
            if len(items) < limit:
                break
            offset += limit
        except Exception as e:
            print(f"[CCS] Error fetching provisions for {platform_customer_id}: {e}")
            break
    return provisions


def _get_tenants(base_url: str, headers: dict, msp_customer_id: str) -> list:
    """
    Fetch all tenants for an MSP workspace.
    Returns a list of tenant dicts; each should include a platform_customer_id for the tenant.
    """
    tenants = []
    offset = 0
    limit = 50
    while True:
        url = f"{base_url}/support-assistant/v1alpha1/tenants"
        params = {
            "limit": limit,
            "offset": offset,
            "platform_customer_id": msp_customer_id,
        }
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            print(f"[CCS] Tenants for MSP {msp_customer_id}: HTTP {resp.status_code}")
            if resp.status_code != 200:
                print(f"[CCS] Tenant API error body: {resp.text[:400]}")
                break
            data = resp.json()
            # Log the full top-level keys so we can see what field name the API uses
            top_keys = list(data.keys()) if isinstance(data, dict) else f"LIST len={len(data)}"
            print(f"[CCS] Tenant API response keys: {top_keys}  | raw[:400]: {str(data)[:400]}")

            # Try every plausible field name the Aquila API might use
            if isinstance(data, list):
                items = data
            else:
                items = (
                    data.get("tenants")
                    or data.get("tenant_customers")
                    or data.get("tenant_list")
                    or data.get("customers")
                    or data.get("items")
                    or data.get("data")
                    or data.get("results")
                    or []
                )
                # Last resort: if still empty but only one key and its value is a list, use that
                if not items and isinstance(data, dict):
                    for v in data.values():
                        if isinstance(v, list) and len(v) > 0:
                            items = v
                            print(f"[CCS] Using fallback tenant list from first list-valued key")
                            break

            print(f"[CCS] Tenants found in this page: {len(items)}")
            if not items:
                break
            tenants.extend(items)
            if len(items) < limit:
                break
            offset += limit
        except Exception as e:
            print(f"[CCS] Error fetching tenants for {msp_customer_id}: {e}")
            break
    return tenants


def _extract_app_ids(provision: dict) -> list:
    """
    Extract ALL plausible application/service IDs from a customer-provisions item.
    Returns a list of unique ID strings rather than just the first one found,
    as some records contain different IDs in different fields.
    """
    ids = set()
    # --- Flat fields ---
    for key in ("app_id", "application_id", "customer_application_id", "application_customer_id",
                "service_id", "appId", "app_instance_id", "provision_id",
                "instance_id", "application_instance_name"):
        val = provision.get(key)
        if val and isinstance(val, str):
            ids.add(val.strip())

    # --- Nested: provision["application"]["id"] or provision["app"]["id"] ---
    for nested_key in ("application", "app", "service", "product"):
        nested = provision.get(nested_key)
        if isinstance(nested, dict):
            for id_key in ("id", "app_id", "application_id", "instance_id", "appId", "customer_id", "application_customer_id"):
                val = nested.get(id_key)
                if val and isinstance(val, str):
                    ids.add(val.strip())

    return list(ids)


@router.post("/audit-customer-apps")
async def ccs_audit_customer_apps(
    bearer_token: str = Form(...),
    cookie: str = Form(""),
    base_url: str = Form(API_BASE),
    file: UploadFile = File(...),      # CSV of search strings (customer name / email / ID)
    ref_file: UploadFile = File(...)   # CSV of reference app_ids to compare against
):
    """
    For each customer search string:
      1. Query /support-assistant/v1alpha1/customers to find matching workspaces.
      2. For each workspace, fetch customer-provisions to collect app_ids.
      3. If the workspace is an MSP, also fetch tenants and their provisions.
      4. Compare all collected app_ids against the reference list from ref_file.
    Returns per-workspace results showing matched and missing app IDs.
    Requires an Aquila session base URL.
    """
    start_time = time.time()

    use_aquila = is_aquila_url(base_url)
    if not use_aquila:
        raise HTTPException(status_code=400, detail="Audit Customer Apps requires an Aquila session base URL")

    # ── Parse search strings CSV ────────────────────────────────────────────
    content = await file.read()
    search_strings = parse_csv_column(
        content,
        ["Search String", "search_string", "Customer", "customer", "Email", "email",
         "ID", "id", "Company", "company", "Name", "name"]
    )
    if not search_strings:
        raise HTTPException(status_code=400, detail="No search strings found in CSV (expected a column: Search String, Customer, Email, or ID)")

    # ── Parse reference app IDs CSV ─────────────────────────────────────────
    ref_content = await ref_file.read()
    ref_app_ids_raw = parse_csv_column(
        ref_content,
        ["App ID", "app_id", "Application ID", "application_id",
         "AppID", "Service ID", "service_id", "ID", "id"]
    )
    # Normalise to a set (lower-case, stripped) for fast lookup
    reference_set = {aid.strip().lower() for aid in ref_app_ids_raw if aid.strip()}
    print(f"[CCS] Audit: Parsed reference IDs: {reference_set}")
    if not reference_set:
        raise HTTPException(status_code=400, detail="No app IDs found in reference CSV (expected a column: App ID, Application ID, or id)")

    headers = make_headers(bearer_token, cookie, base_url=base_url)
    customers_endpoint = f"{base_url}/support-assistant/v1alpha1/customers"

    results = {
        "total": 0,
        "successful": 0,
        "failed": 0,
        "details": [],
        "elapsed_seconds": 0,
        "reference_count": len(reference_set),
    }

    def process_search_str(search_str: str):
        print(f"[CCS] Audit: searching customers for '{search_str}'")
        res_details = []
        try:
            resp = requests.get(
                customers_endpoint,
                headers=headers,
                params={"limit": 10, "offset": 0, "search_string": search_str},
                timeout=30,
            )
        except Exception as e:
            return {"failed": 1, "total": 0, "successful": 0, "details": [{"key": search_str, "success": False, "error": str(e)}]}

        if resp.status_code != 200:
            error_msg = f"HTTP {resp.status_code}"
            try:
                err = resp.json()
                error_msg = err.get("message", err.get("detail", str(err)))
            except Exception:
                error_msg = resp.text[:200] or error_msg
            return {"failed": 1, "total": 0, "successful": 0, "details": [{"key": search_str, "success": False, "error": error_msg}]}

        customers = resp.json().get("customers", [])
        if not customers:
            return {"failed": 1, "total": 0, "successful": 0, "details": [{"key": search_str, "success": False, "error": "No customers found for this search string"}]}

        stats = {"failed": 0, "total": 0, "successful": 0, "details": []}
        
        # ── 2. For each matched workspace, gather provisions ────────────────
        for cust in customers:
            stats["total"] += 1
            cust_id = cust.get("customer_id", "")
            comp_name = cust.get("contact", {}).get("company_name", search_str)
            acct_type = cust.get("account_type", "")
            region = cust.get("region", "")

            if not cust_id:
                stats["failed"] += 1
                stats["details"].append({
                    "key": search_str,
                    "success": False,
                    "error": "Customer found but missing customer_id",
                })
                continue

            collected_app_ids = set()

            # Direct provisions
            provisions = _get_provisions(base_url, headers, cust_id)
            for p in provisions:
                aids = _extract_app_ids(p)
                for aid in aids:
                    collected_app_ids.add(aid.lower())

            # MSP: also iterate tenants
            tenant_summary = []
            is_msp = acct_type.upper() == "MSP"
            if is_msp:
                print(f"[CCS] Audit: {cust_id} is MSP — fetching tenants")
                tenants = _get_tenants(base_url, headers, cust_id)
                print(f"[CCS] Audit: MSP {cust_id} → {len(tenants)} tenant(s) returned")
                
                def fetch_tenant_provisions(tenant):
                    tenant_cust_id = (
                        tenant.get("platform_customer_id") or tenant.get("customer_id")
                        or tenant.get("tenant_customer_id") or tenant.get("workspace_id")
                        or tenant.get("account_id") or tenant.get("id") or ""
                    )
                    tenant_name = (
                        tenant.get("company_name") or tenant.get("name")
                        or tenant.get("tenant_name") or tenant.get("contact", {}).get("company_name", "")
                        or tenant_cust_id
                    )
                    if not tenant_cust_id:
                        return None
                    t_provisions = _get_provisions(base_url, headers, tenant_cust_id)
                    t_aids = set()
                    for p in t_provisions:
                        for aid in _extract_app_ids(p):
                            t_aids.add(aid.lower())
                    return {"id": tenant_cust_id, "name": tenant_name, "aids": t_aids}

                with ThreadPoolExecutor(max_workers=10) as t_executor:
                    for t_res in t_executor.map(fetch_tenant_provisions, tenants):
                        if not t_res:
                            continue
                        t_aids = t_res["aids"]
                        for aid in t_aids:
                            collected_app_ids.add(aid)
                        t_matched = sorted(t_aids & reference_set)
                        tenant_summary.append({
                            "tenant_id": t_res["id"],
                            "tenant_name": t_res["name"],
                            "app_ids_found": sorted(t_aids),
                            "matched": t_matched,
                            "missing_from_tenant": sorted(reference_set - t_aids),
                        })

            # ── 3. Compare against reference ────────────────────────────────
            print(f"[CCS] Audit: Comparing for {cust_id}. Collected: {collected_app_ids}")
            matched = sorted(collected_app_ids & reference_set)
            missing = sorted(reference_set - collected_app_ids)

            detail_str = f"Company: {comp_name} | Region: {region} | Type: {acct_type}"
            if matched:
                detail_str += f" | Found IDs: {', '.join(matched)}"

            if is_msp:
                matched_tenants = [t["tenant_name"] for t in tenant_summary if t["matched"]]
                if matched_tenants:
                    detail_str += f" | Matched inside Tenants: {', '.join(matched_tenants)}"
                else:
                    detail_str += f" | Checked {len(tenant_summary)} tenants (no matches)"

            stats["successful"] += 1
            stats["details"].append({
                "key": f"{search_str} → {comp_name} ({cust_id})",
                "success": True,
                "status": "Match" if matched else "No Match",
                "detail": detail_str,
                "raw": {
                    "search_string": search_str,
                    "customer_id": cust_id,
                    "company_name": comp_name,
                    "account_type": acct_type,
                    "region": region,
                    "is_msp": is_msp,
                    "app_ids_found": sorted(collected_app_ids),
                    "matched_app_ids": matched,
                    "missing_app_ids": missing,
                    "reference_count": len(reference_set),
                    "tenants": tenant_summary if is_msp else [],
                },
            })
            
        return stats

    # Run the outer loop in parallel
    with ThreadPoolExecutor(max_workers=5) as executor:
        for partial_stats in executor.map(process_search_str, search_strings):
            results["total"] += partial_stats["total"]
            results["successful"] += partial_stats["successful"]
            results["failed"] += partial_stats["failed"]
            results["details"].extend(partial_stats["details"])

    results["elapsed_seconds"] = round(time.time() - start_time, 2)
    return JSONResponse(content=results)