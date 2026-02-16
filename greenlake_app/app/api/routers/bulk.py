from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from app.core.client import get_glp_client
from typing import List, Optional
import csv
import io
import time
import requests

router = APIRouter()

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
async def bulk_device_info(file: UploadFile = File(...)):
    """Get device information for all devices in CSV."""
    client = get_glp_client()
    if not client:
        raise HTTPException(status_code=401, detail="Client not configured")
    
    token = get_token(client)
    content = await file.read()
    devices = parse_csv_serials(content)
    
    if not devices:
        raise HTTPException(status_code=400, detail="No serial numbers found in CSV")
    
    results = []
    for device_info in devices:
        serial = device_info['serial']
        device = get_device_by_serial(token, serial)
        if device:
            app_data = device.get('application') or {}
            sub_data = device.get('subscription')
            
            sub_key = None
            if sub_data:
                if isinstance(sub_data, list) and len(sub_data) > 0:
                    sub_key = sub_data[0].get('key')
                elif isinstance(sub_data, dict):
                    sub_key = sub_data.get('key')
            #need to work on the regex matching for better results
            results.append({
                'serial': serial,
                'found': True,
                'data': {
                    'id': device.get('id'),
                    'name': device.get('name'),
                    'model': device.get('model'),
                    'macAddress': device.get('macAddress'),
                    'deviceType': device.get('deviceType'),
                    'status': device.get('status'),
                    'application': app_data.get('name') if app_data else None,
                    'subscription': sub_key
                }
            })
        else:
            results.append({'serial': serial, 'found': False, 'error': 'Device not found'})
    
    return JSONResponse(content={'total': len(devices), 'results': results})


# ============================================================
# ASSIGN SUBSCRIPTION
# ============================================================

@router.post("/assign-subscription")
async def bulk_assign_subscription(
    subscription_key: str = Form(...),
    file: UploadFile = File(...)
):
    """Bulk assign subscription to devices from CSV."""
    client = get_glp_client()
    if not client:
        raise HTTPException(status_code=401, detail="Client not configured")
    
    token = get_token(client)
    
    # Get subscription ID from key
    subscription_id = get_subscription_id_from_key(token, subscription_key)
    if not subscription_id:
        raise HTTPException(status_code=404, detail=f"Subscription key '{subscription_key}' not found")
    
    print(f"[DEBUG] Found subscription ID: {subscription_id} for key: {subscription_key}", flush=True)
    
    # Parse CSV
    content = await file.read()
    devices = parse_csv_serials(content)
    
    if not devices:
        raise HTTPException(status_code=400, detail="No serial numbers found in CSV")
    
    print(f"[DEBUG] Processing {len(devices)} devices for subscription assignment", flush=True)
    
    # Collect device UUIDs
    device_map = {}
    for device_info in devices:
        serial = device_info['serial']
        device = get_device_by_serial(token, serial)
        if device and device.get('id'):
            device_map[serial] = device['id']
            print(f"[DEBUG] Found device {serial} with ID {device['id']}", flush=True)
        else:
            print(f"[DEBUG] Device {serial} not found in system", flush=True)
    
    if not device_map:
        raise HTTPException(status_code=404, detail="No devices found from CSV")
    
    # Assign subscription to each device individually
    results = {'total': len(devices), 'successful': 0, 'failed': 0, 'details': []}
    url = f"{API_ENDPOINT}/devices/v1beta1/devices"
    
    for serial, device_uuid in device_map.items():
        try:
            headers = get_auth_headers(token, "application/merge-patch+json")
            params = {"id": device_uuid}
            payload = {"subscription": [{"id": subscription_id}]}
            
            print(f"[DEBUG] PATCH {url}?id={device_uuid}")
            print(f"[DEBUG] Payload: {payload}")
            
            response = requests.patch(url, headers=headers, params=params, json=payload, timeout=30)
            
            print(f"[DEBUG] Device {serial}: Status {response.status_code}")
            print(f"[DEBUG] Response headers: {dict(response.headers)}")
            print(f"[DEBUG] Response body: {response.text[:500]}")
            
            if response.status_code == 200:
                results['successful'] += 1
                results['details'].append({'serial': serial, 'success': True, 'status': 'Completed'})
                
            elif response.status_code == 202:
                # Async operation - check progress
                progress_url = response.headers.get('location', '')
                print(f"[DEBUG] Async accepted. Location: {progress_url}")
                
                if progress_url:
                    async_result = check_async_progress(token, progress_url)
                    
                    if async_result['success'] is True:
                        results['successful'] += 1
                        results['details'].append({'serial': serial, 'success': True, 'status': 'Completed'})
                    elif async_result['success'] is False:
                        results['failed'] += 1
                        results['details'].append({'serial': serial, 'success': False, 'error': async_result['details']})
                    else:
                        # Still processing
                        results['successful'] += 1
                        results['details'].append({'serial': serial, 'success': True, 'status': 'Processing (check later)'})
                else:
                    # 202 but no location header - try to get transactionId from body
                    try:
                        resp_data = response.json()
                        txn_id = resp_data.get('transactionId', '')
                        if txn_id:
                            progress_url = f"{API_ENDPOINT}/async-operations/v1/async-operations/{txn_id}"
                            async_result = check_async_progress(token, progress_url)
                            
                            if async_result['success'] is True:
                                results['successful'] += 1
                                results['details'].append({'serial': serial, 'success': True, 'status': 'Completed'})
                            elif async_result['success'] is False:
                                results['failed'] += 1
                                results['details'].append({'serial': serial, 'success': False, 'error': async_result['details']})
                            else:
                                results['successful'] += 1
                                results['details'].append({'serial': serial, 'success': True, 'status': 'Processing'})
                        else:
                            results['successful'] += 1
                            results['details'].append({'serial': serial, 'success': True, 'status': '202 Accepted'})
                    except:
                        results['successful'] += 1
                        results['details'].append({'serial': serial, 'success': True, 'status': '202 Accepted'})
            else:
                results['failed'] += 1
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message', error_data.get('description', str(error_data)))
                except:
                    error_msg = response.text[:200] if response.text else error_msg
                
                results['details'].append({'serial': serial, 'success': False, 'error': error_msg})
        
        except Exception as e:
            results['failed'] += 1
            results['details'].append({'serial': serial, 'success': False, 'error': str(e)})
        
        time.sleep(0.5)
    
    # Add not-found serials
    for device_info in devices:
        serial = device_info['serial']
        if serial not in device_map:
            results['failed'] += 1
            results['details'].append({'serial': serial, 'success': False, 'error': 'Device not found'})
    
    return JSONResponse(content=results)


