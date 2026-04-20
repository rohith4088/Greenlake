# # import json
# # import time
# # import requests

# # # ==========================================
# # # CONFIGURATION
# # # ==========================================
# # CLIENT_ID = "ee38aac8-02a9-4526-89e6-9057304dac14"
# # CLIENT_SECRET = "2ca1ea821ee6421f9486836ced9c2d00"

# # TENANT_WORKSPACE_ID = "e6c4235403fb11f08ba1a249caf7b79c"

# # SERIAL_NUMBER = "CN34L3MD9V"
# # SUBSCRIPTION_KEY = "PAYHYJEY6573D4"

# # # Set to None to skip (this tenant has no application catalog - returned 404)
# # APPLICATION_ID = None
# # REGION = "US West"

# # BASE_API_URL = "https://global.api.greenlake.hpe.com"
# # AUTH_URL = "https://sso.common.cloud.hpe.com/as/token.oauth2"

# # # ==========================================
# # # 1. AUTH - SSO Token + Workspace-Id header
# # #    (Token Exchange not permitted for this client;
# # #     SSO token IS accepted by the API Gateway with Workspace-Id routing)
# # # ==========================================
# # def get_access_token():
# #     resp = requests.post(
# #         AUTH_URL,
# #         headers={"Content-Type": "application/x-www-form-urlencoded"},
# #         data={"grant_type": "client_credentials"},
# #         auth=(CLIENT_ID, CLIENT_SECRET)
# #     )
# #     resp.raise_for_status()
# #     return resp.json()["access_token"]

# # def get_base_headers(token, merge_patch=False):
# #     headers = {
# #         "Authorization": f"Bearer {token}",
# #         "Workspace-Id": TENANT_WORKSPACE_ID
# #     }
# #     if merge_patch:
# #         headers["Content-Type"] = "application/merge-patch+json"
# #     return headers

# # # ==========================================
# # # 2. LOOKUPS
# # # ==========================================
# # def get_device_details(token, serial):
# #     url = f"{BASE_API_URL}/devices/v1beta1/devices"
# #     resp = requests.get(url, headers=get_base_headers(token), params={"filter": f"serialNumber eq '{serial}'"})
# #     resp.raise_for_status()
# #     items = resp.json().get("items", [])
# #     if not items:
# #         raise Exception(f"Device {serial} not found in GreenLake inventory at all.")
# #     d = items[0]
# #     print(f"  Device ID   : {d['id']}")
# #     print(f"  MAC Address : {d.get('macAddress', 'Unknown')}")
# #     print(f"  Status      : {d.get('status','?')}")
# #     print(f"  Application : {json.dumps(d.get('application'))}")
# #     print(f"  Subscription: {json.dumps(d.get('subscription'))}")
# #     return d

# # def get_subscription_id(token, sub_key):
# #     url = f"{BASE_API_URL}/subscriptions/v1/subscriptions"
# #     resp = requests.get(url, headers=get_base_headers(token), params={"filter": f"key eq '{sub_key}'"})
# #     resp.raise_for_status()
# #     items = resp.json().get("items", [])
# #     if not items:
# #         raise Exception(f"Subscription key {sub_key} not found in this tenant.")
# #     s = items[0]
# #     print(f"  Subscription ID  : {s['id']}")
# #     print(f"  Subscription Tier: {s.get('tier')}")
# #     return s["id"]

# # # ==========================================
# # # 3. WORKSPACE CLAIMING
# # # ==========================================
# # def claim_device_to_workspace(token, serial, mac_address):
# #     print("\nStep 1/2: Claiming unassigned device into Tenant Workspace...")
# #     if not mac_address:
# #         print("  -> ERROR: GreenLake requires a MAC Address to claim a network device into a workspace!")
# #         return False
        
# #     url = f"{BASE_API_URL}/devices/v1beta1/devices"
# #     payload = {
# #         "network": [{
# #             "serialNumber": serial,
# #             "macAddress": mac_address
# #         }],
# #         "compute": [],
# #         "storage": []
# #     }
# #     resp = requests.post(url, headers=get_base_headers(token), json=payload)
# #     if resp.status_code in [200, 201]:
# #         print("  -> Success! Device is now rigidly bound to the Tenant Workspace.\n")
# #         return True
# #     elif resp.status_code == 202:
# #         print("  -> Accepted (async). Waiting for claim processing...")
# #         progress_url = resp.headers.get("location", "")
# #         if not progress_url:
# #             txn_id = resp.json().get("transactionId", "")
# #             progress_url = f"{BASE_API_URL}/async-operations/v1/async-operations/{txn_id}"
# #         return check_async_progress(token, progress_url)
# #     else:
# #         print(f"  -> WARNING: Claim failed (might already be claimed?): HTTP {resp.status_code}: {resp.text}\n")
# #         return True

