from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import JSONResponse
from app.core.client import get_glp_client
from app.audit.logger import log_operation
from typing import List, Optional
import csv
import io
import time
import requests
import asyncio
import httpx
import uuid as _uuid

router = APIRouter()

# Workspace tool uses pycentral auth (client credentials), not session auth.
# We log operations under a synthetic "workspace-tool" actor.
_WORKSPACE_ACTOR = {"username": "workspace-tool", "display_name": "Workspace Tool", "role": "operator"}

# ── Abort flag store ─────────────────────────────────────────────────────────
# Maps operation_id -> asyncio.Event  (set = abort requested)
_abort_events: dict = {}

API_ENDPOINT = "https://global.api.greenlake.hpe.com"


def parse_csv_serials(file_content: bytes) -> List[dict]:
    """Parse CSV file and extract serial numbers and optional MAC addresses.
    Returns list of dicts: [{'serial': 'XXX', 'mac': 'YYY'}, ...]
    """
    try:
        text = file_content.decode('utf-8-sig')
        csv_reader = csv.DictReader(io.StringIO(text))
        devices = []
        
        for row in csv_reader:
            device = {}
            
            # Extract serial number
            for col in ['Serial Number', 'SerialNumber', 'Serial', 'SN', 'serial', 'SERIAL']:
                if col in row and row[col].strip():
                    device['serial'] = row[col].strip()
                    break
            
            # Extract MAC address (optional)
            for col in ['MAC Address', 'MACAddress', 'MAC', 'mac', 'macAddress']:
                if col in row and row[col].strip():
                    device['mac'] = row[col].strip()
                    break
            
            if 'serial' in device:
                devices.append(device)
        
        return devices
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"CSV parse error: {str(e)}")


def get_token(client) -> str:
    """Get access token from the pycentral client.
    Ensures a token is available by triggering a login if needed.
    """
    token_info = client.token_info.get('glp', {})
    token = token_info.get('access_token')
    
    # If no token, or if it might be expired, trigger a minimal command to force refresh
    if not token or 'client_id' in token_info:
        try:
            print("[DEBUG] Triggering token refresh/fetch...")
            # This call will trigger internal pycentral refresh/login logic
            client.command("GET", "/platform/workspace/v1/workspaces", "glp", api_params={"limit": 1})
            token = client.token_info.get('glp', {}).get('access_token')
        except Exception as e:
            print(f"[ERROR] Failed to refresh token: {e}")
            
    return token or ""