# ============================================================
# UNASSIGN SUBSCRIPTION
# ============================================================

@router.post("/unassign-subscription")
async def bulk_unassign_subscription(file: UploadFile = File(...)):
    """Bulk remove subscriptions from devices."""
    client = get_glp_client()
    if not client:
        raise HTTPException(status_code=401, detail="Client not configured")
    
    token = get_token(client)
    content = await file.read()
    devices = parse_csv_serials(content)
    
    if not devices:
        raise HTTPException(status_code=400, detail="No serial numbers found in CSV")
    
    results = {'total': len(devices), 'successful': 0, 'failed': 0, 'details': []}
    url = f"{API_ENDPOINT}/devices/v1beta1/devices"
    
    for device_info in devices:
        serial = device_info['serial']
        device = get_device_by_serial(token, serial)
        if not device or not device.get('id'):
            results['failed'] += 1
            results['details'].append({'serial': serial, 'success': False, 'error': 'Device not found'})
            continue
        
        device_uuid = device['id']
        
        try:
            headers = get_auth_headers(token, "application/merge-patch+json")
            params = {"id": device_uuid}
            # Empty subscription array to unassign
            payload = {"subscription": []}
            
            response = requests.patch(url, headers=headers, params=params, json=payload, timeout=30)
            
            print(f"[DEBUG] Unassign {serial}: Status {response.status_code}")
            
            if response.status_code == 200:
                results['successful'] += 1
                results['details'].append({'serial': serial, 'success': True, 'status': 'Completed'})
            elif response.status_code == 202:
                progress_url = response.headers.get('location', '')
                if progress_url:
                    async_result = check_async_progress(token, progress_url)
                    if async_result['success'] is True:
                        results['successful'] += 1
                        results['details'].append({'serial': serial, 'success': True, 'status': 'Completed'})
                    elif async_result['success'] is False:
                        results['failed'] += 1
                        results['details'].append({'serial': serial, 'success': False, 'error': async_result['details']})
                    else:
                        results['successful'] += 1
                        results['details'].append({'serial': serial, 'success': True, 'status': 'Processing'})
                else:
                    results['successful'] += 1
                    results['details'].append({'serial': serial, 'success': True, 'status': '202 Accepted'})
            else:
                results['failed'] += 1
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message', str(error_data))
                except:
                    pass
                results['details'].append({'serial': serial, 'success': False, 'error': error_msg})
        
        except Exception as e:
            results['failed'] += 1
            results['details'].append({'serial': serial, 'success': False, 'error': str(e)})
        
        time.sleep(0.5)
    
    return JSONResponse(content=results)