# # # ==========================================
# # # 4. ASYNC TRACKING
# # # ==========================================
# # def check_async_progress(token, progress_url):
# #     if not progress_url.startswith("http"):
# #         progress_url = f"{BASE_API_URL}{progress_url}"
# #     print(f"  Polling: {progress_url}")
# #     for i in range(15):
# #         time.sleep(5)
# #         resp = requests.get(progress_url, headers=get_base_headers(token))
# #         if resp.status_code == 200:
# #             data = resp.json()
# #             status = data.get("status", "").upper()
# #             if status in ["SUCCEEDED", "COMPLETED", "SUCCESS"]:
# #                 print(f"  -> SUCCESSFUL after {(i+1)*5}s!\n")
# #                 return True
# #             elif status in ["FAILED", "ERROR", "TIMEOUT"]:
# #                 print(f"  -> FAILED: {json.dumps(data.get('result', {}), indent=2)}")
# #                 return False
# #             else:
# #                 print(f"  -> Still processing [{status}] ({(i+1)*5}s elapsed)...")
# #         else:
# #             print(f"  -> Poll returned HTTP {resp.status_code}")
# #     print("  -> Timed out after 75s.\n")
# #     return False

# # # ==========================================
# # # 4. PATCH HELPER
# # # ==========================================
# # def patch_device(token, device_id, payload, label):
# #     print(f"\n{label}")
# #     resp = requests.patch(
# #         f"{BASE_API_URL}/devices/v1beta1/devices",
# #         headers=get_base_headers(token, merge_patch=True),
# #         params={"id": device_id},
# #         json=payload
# #     )
# #     if resp.status_code in [200, 201, 204]:
# #         print("  -> Applied immediately. Done!\n")
# #         return True
# #     elif resp.status_code == 202:
# #         print("  -> Accepted (async). Waiting for backend worker...")
# #         progress_url = resp.headers.get("location", "")
# #         if not progress_url:
# #             txn_id = resp.json().get("transactionId", "")
# #             progress_url = f"{BASE_API_URL}/devices/v1beta1/async-operations/{txn_id}"
# #         return check_async_progress(token, progress_url)
# #     else:
# #         print(f"  -> FAILED: HTTP {resp.status_code}: {resp.text}\n")
# #         return False

# # # ==========================================
# # # 5. MAIN
# # # ==========================================
# # if __name__ == "__main__":
# #     try:
# #         print("Authenticating...")
# #         token = get_access_token()
# #         print("OK.\n")

# #         print("Looking up device...")
# #         device_info = get_device_details(token, SERIAL_NUMBER)
# #         device_id = device_info["id"]

# #         print("\nLooking up subscription...")
# #         sub_id = get_subscription_id(token, SUBSCRIPTION_KEY)

# #         # 1. Claim device to Tenant Workspace (mandatory for floating devices)
# #         mac_address = device_info.get("macAddress")
# #         claim_device_to_workspace(token, SERIAL_NUMBER, mac_address)

# #         # 2. Only try application assignment if explicitly configured
# #         if APPLICATION_ID:
# #             patch_device(token, device_id, {"application": {"id": APPLICATION_ID}, "region": REGION}, "\nStep 1/2: Assigning Application...")
# #             print("Waiting 3s before subscription step...")
# #             time.sleep(3)

# #         # 3. Finally apply the subscription
# #         patch_device(token, device_id, {"subscription": [{"id": sub_id}]}, "\nStep 2/2: Assigning Subscription...")

# #     except Exception as e:
# #         print(f"\nScript Error: {e}")


# import sys
# import csv
# import json
# import time
# import requests
# from concurrent.futures import ThreadPoolExecutor

# INPUT_FILE = "../test.csv"
# OUTPUT_FILE = "../workspaces_result.csv"

# def parse_workspace(cust: dict, search_string: str) -> dict:
#     contact = cust.get("contact") or {}
#     account = cust.get("account") or {}
#     address = contact.get("address") or {}
#     prefs   = cust.get("preferences") or {}

