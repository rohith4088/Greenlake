import json
import time
import requests

# ==========================================
# CONFIGURATION
# ==========================================
CLIENT_ID = "ee38aac8-02a9-4526-89e6-9057304dac14"
CLIENT_SECRET = "2ca1ea821ee6421f9486836ced9c2d00"

TENANT_WORKSPACE_ID = "e6c4235403fb11f08ba1a249caf7b79c"

SERIAL_NUMBER = "CN34L3MD9V"
SUBSCRIPTION_KEY = "PAYHYJEY6573D4"

# Set to None to skip (this tenant has no application catalog - returned 404)
APPLICATION_ID = None
REGION = "US West"

BASE_API_URL = "https://global.api.greenlake.hpe.com"
AUTH_URL = "https://sso.common.cloud.hpe.com/as/token.oauth2"

# ==========================================
# 1. AUTH - SSO Token + Workspace-Id header
#    (Token Exchange not permitted for this client;
#     SSO token IS accepted by the API Gateway with Workspace-Id routing)
# ==========================================
def get_access_token():
    resp = requests.post(
        AUTH_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials"},
        auth=(CLIENT_ID, CLIENT_SECRET)
    )
    resp.raise_for_status()
    return resp.json()["access_token"]

def get_base_headers(token, merge_patch=False):
    headers = {
        "Authorization": f"Bearer {token}",
        "Workspace-Id": TENANT_WORKSPACE_ID
    }
    if merge_patch:
        headers["Content-Type"] = "application/merge-patch+json"
    return headers

# ==========================================
# 2. LOOKUPS
# ==========================================
def get_device_details(token, serial):
    url = f"{BASE_API_URL}/devices/v1beta1/devices"
    resp = requests.get(url, headers=get_base_headers(token), params={"filter": f"serialNumber eq '{serial}'"})
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        raise Exception(f"Device {serial} not found in GreenLake inventory at all.")
    d = items[0]
    print(f"  Device ID   : {d['id']}")
    print(f"  MAC Address : {d.get('macAddress', 'Unknown')}")
    print(f"  Status      : {d.get('status','?')}")
    print(f"  Application : {json.dumps(d.get('application'))}")
    print(f"  Subscription: {json.dumps(d.get('subscription'))}")
    return d

def get_subscription_id(token, sub_key):
    url = f"{BASE_API_URL}/subscriptions/v1/subscriptions"
    resp = requests.get(url, headers=get_base_headers(token), params={"filter": f"key eq '{sub_key}'"})
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        raise Exception(f"Subscription key {sub_key} not found in this tenant.")
    s = items[0]
    print(f"  Subscription ID  : {s['id']}")
    print(f"  Subscription Tier: {s.get('tier')}")
    return s["id"]

# ==========================================
# 3. WORKSPACE CLAIMING
# ==========================================
def claim_device_to_workspace(token, serial, mac_address):
    print("\nStep 1/2: Claiming unassigned device into Tenant Workspace...")
    if not mac_address:
        print("  -> ERROR: GreenLake requires a MAC Address to claim a network device into a workspace!")
        return False
        
    url = f"{BASE_API_URL}/devices/v1beta1/devices"
    payload = {
        "network": [{
            "serialNumber": serial,
            "macAddress": mac_address
        }],
        "compute": [],
        "storage": []
    }
    resp = requests.post(url, headers=get_base_headers(token), json=payload)
    if resp.status_code in [200, 201]:
        print("  -> Success! Device is now rigidly bound to the Tenant Workspace.\n")
        return True
    elif resp.status_code == 202:
        print("  -> Accepted (async). Waiting for claim processing...")
        progress_url = resp.headers.get("location", "")
        if not progress_url:
            txn_id = resp.json().get("transactionId", "")
            progress_url = f"{BASE_API_URL}/async-operations/v1/async-operations/{txn_id}"
        return check_async_progress(token, progress_url)
    else:
        print(f"  -> WARNING: Claim failed (might already be claimed?): HTTP {resp.status_code}: {resp.text}\n")
        return True

# ==========================================
# 4. ASYNC TRACKING
# ==========================================
def check_async_progress(token, progress_url):
    if not progress_url.startswith("http"):
        progress_url = f"{BASE_API_URL}{progress_url}"
    print(f"  Polling: {progress_url}")
    for i in range(15):
        time.sleep(5)
        resp = requests.get(progress_url, headers=get_base_headers(token))
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("status", "").upper()
            if status in ["SUCCEEDED", "COMPLETED", "SUCCESS"]:
                print(f"  -> SUCCESSFUL after {(i+1)*5}s!\n")
                return True
            elif status in ["FAILED", "ERROR", "TIMEOUT"]:
                print(f"  -> FAILED: {json.dumps(data.get('result', {}), indent=2)}")
                return False
            else:
                print(f"  -> Still processing [{status}] ({(i+1)*5}s elapsed)...")
        else:
            print(f"  -> Poll returned HTTP {resp.status_code}")
    print("  -> Timed out after 75s.\n")
    return False

# ==========================================
# 4. PATCH HELPER
# ==========================================
def patch_device(token, device_id, payload, label):
    print(f"\n{label}")
    resp = requests.patch(
        f"{BASE_API_URL}/devices/v1beta1/devices",
        headers=get_base_headers(token, merge_patch=True),
        params={"id": device_id},
        json=payload
    )
    if resp.status_code in [200, 201, 204]:
        print("  -> Applied immediately. Done!\n")
        return True
    elif resp.status_code == 202:
        print("  -> Accepted (async). Waiting for backend worker...")
        progress_url = resp.headers.get("location", "")
        if not progress_url:
            txn_id = resp.json().get("transactionId", "")
            progress_url = f"{BASE_API_URL}/devices/v1beta1/async-operations/{txn_id}"
        return check_async_progress(token, progress_url)
    else:
        print(f"  -> FAILED: HTTP {resp.status_code}: {resp.text}\n")
        return False

# ==========================================
# 5. MAIN
# ==========================================
if __name__ == "__main__":
    try:
        print("Authenticating...")
        token = get_access_token()
        print("OK.\n")

        print("Looking up device...")
        device_info = get_device_details(token, SERIAL_NUMBER)
        device_id = device_info["id"]

        print("\nLooking up subscription...")
        sub_id = get_subscription_id(token, SUBSCRIPTION_KEY)

        # 1. Claim device to Tenant Workspace (mandatory for floating devices)
        mac_address = device_info.get("macAddress")
        claim_device_to_workspace(token, SERIAL_NUMBER, mac_address)

        # 2. Only try application assignment if explicitly configured
        if APPLICATION_ID:
            patch_device(token, device_id, {"application": {"id": APPLICATION_ID}, "region": REGION}, "\nStep 1/2: Assigning Application...")
            print("Waiting 3s before subscription step...")
            time.sleep(3)

        # 3. Finally apply the subscription
        patch_device(token, device_id, {"subscription": [{"id": sub_id}]}, "\nStep 2/2: Assigning Subscription...")

    except Exception as e:
        print(f"\nScript Error: {e}")