# ============================================================
# ADD DEVICES TO APPLICATION
# ============================================================

@router.post("/transfer-devices")
async def bulk_transfer_devices(
    application_id: str = Form(...),
    region: str = Form(...),
    file: UploadFile = File(...)
):
    """Bulk transfer devices to an application using raw requests."""
    client = get_glp_client()
    if not client:
        raise HTTPException(status_code=401, detail="Client not configured")
    
    token = get_token(client)
    content = await file.read()
    devices = parse_csv_serials(content)
    
    if not devices:
        raise HTTPException(status_code=400, detail="No serial numbers found in CSV")
    
    # Extract only serials for batch processing compatibility
    serials = [d['serial'] for d in devices]
    
    results = {'total': len(devices), 'successful': 0, 'failed': 0, 'details': []}
    url = f"{API_ENDPOINT}/devices/v1beta1/devices"
    
    # Process in batches of 5 (API limit)
    batch_size = 5
    for i in range(0, len(serials), batch_size):
        batch = serials[i:i+batch_size]
        batch_devices = []  # (serial, uuid) pairs
        
        for serial in batch:
            device = get_device_by_serial(token, serial)
            if device and device.get('id'):
                batch_devices.append((serial, device['id']))
            else:
                results['failed'] += 1
                results['details'].append({'serial': serial, 'success': False, 'error': 'Device not found'})
        
        if not batch_devices:
            continue
        
        # Multiple device IDs as repeated query params
        batch_uuids = [uuid for _, uuid in batch_devices]
        batch_serials = [s for s, _ in batch_devices]
        
        try:
            headers = get_auth_headers(token, "application/merge-patch+json")
            # Use list of tuples for multiple id params
            params = [("id", uuid) for uuid in batch_uuids]
            payload = {
                "application": {"id": application_id},
                "region": region
            }
            
            print(f"[DEBUG] Transfer batch: {batch_serials}")
            print(f"[DEBUG] PATCH {url} with {len(batch_uuids)} device(s)")
            
            response = requests.patch(url, headers=headers, params=params, json=payload, timeout=30)
            
            print(f"[DEBUG] Transfer response: {response.status_code}")
            print(f"[DEBUG] Response body: {response.text[:500]}")
            
            if response.status_code == 200:
                results['successful'] += len(batch_serials)
                for serial in batch_serials:
                    results['details'].append({'serial': serial, 'success': True, 'status': 'Completed'})
                    
            elif response.status_code == 202:
                # Check async progress
                progress_url = response.headers.get('location', '')
                
                if not progress_url:
                    try:
                        resp_data = response.json()
                        txn_id = resp_data.get('transactionId', '')
                        if txn_id:
                            progress_url = f"{API_ENDPOINT}/async-operations/v1/async-operations/{txn_id}"
                    except:
                        pass
                
                if progress_url:
                    print(f"[DEBUG] Checking async progress: {progress_url}")
                    async_result = check_async_progress(token, progress_url, max_wait=60)
                    
                    # Create UUID to Serial map for this batch
                    uuid_to_serial = {uuid: s for s, uuid in batch_devices}
                    
                    if async_result['status'] in ['COMPLETED', 'SUCCEEDED', 'SUCCESS']:
                        results['successful'] += len(batch_serials)
                        for serial in batch_serials:
                            results['details'].append({'serial': serial, 'success': True, 'status': 'Completed'})
                            
                    elif async_result['status'] in ['FAILED', 'ERROR']:
                        result_data = async_result.get('result', {})
                        succeeded = result_data.get('succeededDevices', [])
                        failed = result_data.get('failedDevices', [])
                        
                        # Handle successes
                        if succeeded and isinstance(succeeded, list):
                            for uuid in succeeded:
                                if uuid in uuid_to_serial:
                                    serial = uuid_to_serial[uuid]
                                    results['successful'] += 1
                                    results['details'].append({'serial': serial, 'success': True, 'status': 'Completed'})
                        
                        # Handle failures
                        if failed and isinstance(failed, list):
                            for uuid in failed:
                                if uuid in uuid_to_serial:
                                    serial = uuid_to_serial[uuid]
                                    results['failed'] += 1
                                    # Try to find specific error if available or use generic
                                    error_msg = async_result.get('details', 'Transfer failed')
                                    results['details'].append({'serial': serial, 'success': False, 'error': error_msg})
                        
                        # Fallback for devices not covered
                        processed_uuids = set(succeeded if isinstance(succeeded, list) else []) | \
                                          set(failed if isinstance(failed, list) else [])
                                          
                        for uuid, serial in uuid_to_serial.items():
                            if uuid not in processed_uuids:
                                results['failed'] += 1
                                results['details'].append({
                                    'serial': serial, 
                                    'success': False, 
                                    'error': async_result.get('details', 'Start Async Failed')
                                })
                    else:
                        results['successful'] += len(batch_serials)
                        for serial in batch_serials:
                            results['details'].append({'serial': serial, 'success': True, 'status': 'Processing'})
                else:
                    results['successful'] += len(batch_serials)
                    for serial in batch_serials:
                        results['details'].append({'serial': serial, 'success': True, 'status': '202 Accepted'})
            else:
                results['failed'] += len(batch_serials)
                error_msg = f"HTTP {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get('message', str(error_data))
                except:
                    error_msg = response.text[:200] if response.text else error_msg
                
                for serial in batch_serials:
                    results['details'].append({'serial': serial, 'success': False, 'error': error_msg})
        
        except Exception as e:
            results['failed'] += len(batch_serials)
            for serial in batch_serials:
                results['details'].append({'serial': serial, 'success': False, 'error': str(e)})
        
        # Rate limiting between batches
        if i + batch_size < len(serials):
            time.sleep(12)
    
    return JSONResponse(content=results)