#     return {
#         "search_string": search_string,
#         "customer_id": cust.get("customer_id", ""),
#         "company_name": contact.get("company_name", ""),
#         "account_type": cust.get("account_type") or account.get("account_type", ""),
#         "status": account.get("status", ""),
#         "msp_id": cust.get("msp_id", ""),
#         "email": cust.get("email") or contact.get("email", ""),
#         "created_by": contact.get("created_by", ""),
#         "phone_number": contact.get("phone_number", ""),
#         "region": cust.get("region", ""),
#         "organization_id": cust.get("organization_id", ""),
#         "activate_customer_id": cust.get("activate_customer_id", ""),
#         "multi_fa_enabled": prefs.get("multi_fa_enabled", ""),
#         "created_at": account.get("created_at", ""),
#         "updated_at": account.get("updated_at", ""),
#         "address_street": contact.get("street_address", address.get("street_address", "")),
#         "address_city": address.get("city", ""),
#         "address_state": address.get("state_or_region", ""),
#         "address_zip": address.get("zip", ""),
#         "address_country": address.get("country_code", "")
#     }

# def fetch_workspace(search_string, headers, endpoint):
#     try:
#         resp = requests.get(
#             endpoint,
#             headers=headers,
#             params={"limit": 10, "offset": 0, "search_string": search_string},
#             timeout=30
#         )
#         if resp.status_code != 200:
#             return None, f"HTTP {resp.status_code}: {resp.text[:100]}"
#         raw = resp.json().get("customers", [])
#         return [parse_workspace(c, search_string) for c in raw], None
#     except Exception as e:
#         return None, str(e)

# def main():
#     print("=" * 60)
#     print("  Bulk Workspace Search CLI (Aquila)")
#     print("=" * 60)
#     print(f"Reading search strings from: {INPUT_FILE}")
    
#     unique_strings = []
#     try:
#         with open(INPUT_FILE, "r") as f:
#             reader = csv.reader(f)
#             header = next(reader, [])
#             col_idx = 0
#             for i, col in enumerate(header):
#                 if col.strip().lower() in ["search string", "platform customer id", "customer id", "id", "email", "company", "name"]:
#                     col_idx = i
#                     break
#             for row in reader:
#                 if len(row) > col_idx and row[col_idx].strip():
#                     val = row[col_idx].strip()
#                     if val not in unique_strings:
#                         unique_strings.append(val)
#     except Exception as e:
#         print(f"Error reading {INPUT_FILE}: {e}")
#         return

#     print(f"Found {len(unique_strings)} unique search strings.")
    
#     bearer = input("\nPaste your Bearer Token (just the token string, without 'Bearer '): ").strip()
#     if not bearer:
#         print("Token is required!")
#         return

#     cookie = input("Paste your Cookie string (press Enter to skip): ").strip()
    
#     base_url = "https://aquila-user-api.common.cloud.hpe.com"
#     endpoint = f"{base_url}/support-assistant/v1alpha1/customers"
    
#     headers = {
#         "Authorization": f"Bearer {bearer}",
#         "Accept": "application/json"
#     }
#     if cookie:
#         headers["Cookie"] = cookie

#     print(f"\nSearching {len(unique_strings)} workspaces in parallel...")
#     start = time.time()
    
#     results = []
#     errors = 0
#     not_found = 0
#     found = 0
    
#     with ThreadPoolExecutor(max_workers=20) as executor:
#         futures = {executor.submit(fetch_workspace, s, headers, endpoint): s for s in unique_strings}
        
#         count = 0
#         for fut in futures:
#             count += 1
#             search_str = futures[fut]
#             try:
#                 ws_list, err = fut.result()
#                 if err:
#                     errors += 1
#                     print(f"[{count}/{len(unique_strings)}] ERROR for {search_str}: {err}")
#                 elif not ws_list:
#                     not_found += 1
#                     print(f"[{count}/{len(unique_strings)}] NOT FOUND: {search_str}")
#                 else:
#                     found += len(ws_list)
#                     results.extend(ws_list)
#                     print(f"[{count}/{len(unique_strings)}] FOUND {len(ws_list)} workspaces for: {search_str}")
#             except Exception as e:
#                 errors += 1
#                 print(f"[{count}/{len(unique_strings)}] FATAL ERROR for {search_str}: {e}")

#     print(f"\nDone in {time.time()-start:.1f}s! Found {found} workspaces, {not_found} not found, {errors} errors.")
    
#     if results:
#         fieldnames = list(results[0].keys())
#         with open(OUTPUT_FILE, "w", newline="") as f:
#             writer = csv.DictWriter(f, fieldnames=fieldnames)
#             writer.writeheader()
#             writer.writerows(results)
#         print(f"\n✅ Results saved successfully to {OUTPUT_FILE}")

# if __name__ == "__main__":
#     main()