def get_auth_headers(token: str, content_type: str = "application/json") -> dict:
    """Build authorization headers."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": content_type
    }


def get_device_by_serial(token: str, serial: str) -> Optional[dict]:
    """Get device info by serial number using raw requests."""
    url = f"{API_ENDPOINT}/devices/v1beta1/devices"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"filter": f"serialNumber eq '{serial}'"}
    
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('items') and len(data['items']) > 0:
                return data['items'][0]
    except Exception as e:
        print(f"[DEBUG] Error getting device {serial}: {e}")
    
    return None


def check_async_progress(token: str, progress_url: str, max_wait: int = 30) -> dict:
    """
    Poll async operation progress URL until completion.
    Returns: {'success': bool, 'status': str, 'details': str}
    """
    
    # Debug inputs
    print(f"[DEBUG] check_async_progress input: '{progress_url}'", flush=True)
    
    # Ensure cleanliness
    progress_url = progress_url.strip()
    
    # Fix relative URLs - prepend API endpoint if needed
    if not progress_url.lower().startswith('http'):
        # Ensure API_ENDPOINT is available
        base = API_ENDPOINT
        if not base:
             base = "https://global.api.greenlake.hpe.com"
             
        if not progress_url.startswith('/'):
            progress_url = f"/{progress_url}"
            
        progress_url = f"{base}{progress_url}"
    
    print(f"[DEBUG] Polling async URL (final): {progress_url}", flush=True)
    polls = max_wait // 5  # poll every 5 seconds
    
    for attempt in range(polls):
        time.sleep(5)
        try:
            resp = requests.get(
                progress_url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30
            )
            print(f"[DEBUG] Async poll {attempt+1}: HTTP {resp.status_code}")
            
            if resp.status_code == 200:
                data = resp.json()
                status = data.get('status', '').upper()
                print(f"[DEBUG] Async status: {status}, data: {data}")
                
                if status in ['SUCCEEDED', 'COMPLETED', 'SUCCESS']:
                    return {
                        'success': True, 
                        'status': status, 
                        'details': 'Operation completed successfully',
                        'result': data.get('result', {})
                    }
                elif status in ['FAILED', 'ERROR', 'TIMEOUT']:
                    result = data.get('result', {})
                    log_messages = data.get('logMessages', [])
                    reason = result.get('reason', '')
                    failed_devices = result.get('failedDevices', [])
                    failed_count = len(failed_devices) if isinstance(failed_devices, list) else result.get('failedDeviceCount', 0)
                    
                    # Try to extract more detailed error information
                    error_details = []
                    if reason:
                        error_details.append(reason)
                    if log_messages:
                        error_details.extend([msg.get('message', str(msg)) for msg in log_messages if isinstance(msg, dict)])
                    if failed_devices:
                        error_details.append(f"Failed device count: {failed_count}")
                    
                    details = '; '.join(error_details) if error_details else f"Operation failed ({failed_count} device(s))"
                    
                    return {
                        'success': False, 
                        'status': status, 
                        'details': details,
                        'result': result
                    }
                # else still IN_PROGRESS, continue polling
        except Exception as e:
            print(f"[DEBUG] Poll error: {e}")
    
    return {'success': None, 'status': 'TIMEOUT', 'details': 'Polling timed out - operation may still be processing'}


def get_subscription_id_from_key(token: str, subscription_key: str) -> Optional[str]:
    """Find subscription ID from subscription key using raw requests."""
    url = f"{API_ENDPOINT}/subscriptions/v1/subscriptions"
    headers = {"Authorization": f"Bearer {token}"}
    
    # Try filter first
    for filter_str in [f"key eq '{subscription_key}'"]:
        try:
            params = {"filter": filter_str, "limit": 10}
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get('items', [])
                if items:
                    return items[0].get('id')
        except:
            pass
    
    # Fallback: search all subscriptions
    try:
        params = {"limit": 100}
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            for sub in data.get('items', []):
                if sub.get('key') == subscription_key:
                    return sub.get('id')
    except:
        pass
    
    return None


# ============================================================
# DEVICE INFO
# ============================================================

@router.post("/device-info")
async def bulk_device_info(
    file: UploadFile = File(...),
    operation_id: Optional[str] = Form(None),
):
    """Get device information for all devices in CSV."""
    client = get_glp_client()
    if not client:
        raise HTTPException(status_code=401, detail="Client not configured")

    op_id = operation_id or str(_uuid.uuid4())
    abort_event = asyncio.Event()
    _abort_events[op_id] = abort_event

    try:
        token = get_token(client)
        content = await file.read()
        devices = parse_csv_serials(content)

        if not devices:
            raise HTTPException(status_code=400, detail="No serial numbers found in CSV")

        # Concurrent lookup — GET endpoints tolerate higher concurrency
        lookup_sem = asyncio.Semaphore(15)

        async def _lookup(device_info):
            if abort_event.is_set():
                return {'serial': device_info['serial'], 'found': False, 'error': 'Aborted'}
            serial = device_info['serial']
            async with lookup_sem:
                return await _async_lookup_device_uuid(token, serial, abort_event)

        raw_results = await asyncio.gather(*[_lookup(d) for d in devices])

        # Enrich with full device data for found devices
        results = []
        enrich_sem = asyncio.Semaphore(10)

        async def _enrich(lr):
            serial = lr['serial']
            if not lr.get('uuid'):
                return {'serial': serial, 'found': False,
                        'error': 'Aborted' if lr.get('aborted') else 'Device not found'}
            async with enrich_sem:
                url = f"{API_ENDPOINT}/devices/v1beta1/devices"
                headers = {"Authorization": f"Bearer {token}"}
                params = {"filter": f"id eq '{lr['uuid']}'"}  # fetch by uuid for speed
                try:
                    async with httpx.AsyncClient(timeout=30) as client_h:
                        resp = await client_h.get(url, headers=headers, params=params)
                    if resp.status_code == 200:
                        items = resp.json().get('items', [])
                        if items:
                            device = items[0]
                            app_data = device.get('application') or {}
                            sub_data = device.get('subscription')
                            sub_key = None
                            if sub_data:
                                if isinstance(sub_data, list) and sub_data:
                                    sub_key = sub_data[0].get('key')
                                elif isinstance(sub_data, dict):
                                    sub_key = sub_data.get('key')
                            return {
                                'serial': serial, 'found': True,
                                'data': {
                                    'id': device.get('id'),
                                    'name': device.get('name'),
                                    'model': device.get('model'),
                                    'macAddress': device.get('macAddress'),
                                    'deviceType': device.get('deviceType'),
                                    'status': device.get('status'),
                                    'application': app_data.get('name') if app_data else None,
                                    'subscription': sub_key,
                                }
                            }
                except Exception as e:
                    pass
            return {'serial': serial, 'found': False, 'error': 'Failed to fetch device details'}

        results = list(await asyncio.gather(*[_enrich(lr) for lr in raw_results]))
        return JSONResponse(content={
            'operation_id': op_id,
            'total': len(devices),
            'aborted': abort_event.is_set(),
            'results': results,
        })
    finally:
        _abort_events.pop(op_id, None)


# ============================================================
# ASSIGN SUBSCRIPTION
# ============================================================

# ── Concurrency limits for assign-subscription ───────────────────────────────
# GET (UUID lookup): 15 parallel is fine — read endpoints are less restricted
_ASSIGN_LOOKUP_CONCURRENCY = 15
# PATCH (write): HPE GreenLake throttles writes heavily; keep at 3 max
_ASSIGN_PATCH_CONCURRENCY = 3
# 429 retry settings
_MAX_RETRY_429 = 4        # max attempts per device
_RETRY_BACKOFF_BASE = 8   # seconds; doubles each retry (8 → 16 → 32 → 64)


async def _async_lookup_device_uuid(token: str, serial: str, abort_event: asyncio.Event) -> dict:
    """Concurrently look up device UUID by serial. Returns {'serial', 'uuid'|None}."""
    if abort_event.is_set():
        return {'serial': serial, 'uuid': None, 'aborted': True}

    url = f"{API_ENDPOINT}/devices/v1beta1/devices"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"filter": f"serialNumber eq '{serial}'"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code == 200:
                items = resp.json().get('items', [])
                if items:
                    return {'serial': serial, 'uuid': items[0].get('id')}
    except Exception as e:
        print(f"[WARN] UUID lookup failed for {serial}: {e}")

    return {'serial': serial, 'uuid': None}


async def _async_patch_subscription(
    token: str,
    serial: str,
    device_uuid: str,
    subscription_id: str,
    abort_event: asyncio.Event,
) -> dict:
    """PATCH subscription on a single device with 429 retry/backoff. Returns rich result dict."""
    if abort_event.is_set():
        return {'serial': serial, 'success': False, 'aborted': True, 'error': 'Aborted by user'}

    url = f"{API_ENDPOINT}/devices/v1beta1/devices"
    headers = get_auth_headers(token, "application/merge-patch+json")
    params = {"id": device_uuid}
    payload = {"subscription": [{"id": subscription_id}]}

    last_resp = None
    for attempt in range(1, _MAX_RETRY_429 + 1):
        if abort_event.is_set():
            return {'serial': serial, 'success': False, 'aborted': True, 'error': 'Aborted by user'}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.patch(url, headers=headers, params=params, json=payload)
            last_resp = resp
            print(f"[DEBUG] PATCH {serial}: HTTP {resp.status_code} (attempt {attempt})", flush=True)

            if resp.status_code == 429:
                # Honour Retry-After header if present, otherwise use exponential backoff
                retry_after = resp.headers.get('Retry-After')
                wait = int(retry_after) if retry_after and retry_after.isdigit() \
                       else _RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                print(f"[WARN] 429 rate-limit for {serial}. Waiting {wait}s before retry {attempt}/{_MAX_RETRY_429}", flush=True)
                await asyncio.sleep(wait)
                continue  # retry

            # Not a 429 — handle final response below
            break

        except Exception as e:
            return {
                'serial': serial, 'success': False, 'error': str(e),
                'device_uuid': device_uuid, 'subscription_id': subscription_id, 'exception': True,
            }
    else:
        # Exhausted all retries on 429
        return {
            'serial': serial, 'success': False,
            'error': f'Rate-limited (HTTP 429) after {_MAX_RETRY_429} retries — API quota exhausted.',
            'http_status': 429, 'device_uuid': device_uuid, 'subscription_id': subscription_id,
        }

    resp = last_resp
    try:
        if resp.status_code == 200:
            return {'serial': serial, 'success': True, 'status': 'Completed'}

        elif resp.status_code == 202:
            progress_url = resp.headers.get('location', '')
            if not progress_url:
                try:
                    txn_id = resp.json().get('transactionId', '')
                    if txn_id:
                        progress_url = f"{API_ENDPOINT}/async-operations/v1/async-operations/{txn_id}"
                except Exception:
                    pass

            if progress_url:
                loop = asyncio.get_event_loop()
                async_result = await loop.run_in_executor(
                    None, check_async_progress, token, progress_url
                )
                if async_result['success'] is True:
                    return {'serial': serial, 'success': True, 'status': 'Completed'}
                elif async_result['success'] is False:
                    # Build a human-readable hint for the most common causes
                    result_data = async_result.get('result', {})
                    failed_devices = result_data.get('failedDevices', [])
                    hint = ''
                    if failed_devices and not result_data.get('reason') and not async_result.get('details', '').strip():
                        hint = (' Possible causes: (1) subscription has no remaining seats, '
                                '(2) subscription tier does not match device type, '
                                '(3) device is already bound to a different subscription — unassign it first.')
                    error_msg = (async_result.get('details') or 'Async operation FAILED') + hint
                    return {
                        'serial': serial, 'success': False, 'error': error_msg,
                        'http_status': 202, 'device_uuid': device_uuid,
                        'subscription_id': subscription_id,
                        'async_status': async_result.get('status'),
                        'async_result': result_data,
                    }
                else:
                    return {'serial': serial, 'success': True, 'status': 'Processing (check later)'}
            else:
                return {'serial': serial, 'success': True, 'status': '202 Accepted'}

        else:
            http_status = resp.status_code
            raw_body = ''
            error_msg = f"HTTP {http_status}"
            try:
                error_data = resp.json()
                error_msg = error_data.get('message', error_data.get('description', str(error_data)))
                raw_body = str(error_data)
            except Exception:
                raw_body = resp.text[:500] if resp.text else ''
                error_msg = raw_body or error_msg

            return {
                'serial': serial, 'success': False, 'error': error_msg,
                'http_status': http_status, 'raw_response': raw_body[:500],
                'device_uuid': device_uuid, 'subscription_id': subscription_id,
            }

    except Exception as e:
        return {
            'serial': serial, 'success': False, 'error': str(e),
            'device_uuid': device_uuid, 'subscription_id': subscription_id, 'exception': True,
        }


@router.post("/assign-subscription")
async def bulk_assign_subscription(
    subscription_key: str = Form(...),
    file: UploadFile = File(...),
    operation_id: Optional[str] = Form(None),
):
    """Bulk assign subscription to devices from CSV.

    Improvements over v1:
    - Concurrent UUID lookups (up to 15 parallel) — much faster for large CSVs.
    - Abort support: pass operation_id then call DELETE /api/bulk/abort/{operation_id}.
    - Detailed failure report: includes http_status, raw_response, device_uuid,
      subscription_id and async_result for every persistent failure.
    """
    client = get_glp_client()
    if not client:
        raise HTTPException(status_code=401, detail="Client not configured")

    token = get_token(client)

    # Register abort event
    op_id = operation_id or str(_uuid.uuid4())
    abort_event = asyncio.Event()
    _abort_events[op_id] = abort_event

    try:
        # Resolve subscription key → ID
        subscription_id = get_subscription_id_from_key(token, subscription_key)
        if not subscription_id:
            raise HTTPException(
                status_code=404,
                detail=f"Subscription key '{subscription_key}' not found"
            )
        print(f"[DEBUG] Subscription ID: {subscription_id} (key: {subscription_key})", flush=True)

        # Parse CSV
        content = await file.read()
        devices = parse_csv_serials(content)
        if not devices:
            raise HTTPException(status_code=400, detail="No serial numbers found in CSV")

        print(f"[INFO] Starting concurrent UUID lookup for {len(devices)} devices...", flush=True)
        start_lookup = time.time()

        # ── Phase 1: Concurrent UUID lookups ─────────────────────────────────
        sem = asyncio.Semaphore(_ASSIGN_LOOKUP_CONCURRENCY)

        async def _throttled_lookup(serial: str):
            async with sem:
                return await _async_lookup_device_uuid(token, serial, abort_event)

        lookup_results = await asyncio.gather(
            *[_throttled_lookup(d['serial']) for d in devices]
        )

        elapsed_lookup = time.time() - start_lookup
        print(f"[INFO] UUID lookup done in {elapsed_lookup:.2f}s", flush=True)

        # Build serial → uuid map; collect not-found
        device_map: dict[str, str] = {}
        not_found_serials: list[str] = []
        for lr in lookup_results:
            if lr.get('aborted'):
                not_found_serials.append(lr['serial'])  # treated as skipped
            elif lr.get('uuid'):
                device_map[lr['serial']] = lr['uuid']
            else:
                not_found_serials.append(lr['serial'])

        results: dict = {
            'operation_id': op_id,
            'total': len(devices),
            'successful': 0,
            'failed': 0,
            'aborted': False,
            'details': [],
            'lookup_time_seconds': round(elapsed_lookup, 2),
            'failure_report': [],  # detailed per-device failure info
        }

        # Mark not-found devices as failed
        for serial in not_found_serials:
            results['failed'] += 1
            detail = {
                'serial': serial,
                'success': False,
                'error': 'Device not found (UUID lookup failed)',
            }
            results['details'].append(detail)
            results['failure_report'].append({
                **detail,
                'phase': 'uuid_lookup',
                'subscription_key': subscription_key,
            })

        if not device_map:
            results['aborted'] = abort_event.is_set()
            return JSONResponse(content=results)

        # ── Phase 2: Concurrent PATCH subscription ────────────────────────────
        # PATCH endpoints are rate-limited much more tightly than GETs.
        # Use a separate, smaller semaphore (_ASSIGN_PATCH_CONCURRENCY=3).
        print(f"[INFO] Patching subscription on {len(device_map)} devices "
              f"(max {_ASSIGN_PATCH_CONCURRENCY} concurrent, up to {_MAX_RETRY_429} retries on 429)...", flush=True)
        start_patch = time.time()
        patch_sem = asyncio.Semaphore(_ASSIGN_PATCH_CONCURRENCY)

        async def _throttled_patch(serial: str, uuid: str):
            async with patch_sem:
                return await _async_patch_subscription(token, serial, uuid, subscription_id, abort_event)

        patch_results = await asyncio.gather(
            *[_throttled_patch(s, u) for s, u in device_map.items()]
        )

        elapsed_patch = time.time() - start_patch
        print(f"[INFO] PATCH phase done in {elapsed_patch:.2f}s", flush=True)

        for pr in patch_results:
            if pr.get('aborted'):
                results['aborted'] = True
                results['failed'] += 1
                results['details'].append({'serial': pr['serial'], 'success': False, 'error': 'Aborted'})
            elif pr.get('success'):
                results['successful'] += 1
                results['details'].append({'serial': pr['serial'], 'success': True, 'status': pr.get('status', 'Completed')})
            else:
                results['failed'] += 1
                simple = {'serial': pr['serial'], 'success': False, 'error': pr.get('error', 'Unknown error')}
                results['details'].append(simple)
                # Rich failure report entry
                results['failure_report'].append({
                    'serial': pr['serial'],
                    'phase': 'subscription_patch',
                    'http_status': pr.get('http_status'),
                    'raw_response': pr.get('raw_response', ''),
                    'device_uuid': pr.get('device_uuid', device_map.get(pr['serial'])),
                    'subscription_id': pr.get('subscription_id', subscription_id),
                    'subscription_key': subscription_key,
                    'async_status': pr.get('async_status'),
                    'async_result': pr.get('async_result'),
                    'error': pr.get('error', 'Unknown error'),
                    'exception': pr.get('exception', False),
                })

        results['patch_time_seconds'] = round(elapsed_patch, 2)
        results['total_time_seconds'] = round(elapsed_lookup + elapsed_patch, 2)
        results['aborted'] = abort_event.is_set()

        try:
            _serials = [d['serial'] for d in devices[:10]]
            log_operation(
                user=_WORKSPACE_ACTOR, operation="Assign Subscription",
                endpoint="/api/bulk/assign-subscription",
                input_rows=len(devices),
                query_input=subscription_key + " → " + ", ".join(_serials),
                total=results['total'], success=results['successful'], failed=results['failed'],
                elapsed_sec=results.get('total_time_seconds'),
                status='ok', detail=f"Sub key: {subscription_key}",
            )
        except Exception: pass

        return JSONResponse(content=results)

    finally:
        _abort_events.pop(op_id, None)


@router.delete("/abort/{operation_id}")
async def abort_operation(operation_id: str):
    """Signal any in-flight bulk operation to stop gracefully after its current item."""
    event = _abort_events.get(operation_id)
    if event is None:
        raise HTTPException(
            status_code=404,
            detail=f"No active operation '{operation_id}' found (may have already completed)."
        )
    event.set()
    print(f"[INFO] Abort requested for operation {operation_id}", flush=True)
    return JSONResponse(content={'message': f'Abort signal sent to operation {operation_id}'})


# ============================================================
# UNASSIGN SUBSCRIPTION
# ============================================================

@router.post("/unassign-subscription")
async def bulk_unassign_subscription(
    file: UploadFile = File(...),
    operation_id: Optional[str] = Form(None),
):
    """Bulk remove subscriptions from devices.
    Concurrent UUID lookup + async PATCH with 429 retry + abort support.
    """
    client = get_glp_client()
    if not client:
        raise HTTPException(status_code=401, detail="Client not configured")

    op_id = operation_id or str(_uuid.uuid4())
    abort_event = asyncio.Event()
    _abort_events[op_id] = abort_event

    try:
        token = get_token(client)
        content = await file.read()
        devices = parse_csv_serials(content)

        if not devices:
            raise HTTPException(status_code=400, detail="No serial numbers found in CSV")

        # Phase 1: Concurrent UUID lookups
        lu_sem = asyncio.Semaphore(_ASSIGN_LOOKUP_CONCURRENCY)

        async def _lu(serial):
            async with lu_sem:
                return await _async_lookup_device_uuid(token, serial, abort_event)

        lookup_results = await asyncio.gather(*[_lu(d['serial']) for d in devices])

        results = {
            'operation_id': op_id, 'total': len(devices),
            'successful': 0, 'failed': 0, 'aborted': False,
            'details': [], 'failure_report': [],
        }

        device_map: dict[str, str] = {}
        for lr in lookup_results:
            if lr.get('aborted') or not lr.get('uuid'):
                results['failed'] += 1
                err = 'Aborted' if lr.get('aborted') else 'Device not found'
                results['details'].append({'serial': lr['serial'], 'success': False, 'error': err})
                results['failure_report'].append({'serial': lr['serial'], 'phase': 'uuid_lookup', 'error': err})
            else:
                device_map[lr['serial']] = lr['uuid']

        if not device_map:
            results['aborted'] = abort_event.is_set()
            return JSONResponse(content=results)

        # Phase 2: Concurrent PATCH (empty subscription = unassign) with 429 retry
        patch_sem = asyncio.Semaphore(_ASSIGN_PATCH_CONCURRENCY)

        async def _unassign_patch(serial, uuid):
            if abort_event.is_set():
                return {'serial': serial, 'success': False, 'aborted': True, 'error': 'Aborted'}
            async with patch_sem:
                url = f"{API_ENDPOINT}/devices/v1beta1/devices"
                headers = get_auth_headers(token, "application/merge-patch+json")
                params = {"id": uuid}
                payload = {"subscription": []}
                last_resp = None
                for attempt in range(1, _MAX_RETRY_429 + 1):
                    if abort_event.is_set():
                        return {'serial': serial, 'success': False, 'aborted': True, 'error': 'Aborted'}
                    try:
                        async with httpx.AsyncClient(timeout=30) as hc:
                            resp = await hc.patch(url, headers=headers, params=params, json=payload)
                        last_resp = resp
                        print(f"[DEBUG] Unassign {serial}: HTTP {resp.status_code} (attempt {attempt})", flush=True)
                        if resp.status_code == 429:
                            retry_after = resp.headers.get('Retry-After')
                            wait = int(retry_after) if retry_after and retry_after.isdigit() \
                                   else _RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                            print(f"[WARN] 429 on unassign {serial}, wait {wait}s", flush=True)
                            await asyncio.sleep(wait)
                            continue
                        break
                    except Exception as e:
                        return {'serial': serial, 'success': False, 'error': str(e),
                                'device_uuid': uuid, 'exception': True}
                else:
                    return {'serial': serial, 'success': False,
                            'error': f'Rate-limited after {_MAX_RETRY_429} retries',
                            'http_status': 429, 'device_uuid': uuid}

                resp = last_resp
                if resp.status_code == 200:
                    return {'serial': serial, 'success': True, 'status': 'Completed'}
                elif resp.status_code == 202:
                    prog = resp.headers.get('location', '')
                    if prog:
                        loop = asyncio.get_event_loop()
                        ar = await loop.run_in_executor(None, check_async_progress, token, prog)
                        if ar['success'] is True:
                            return {'serial': serial, 'success': True, 'status': 'Completed'}
                        elif ar['success'] is False:
                            return {'serial': serial, 'success': False, 'error': ar['details'],
                                    'http_status': 202, 'device_uuid': uuid}
                        return {'serial': serial, 'success': True, 'status': 'Processing'}
                    return {'serial': serial, 'success': True, 'status': '202 Accepted'}
                else:
                    err = f"HTTP {resp.status_code}"
                    try:
                        err = resp.json().get('message', err)
                    except Exception:
                        pass
                    return {'serial': serial, 'success': False, 'error': err,
                            'http_status': resp.status_code, 'device_uuid': uuid}

        patch_results = await asyncio.gather(
            *[_unassign_patch(s, u) for s, u in device_map.items()]
        )

        for pr in patch_results:
            if pr.get('aborted'):
                results['aborted'] = True
                results['failed'] += 1
                results['details'].append({'serial': pr['serial'], 'success': False, 'error': 'Aborted'})
            elif pr.get('success'):
                results['successful'] += 1
                results['details'].append({'serial': pr['serial'], 'success': True,
                                           'status': pr.get('status', 'Completed')})
            else:
                results['failed'] += 1
                results['details'].append({'serial': pr['serial'], 'success': False,
                                           'error': pr.get('error', 'Unknown error')})
                results['failure_report'].append({
                    'serial': pr['serial'], 'phase': 'unassign_patch',
                    'http_status': pr.get('http_status'),
                    'device_uuid': pr.get('device_uuid'),
                    'error': pr.get('error'),
                })

        results['aborted'] = abort_event.is_set()
        try:
            log_operation(
                user=_WORKSPACE_ACTOR, operation="Unassign Subscription",
                endpoint="/api/bulk/unassign-subscription",
                input_rows=results.get('total'),
                total=results.get('total'), success=results.get('successful'), failed=results.get('failed'),
                status='ok',
            )
        except Exception: pass
        return JSONResponse(content=results)
    finally:
        _abort_events.pop(op_id, None)


# ============================================================
# ADD DEVICES TO APPLICATION
# ============================================================

@router.post("/transfer-devices")
async def bulk_transfer_devices(
    application_id: str = Form(...),
    region: str = Form(...),
    file: UploadFile = File(...),
    operation_id: Optional[str] = Form(None),
):
    """Bulk transfer devices to an application. Supports abort and 429 retry."""
    client = get_glp_client()
    if not client:
        raise HTTPException(status_code=401, detail="Client not configured")

    op_id = operation_id or str(_uuid.uuid4())
    abort_event = asyncio.Event()
    _abort_events[op_id] = abort_event

    try:
        token = get_token(client)
        content = await file.read()
        devices = parse_csv_serials(content)

        if not devices:
            raise HTTPException(status_code=400, detail="No serial numbers found in CSV")

        serials = [d['serial'] for d in devices]
        results = {
            'operation_id': op_id, 'total': len(devices),
            'successful': 0, 'failed': 0, 'aborted': False,
            'details': [], 'failure_report': [],
        }
        url = f"{API_ENDPOINT}/devices/v1beta1/devices"
        batch_size = 5

        for i in range(0, len(serials), batch_size):
            if abort_event.is_set():
                results['aborted'] = True
                for serial in serials[i:]:
                    results['failed'] += 1
                    results['details'].append({'serial': serial, 'success': False, 'error': 'Aborted'})
                break

            batch = serials[i:i + batch_size]
            batch_devices = []
            for serial in batch:
                device = get_device_by_serial(token, serial)
                if device and device.get('id'):
                    batch_devices.append((serial, device['id']))
                else:
                    results['failed'] += 1
                    results['details'].append({'serial': serial, 'success': False, 'error': 'Device not found'})

            if not batch_devices:
                continue

            batch_uuids = [uid for _, uid in batch_devices]
            batch_serials = [s for s, _ in batch_devices]

            # 429 retry on batch PATCH
            last_resp = None
            patch_ok = False
            for attempt in range(1, _MAX_RETRY_429 + 1):
                if abort_event.is_set():
                    break
                try:
                    headers = get_auth_headers(token, "application/merge-patch+json")
                    params = [("id", uid) for uid in batch_uuids]
                    payload = {"application": {"id": application_id}, "region": region}
                    print(f"[DEBUG] Transfer batch {batch_serials} (attempt {attempt})", flush=True)
                    response = requests.patch(url, headers=headers, params=params, json=payload, timeout=30)
                    last_resp = response
                    if response.status_code == 429:
                        retry_after = response.headers.get('Retry-After')
                        wait = int(retry_after) if retry_after and retry_after.isdigit() \
                               else _RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                        print(f"[WARN] 429 on transfer batch, wait {wait}s", flush=True)
                        time.sleep(wait)
                        continue
                    patch_ok = True
                    break
                except Exception as e:
                    for serial in batch_serials:
                        results['failed'] += 1
                        results['details'].append({'serial': serial, 'success': False, 'error': str(e)})
                    last_resp = None
                    break

            if abort_event.is_set():
                for serial in batch_serials:
                    results['failed'] += 1
                    results['details'].append({'serial': serial, 'success': False, 'error': 'Aborted'})
                results['aborted'] = True
                break

            if last_resp is None:
                if i + batch_size < len(serials):
                    time.sleep(12)
                continue

            if not patch_ok:
                err = f'Rate-limited (HTTP 429) after {_MAX_RETRY_429} retries'
                for serial in batch_serials:
                    results['failed'] += 1
                    results['details'].append({'serial': serial, 'success': False, 'error': err})
                    results['failure_report'].append({'serial': serial, 'phase': 'batch_patch',
                                                      'http_status': 429, 'error': err})
                if i + batch_size < len(serials):
                    time.sleep(12)
                continue

            response = last_resp
            if response.status_code == 200:
                results['successful'] += len(batch_serials)
                for serial in batch_serials:
                    results['details'].append({'serial': serial, 'success': True, 'status': 'Completed'})

            elif response.status_code == 202:
                progress_url = response.headers.get('location', '')
                if not progress_url:
                    try:
                        txn_id = response.json().get('transactionId', '')
                        if txn_id:
                            progress_url = f"{API_ENDPOINT}/async-operations/v1/async-operations/{txn_id}"
                    except Exception:
                        pass
                if progress_url:
                    async_result = check_async_progress(token, progress_url, max_wait=60)
                    uuid_to_serial = {uid: s for s, uid in batch_devices}
                    if async_result['status'] in ['COMPLETED', 'SUCCEEDED', 'SUCCESS']:
                        results['successful'] += len(batch_serials)
                        for serial in batch_serials:
                            results['details'].append({'serial': serial, 'success': True, 'status': 'Completed'})
                    elif async_result['status'] in ['FAILED', 'ERROR']:
                        result_data = async_result.get('result', {})
                        succeeded = result_data.get('succeededDevices', []) or []
                        failed_uuids = result_data.get('failedDevices', []) or []
                        processed = set()
                        for uid in succeeded:
                            if uid in uuid_to_serial:
                                results['successful'] += 1
                                results['details'].append({'serial': uuid_to_serial[uid], 'success': True, 'status': 'Completed'})
                                processed.add(uid)
                        for uid in failed_uuids:
                            if uid in uuid_to_serial:
                                err = async_result.get('details', 'Transfer failed')
                                results['failed'] += 1
                                results['details'].append({'serial': uuid_to_serial[uid], 'success': False, 'error': err})
                                results['failure_report'].append({'serial': uuid_to_serial[uid],
                                                                  'phase': 'async_transfer', 'http_status': 202,
                                                                  'error': err, 'device_uuid': uid})
                                processed.add(uid)
                        for uid, s in uuid_to_serial.items():
                            if uid not in processed:
                                err = async_result.get('details', 'Async transfer failed')
                                results['failed'] += 1
                                results['details'].append({'serial': s, 'success': False, 'error': err})
                    else:
                        results['successful'] += len(batch_serials)
                        for serial in batch_serials:
                            results['details'].append({'serial': serial, 'success': True, 'status': 'Processing'})
                else:
                    results['successful'] += len(batch_serials)
                    for serial in batch_serials:
                        results['details'].append({'serial': serial, 'success': True, 'status': '202 Accepted'})
            else:
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_msg = response.json().get('message', error_msg)
                except Exception:
                    error_msg = response.text[:200] if response.text else error_msg
                results['failed'] += len(batch_serials)
                for serial in batch_serials:
                    results['details'].append({'serial': serial, 'success': False, 'error': error_msg})
                    results['failure_report'].append({'serial': serial, 'phase': 'batch_patch',
                                                      'http_status': response.status_code, 'error': error_msg})

            if i + batch_size < len(serials):
                time.sleep(12)

        results['aborted'] = abort_event.is_set()
        try:
            log_operation(
                user=_WORKSPACE_ACTOR, operation="Transfer Devices to App",
                endpoint="/api/bulk/transfer-devices",
                input_rows=results.get('total'),
                query_input=f"app:{locals().get('application_id','')} region:{locals().get('region','')}",
                total=results.get('total'), success=results.get('successful'), failed=results.get('failed'),
                status='ok',
            )
        except Exception: pass
        return JSONResponse(content=results)
    finally:
        _abort_events.pop(op_id, None)



# ============================================================
# TRANSFER WORKSPACES (Source -> Destination) - ASYNC OPTIMIZED
# ============================================================

from pycentral import NewCentralBase
from pycentral.glp.devices import Devices as GLPDevices

# Semaphore to limit concurrent HTTP requests
MAX_CONCURRENT_REQUESTS = 10
semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

async def async_get_token(client):
    """Asynchronously get token for a client."""
    # Assuming get_token is synchronous and safe to call directly
    # If it involves I/O, it should be awaited or run in a thread pool
    return get_token(client)

async def async_get_device_by_serial(token, serial):
    """Asynchronously get device details by serial number using OData filter."""
    async with semaphore:
        url = f"{API_ENDPOINT}/devices/v1beta1/devices"
        headers = get_auth_headers(token)
        params = {"filter": f"serialNumber eq '{serial}'"}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                items = data.get('items', [])
                if items:
                    return items[0]
            return None

async def async_patch_device(token, device_id, payload):
    """Asynchronously patch device (unassign app/subscription)."""
    async with semaphore:
        url = f"{API_ENDPOINT}/devices/v1beta1/devices"
        headers = get_auth_headers(token, "application/merge-patch+json")
        params = {"id": device_id}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.patch(url, headers=headers, params=params, json=payload)
            return response

async def async_add_devices_to_inventory(token, category, devices_data):
    """Asynchronously add devices to inventory bypassing pycentral rate limits.
    Pycentral artificially caps at 20 devices/minute. This native HTTPX call chunks
    devices into larger sets to drastically drastically improve performance.
    """
    CHUNK_SIZE = 50
    all_responses = []

    url = f"{API_ENDPOINT}/devices/v1beta1/devices"
    headers = get_auth_headers(token)

    async with httpx.AsyncClient(timeout=45) as client:
        for i in range(0, len(devices_data), CHUNK_SIZE):
            chunk = devices_data[i:i + CHUNK_SIZE]
            
            payload = {"network": [], "compute": [], "storage": []}
            payload[category] = chunk
            
            async with semaphore:
                try:
                    response = await client.post(url, headers=headers, json=payload)
                    # Create a dict that mirrors the pycentral response format so existing
                    # downstream logic parses it seamlessly
                    if response.status_code in [200, 201, 202]:
                        all_responses.append({'code': response.status_code, 'msg': 'Add device request accepted...'})
                    else:
                        all_responses.append({'code': response.status_code, 'msg': response.text})
                except Exception as e:
                    all_responses.append({'code': 500, 'msg': str(e)})

    return all_responses

def create_client(client_id, client_secret):
    """Helper to create a client instance from credentials."""
    token_info = {
        "glp": {
            "client_id": client_id,
            "client_secret": client_secret,
            "base_url": "https://global.api.greenlake.hpe.com"
        }
    }
    return NewCentralBase(token_info=token_info)

@router.post("/transfer-workspaces")
async def transfer_workspaces(
    source_client_id: str = Form(...),
    source_client_secret: str = Form(...),
    dest_client_id: str = Form(...),
    dest_client_secret: str = Form(...),
    file: UploadFile = File(...)
):
    """
    Bulk transfer devices from Source Workspace to Destination Workspace.
    1. Unassign from Source Application (if assigned).
    2. Remove from Source Inventory (implicitly by unassigning).
    3. Add to Destination Inventory.
    Optimized for async concurrent operations.
    """
    # Initialize Clients
    try:
        source_client = create_client(source_client_id, source_client_secret)
        dest_client = create_client(dest_client_id, dest_client_secret)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to initialize clients: {str(e)}")

    # Parse CSV
    content = await file.read()
    try:
        devices_from_csv = parse_csv_serials(content)
    except Exception as e:
         raise HTTPException(status_code=400, detail=f"CSV Error: {str(e)}")
    
    if not devices_from_csv:
        raise HTTPException(status_code=400, detail="No devices found in CSV")

    results = {
        'total': len(devices_from_csv), 
        'successful': 0, 
        'failed': 0, 
        'details': [],
        'startTime': None,
        'estimatedCompletion': None,
        'averageTimePerDevice': None
    }
    
    
    start_time = time.time()
    results['startTime'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))
    
    source_token = await async_get_token(source_client)
    dest_token = await async_get_token(dest_client)

    # Step 1: Pre-fetch all source device details concurrently
    print(f"[DEBUG] Pre-fetching details for {len(devices_from_csv)} devices from source...")
    device_lookup_tasks = []
    for device_info in devices_from_csv:
        serial = device_info['serial']
        device_lookup_tasks.append(async_get_device_by_serial(source_token, serial))
    
    source_devices_data = await asyncio.gather(*device_lookup_tasks)
    
    # Prepare for processing
    devices_to_process = []
    for i, device_info in enumerate(devices_from_csv):
        serial = device_info['serial']
        mac_from_csv = device_info.get('mac')
        source_device = source_devices_data[i]

        if source_device is None:
            results['failed'] += 1
            results['details'].append({'serial': serial, 'success': False, 'error': 'Device not found in Source'})
            continue
        
        device_type = source_device.get('deviceType', 'NETWORK').upper()
        mac_address = mac_from_csv if mac_from_csv else source_device.get('macAddress')
        part_number = source_device.get('model')

        if not mac_address:
            results['failed'] += 1
            results['details'].append({
                'serial': serial, 
                'success': False, 
                'error': 'Device has no MAC address (required for adding to inventory)'
            })
            continue

        devices_to_process.append({
            'serial': serial,
            'mac_address': mac_address,
            'part_number': part_number,
            'device_type': device_type,
            'source_device_id': source_device['id'],
            'source_app_id': (source_device.get('application') or {}).get('id'),
            'has_subscription': bool(
                source_device.get('subscription') and
                isinstance(source_device.get('subscription'), list) and
                len(source_device.get('subscription')) > 0
            )
        })
    
    print(f"[DEBUG] {len(devices_to_process)} devices ready for transfer after pre-fetch and validation.")

    # Step 2 & 3: Unassign from Source and Add to Destination concurrently
    async def process_single_device(device_data):
        serial = device_data['serial']
        source_device_id = device_data['source_device_id']
        source_app_id = device_data['source_app_id']
        has_subscription = device_data['has_subscription']
        mac_address = device_data['mac_address']
        part_number = device_data['part_number']
        device_type = device_data['device_type']

        try:
            # 2a. Unassign from Application (if assigned)
            if source_app_id:
                print(f"[DEBUG] Unassigning {serial} from Application {source_app_id}")
                app_unassign_resp = await async_patch_device(source_token, source_device_id, {"application": {"id": None}, "region": None})
                if app_unassign_resp.status_code not in [200, 202]:
                    print(f"Warning: Failed to unassign app for {serial}: {app_unassign_resp.text}")
            
            # 2b. Unassign from Subscription (if assigned)
            if has_subscription:
                print(f"[DEBUG] Unassigning {serial} from Subscription")
                subs_unassign_resp = await async_patch_device(source_token, source_device_id, {"subscription": []})
                if subs_unassign_resp.status_code not in [200, 202]:
                    print(f"Warning: Failed to unassign subscription for {serial}: {subs_unassign_resp.text}")
            
            # 3. Add to Destination Inventory (prepare data for batching)
            category = "network"
            if "COMPUTE" in device_type: 
                category = "compute"
            elif "STORAGE" in device_type:
                category = "storage"
            
            device_input = {
                "serialNumber": serial,
                "macAddress": mac_address
            }
            if part_number:
                device_input["partNumber"] = part_number
            
            return {'serial': serial, 'success': True, 'status': 'Unassigned', 'category': category, 'device_input': device_input}

        except Exception as e:
            return {'serial': serial, 'success': False, 'error': f"Exception during unassignment: {str(e)}"}

    print(f"[DEBUG] Starting concurrent unassignment tasks for {len(devices_to_process)} devices...")
    unassignment_tasks = [process_single_device(d) for d in devices_to_process]
    unassignment_results = await asyncio.gather(*unassignment_tasks)

    # Aggregate results and prepare for destination batching
    destination_batches = {
        "network": [],
        "compute": [],
        "storage": []
    }
    processed_count = 0
    
    for res in unassignment_results:
        processed_count += 1
        if res['success']:
            destination_batches[res['category']].append(res['device_input'])
        else:
            results['failed'] += 1
            results['details'].append({'serial': res['serial'], 'success': False, 'error': res['error']})
        
        # Update progress and estimate time remaining
        elapsed_time = time.time() - start_time
        avg_time_per_device = elapsed_time / processed_count
        remaining_devices = len(devices_from_csv) - processed_count
        estimated_remaining_seconds = avg_time_per_device * remaining_devices
        
        results['averageTimePerDevice'] = f"{avg_time_per_device:.2f}s"
        if remaining_devices > 0:
            estimated_completion_time = time.time() + estimated_remaining_seconds
            results['estimatedCompletion'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(estimated_completion_time))
        else:
            results['estimatedCompletion'] = 'Completed'

    # Step 4: Add to Destination Inventory in batches
    # NOTE: pycentral's add_devices returns a list of batch-level response dicts like:
    #   [{'code': 202, 'msg': 'Add device request accepted...'}]
    # There is NO per-device serial in the response — it is a single status per API call.
    # Therefore we map: if any resp in resp_list has code 200/201/202 → all serials in that category = success.
    print(f"[DEBUG] Adding devices to destination inventory in batches...")

    # Track which categories we are adding, in order, to map responses back to serials
    ordered_categories = []
    add_to_dest_tasks = []
    for category, devices_list in destination_batches.items():
        if not devices_list:
            continue
        ordered_categories.append(category)
        add_to_dest_tasks.append(async_add_devices_to_inventory(dest_token, category, devices_list))

    destination_add_responses = await asyncio.gather(*add_to_dest_tasks, return_exceptions=True)

    for idx, resp_list in enumerate(destination_add_responses):
        category = ordered_categories[idx]
        serials_in_batch = [d['serialNumber'] for d in destination_batches[category]]

        if isinstance(resp_list, Exception):
            # Exception calling add_devices — all serials in this category failed
            err = str(resp_list)
            print(f"[ERROR] Destination add exception for {category}: {err}")
            for serial in serials_in_batch:
                results['failed'] += 1
                results['details'].append({'serial': serial, 'success': False, 'error': f"Failed to add to Destination: {err}"})
            continue

        # resp_list is a list of batch-level dicts e.g. [{'code': 202, 'msg': '...'}]
        # A 202 means the whole batch was accepted. Check if ANY call succeeded.
        batch_ok = any(r.get('code') in [200, 201, 202] for r in resp_list if isinstance(r, dict))
        error_msg = "; ".join(str(r.get('msg', r)) for r in resp_list if isinstance(r, dict) and r.get('code') not in [200, 201, 202])

        print(f"[DEBUG] Destination batch {category}: batch_ok={batch_ok}, serials={len(serials_in_batch)}")

        for serial in serials_in_batch:
            if batch_ok:
                results['successful'] += 1
                results['details'].append({'serial': serial, 'success': True, 'status': 'Transferred'})
            else:
                results['failed'] += 1
                results['details'].append({'serial': serial, 'success': False, 'error': f"Failed to add to Destination: {error_msg or 'Unknown error'}"})

    total_time = time.time() - start_time
    print(f"[COMPLETE] All {len(devices_from_csv)} devices processed in {total_time:.2f}s")

    try:
        log_operation(
            user=_WORKSPACE_ACTOR, operation="Transfer Workspaces",
            endpoint="/api/bulk/transfer-workspaces",
            input_rows=len(devices_from_csv),
            query_input=f"src→dst: {len(devices_from_csv)} devices",
            total=results.get('total'), success=results.get('successful'), failed=results.get('failed'),
            elapsed_sec=round(total_time, 2), status='ok',
        )
    except Exception: pass

    return JSONResponse(content=results)


# ============================================================
# TRANSFER SUBSCRIPTION KEYS (Source Workspace -> Destination Workspace)
# ============================================================

def parse_csv_keys(file_content: bytes) -> list:
    """Parse CSV and extract subscription keys.
    Accepts a single-column CSV with header 'Key' or 'SubscriptionKey'.
    Returns list of key strings.
    """
    try:
        text = file_content.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(text))
        keys = []
        for row in reader:
            for col in ['Key', 'key', 'SubscriptionKey', 'Subscription Key', 'subscription_key']:
                if col in row and row[col].strip():
                    keys.append(row[col].strip())
                    break
        return keys
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"CSV parse error: {str(e)}")


@router.post("/transfer-subscriptions")
async def transfer_subscriptions(
    source_client_id: str = Form(...),
    source_client_secret: str = Form(...),
    dest_client_id: str = Form(...),
    dest_client_secret: str = Form(...),
    file: UploadFile = File(...)
):
    """
    POC: Transfer subscription keys from Source Workspace to Destination Workspace.
    
    Process:
    1. Authenticate to both workspaces.
    2. Read subscription keys from CSV.
    3. Verify each key exists in the Source Workspace.
    4. Add each verified key to the Destination Workspace via POST /subscriptions.

    NOTE: The GreenLake API does NOT support removing subscriptions via API.
    This is a claim/copy operation — the source workspace retains the subscriptions.
    Rate limit: max 5 keys per request, 4 requests/minute.
    """
    # Authenticate
    try:
        source_client = create_client(source_client_id, source_client_secret)
        dest_client = create_client(dest_client_id, dest_client_secret)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to initialize clients: {str(e)}")

    # Parse CSV
    content = await file.read()
    keys = parse_csv_keys(content)

    if not keys:
        raise HTTPException(status_code=400, detail="No subscription keys found in CSV. Ensure a column named 'Key' or 'SubscriptionKey' exists.")

    print(f"[INFO] Transfer subscriptions: {len(keys)} keys from CSV", flush=True)

    from pycentral.glp.subscriptions import Subscriptions
    subs_api = Subscriptions()

    results = {
        'total': len(keys),
        'successful': 0,
        'failed': 0,
        'details': []
    }

    # Step 1: Verify keys exist in source workspace
    print(f"[INFO] Verifying {len(keys)} keys against Source Workspace...", flush=True)
    source_token = get_token(source_client)

    verified_keys = []
    for key in keys:
        try:
            found, result = subs_api.get_sub_id(source_client, key)
            if found:
                print(f"[OK] Key {key} found in source (ID: {result})", flush=True)
                verified_keys.append({'key': key, 'id': result})
            else:
                print(f"[MISS] Key {key} not found in source: {result}", flush=True)
                results['failed'] += 1
                results['details'].append({
                    'key': key,
                    'success': False,
                    'error': f"Key not found in Source Workspace: {result}"
                })
        except Exception as e:
            results['failed'] += 1
            results['details'].append({'key': key, 'success': False, 'error': f"Lookup error: {str(e)}"})

    print(f"[INFO] {len(verified_keys)}/{len(keys)} keys verified in source. Adding to destination...", flush=True)

    if not verified_keys:
        return JSONResponse(content=results)

    # Step 2: Add verified keys to destination in batches of 5 (API hard limit)
    BATCH_SIZE = 5
    RATE_LIMIT_SLEEP = 16  # 4 requests/min = one per 15s; 16s to be safe

    for batch_start in range(0, len(verified_keys), BATCH_SIZE):
        batch = verified_keys[batch_start:batch_start + BATCH_SIZE]
        batch_keys = [item['key'] for item in batch]

        print(f"[INFO] Adding batch {batch_start // BATCH_SIZE + 1}: {batch_keys}", flush=True)

        try:
            subscriptions_payload = [{"key": k} for k in batch_keys]
            resp = subs_api.add_subscription(dest_client, subscriptions=subscriptions_payload)

            # add_subscription returns the final status dict after polling async progress
            # A successful response has code 200 or the status from the async check
            resp_code = resp.get('code') if isinstance(resp, dict) else None
            resp_msg = resp.get('msg', str(resp)) if isinstance(resp, dict) else str(resp)

            print(f"[DEBUG] Batch response: code={resp_code}, msg={str(resp_msg)[:200]}", flush=True)

            # add_subscription internally polls until done and returns final status
            # Success indicators: code 200, or msg contains success info
            batch_ok = resp_code in [200, 201, 202] if resp_code else False

            # Also accept if resp is a list (when > 5 keys internally batched by library)
            if isinstance(resp, list):
                batch_ok = any(
                    (r.get('code') in [200, 201, 202] if isinstance(r, dict) else False)
                    for r in resp
                )

            for item in batch:
                if batch_ok:
                    results['successful'] += 1
                    results['details'].append({'key': item['key'], 'success': True, 'status': 'Added to Destination'})
                else:
                    results['failed'] += 1
                    results['details'].append({'key': item['key'], 'success': False, 'error': f"API error: {str(resp_msg)[:200]}"})

        except Exception as e:
            print(f"[ERROR] Batch {batch_start // BATCH_SIZE + 1} failed: {e}", flush=True)
            for item in batch:
                results['failed'] += 1
                results['details'].append({'key': item['key'], 'success': False, 'error': f"Exception: {str(e)}"})

        # Rate limit: 4 requests/minute max
        if batch_start + BATCH_SIZE < len(verified_keys):
            print(f"[RATE_LIMIT] Sleeping {RATE_LIMIT_SLEEP}s before next batch...", flush=True)
            time.sleep(RATE_LIMIT_SLEEP)

    print(f"[COMPLETE] Subscription transfer done. {results['successful']} ok, {results['failed']} failed.", flush=True)
    try:
        _keys_preview = ", ".join(k for k in (results.get('details') or [{}])[:5] if isinstance(k, str))
        log_operation(
            user=_WORKSPACE_ACTOR, operation="Transfer Subscriptions",
            endpoint="/api/bulk/transfer-subscriptions",
            input_rows=results.get('total'),
            total=results.get('total'), success=results.get('successful'), failed=results.get('failed'),
            status='ok',
        )
    except Exception: pass
    return JSONResponse(content=results)



@router.get("/debug-subs")
async def debug_subscription_details(keys: str):
    """Debug endpoint to fetch subscription details for comma-separated keys."""
    client = get_glp_client()
    
    from pycentral.glp.subscriptions import Subscriptions
    subs_api = Subscriptions()
    
    key_list = [k.strip() for k in keys.split(',')]
    results = []
    
    for key in key_list:
        sub_id = "NOT FOUND"
        found = False
        
        # Try to resolve ID
        found, result = subs_api.get_sub_id(client, key)
        if found:
            sub_id = result
        
        status = "N/A"
        end_date = "N/A"
        tier = "N/A"
        
        item = None
        if found:
            # Fetch details by ID first
            resp = subs_api.get_subscription(client, filter=f"id eq '{sub_id}'")
            if resp['code'] == 200 and resp['msg']['count'] > 0:
                item = resp['msg']['items'][0]
        
        if not item:
            # Try by key
            resp = subs_api.get_subscription(client, filter=f"key eq '{key}'")
            if resp['code'] == 200 and resp['msg']['count'] > 0:
                 item = resp['msg']['items'][0]
                 if sub_id == "NOT FOUND":
                     sub_id = item.get('id', 'FOUND_BY_KEY')
                     found = True

        if item:
            from datetime import datetime
            now = datetime.utcnow()
            
            status = item.get('status', 'N/A')
            # 'expiresAt' might be unix timestamp or string. 
            # If timestamp, might want to convert, but returning raw is fine for now.
            end_date = item.get('expiresAt', 'N/A') 
            start_date = item.get('startsAt', 'N/A')
            tier = item.get('tier', 'N/A')
            sku_description = item.get('skuDescription', item.get('description', 'N/A'))
            subscription_status = item.get('subscriptionStatus', 'N/A')
            available_quantity = item.get('availableQuantity', 'N/A')
            quantity = item.get('quantity', 'N/A')
            
            calculated_status = 'Active'
            if end_date and end_date != 'N/A':
                try:
                    dt_str = end_date.replace('Z', '')
                    if 'T' in dt_str:
                        exp_dt = datetime.fromisoformat(dt_str)
                    else:
                        exp_dt = datetime.strptime(dt_str.split(' ')[0], '%Y-%m-%d')
                    
                    if exp_dt < now:
                        calculated_status = 'Expired'
                except:
                    pass
        
        results.append({
            "key": key,
            "id": sub_id,
            "tier": tier,
            "status": status,
            "calculated_status": calculated_status,
            "start_date": start_date,
            "end_date": end_date,
            "sku_description": sku_description,
            "subscription_status": subscription_status,
            "available_quantity": available_quantity,
            "total_quantity": quantity,
            "debug_item": item # Add this to see what's inside
        })
        
    return results