# ============================================================
# TRANSFER WORKSPACES (Source -> Destination)
# ============================================================

from pycentral import NewCentralBase

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
    2. Remove from Source Inventory.
    3. Add to Destination Inventory.
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
    
    import time
    start_time = time.time()
    results['startTime'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(start_time))
    
    # Process each device
    processed_count = 0
    for device_info in devices_from_csv:
        serial = device_info['serial']
        mac_from_csv = device_info.get('mac')  # Optional MAC from CSV
        
        try:
            # 1. Verify Device in Source
            print(f"[DEBUG] Looking up device {serial} in source workspace")
            source_device = get_device_by_serial(get_token(source_client), serial)
            print(f"[DEBUG] Device lookup result: {source_device is not None}")
            
            if source_device is None:
                print(f"[DEBUG] Device {serial} not found in source workspace")
                results['failed'] += 1
                results['details'].append({'serial': serial, 'success': False, 'error': 'Device not found in Source'})
                continue
            
            # Extract details needed for adding to destination
            # Prefer MAC from CSV, fallback to source device
            print(f"[DEBUG] Device {serial} found: {source_device.get('id', 'NO_ID')}")
            device_type = source_device.get('deviceType', 'NETWORK').upper() # NETWORK, COMPUTE, STORAGE
            mac_address = mac_from_csv if mac_from_csv else source_device.get('macAddress')
            part_number = source_device.get('model') # Often mapped to model/part
            
            if not mac_address:
                print(f"[WARN] Device {serial} has no MAC address in CSV or source device")

            # 2. Unassign from Source (Application AND Subscription)
            # NOTE: According to GreenLake API docs, only ONE operation per API call is allowed
            # We must unassign application first, then subscription in separate calls
            
            # 2a. Unassign from Application (if assigned)
            # Handle case where 'application' field exists but is None
            app = source_device.get('application')
            app_id = app.get('id') if app and isinstance(app, dict) else None
            
            if app_id:
                print(f"[DEBUG] Unassigning {serial} from Application {app_id}")
                url = f"{API_ENDPOINT}/devices/v1beta1/devices"
                headers = get_auth_headers(get_token(source_client), "application/merge-patch+json")
                params = {"id": source_device['id']}
                payload = {"application": {"id": None}, "region": None}
                
                resp = requests.patch(url, headers=headers, params=params, json=payload, timeout=30)
                print(f"[DEBUG] Unassign app response: {resp.status_code}")
                if resp.status_code not in [200, 202]:
                    print(f"Warning: Failed to unassign app: {resp.text}")
                    # Continue anyway - might already be unassigned
            else:
                print(f"[DEBUG] Device {serial} has no application assignment")
            
            # 2b. Unassign from Subscription (if assigned) - SEPARATE API CALL
            # Handle case where 'subscription' field exists but is None or empty
            subs = source_device.get('subscription')
            has_subscription = subs and isinstance(subs, list) and len(subs) > 0
            
            if has_subscription:
                print(f"[DEBUG] Unassigning {serial} from Subscription")
                url = f"{API_ENDPOINT}/devices/v1beta1/devices"
                headers = get_auth_headers(get_token(source_client), "application/merge-patch+json")
                params = {"id": source_device['id']}
                payload = {"subscription": []}  # Empty array to remove subscription
                
                resp = requests.patch(url, headers=headers, params=params, json=payload, timeout=30)
                print(f"[DEBUG] Unassign subscription response: {resp.status_code}")
                if resp.status_code not in [200, 202]:
                    print(f"Warning: Failed to unassign subscription: {resp.text}")
                    # Continue anyway
            else:
                print(f"[DEBUG] Device {serial} has no subscription assignment")

            # 3. SKIP REMOVAL - No direct API exists for device deletion
            # After unassignment, the device should be available for claiming by destination workspace
            print(f"[DEBUG] Skipping removal - device {serial} unassigned and ready for destination")

            # 4. Add to Destination Inventory
            # API requires: serialnumber and macaddress (both must not be null)
            
            # Validate required fields
            if not mac_address:
                print(f"[ERROR] Device {serial} has no MAC address - cannot add to destination")
                results['failed'] += 1
                results['details'].append({
                    'serial': serial, 
                    'success': False, 
                    'error': 'Device has no MAC address (required for adding to inventory)'
                })
                continue
            
            
            print(f"[DEBUG] Adding device {serial} (MAC: {mac_address}) to destination")
            
            # IMPORTANT: GreenLake API expects camelCase field names, NOT snake_case
            device_input = {
                "serialNumber": serial,  # NOT serial_number
                "macAddress": mac_address  # NOT mac_address
            }
            if part_number:
                device_input["partNumber"] = part_number  # NOT part_number
            
            print(f"[DEBUG] Device payload: {device_input}")
            
            # Categorize based on type (defaulting to network)
            category = "network"
            if "COMPUTE" in device_type: 
                category = "compute"
            elif "STORAGE" in device_type:
                category = "storage"
            
            print(f"[DEBUG] Device type: {device_type}, category: {category}")
            
            from pycentral.glp.devices import Devices
            devices_api = Devices()
            
            # Add to destination using library method
            add_resp_list = []
            if category == "network":
                add_resp_list = devices_api.add_devices(dest_client, network=[device_input])
            elif category == "compute":
                add_resp_list = devices_api.add_devices(dest_client, compute=[device_input])
            elif category == "storage":
                add_resp_list = devices_api.add_devices(dest_client, storage=[device_input])
            
            # Check response
            # add_devices returns list of responses
            success = False
            error_msg = "Unknown error adding to destination"
            
            for resp in add_resp_list:
                if resp.get('code') in [200, 201, 202]:
                    success = True
                    break
                else:
                    error_msg = resp.get('msg', str(resp))
            
            if success:
                results['successful'] += 1
                results['details'].append({'serial': serial, 'success': True, 'status': 'Transferred'})
            else:
                results['failed'] += 1
                results['details'].append({'serial': serial, 'success': False, 'error': f"Failed to add to Destination: {error_msg}"})
                # Revert? Add back to source? (Complex rollback, for now just report error)
                
        except Exception as e:
            results['failed'] += 1
            results['details'].append({'serial': serial, 'success': False, 'error': f"Exception: {str(e)}"})
            import traceback
            traceback.print_exc()
        
        # Update progress and estimate time remaining
        processed_count += 1
        elapsed_time = time.time() - start_time
        avg_time_per_device = elapsed_time / processed_count
        remaining_devices = len(devices_from_csv) - processed_count
        estimated_remaining_seconds = avg_time_per_device * remaining_devices
        
        results['averageTimePerDevice'] = f"{avg_time_per_device:.2f}s"
        if remaining_devices > 0:
            estimated_completion_time = time.time() + estimated_remaining_seconds
            results['estimatedCompletion'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(estimated_completion_time))
            print(f"[PROGRESS] {processed_count}/{len(devices_from_csv)} completed. Est. {estimated_remaining_seconds:.0f}s remaining")
        else:
            results['estimatedCompletion'] = 'Completed'
            total_time = time.time() - start_time
            print(f"[COMPLETE] All {processed_count} devices processed in {total_time:.2f}s")

    return JSONResponse(content=results)


@router.get("/debug-subs")
async def debug_subscription_details(keys: str):
    """Debug endpoint to fetch subscription details for comma-separated keys."""
    client = get_glp_client()
    if not client:
        return {"error": "Client not configured"}
    
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