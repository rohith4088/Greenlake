
import sys
import os
import requests
import json
import yaml

# Add app/lib to path
sys.path.append(os.path.join(os.getcwd(), 'app'))
sys.path.append(os.path.join(os.getcwd(), 'app', 'lib'))

from pycentral import NewCentralBase

def get_client():
    # Helper to get from env
    c_id = os.environ.get("GLP_CLIENT_ID")
    c_secret = os.environ.get("GLP_CLIENT_SECRET")
    
    if c_id and c_secret:
        print(f"Found Env Vars: {c_id}")
        token_info = {
            "glp": {
                "client_id": c_id,
                "client_secret": c_secret,
                "base_url": "https://global.api.greenlake.hpe.com"
            }
        }
        return NewCentralBase(token_info=token_info)
    else:
        print("Env vars GLP_CLIENT_ID/SECRET not found")
        # Try loading from token.yaml as fallback
        if os.path.exists("token.yaml"):
             print("Loading from token.yaml")
             return NewCentralBase(token_info="token.yaml")
        return None

def main():
    client = get_client()
    if not client:
        print("Failed to initialize client")
        return

    token = client.token_info['glp']['access_token']
    base_url = "https://global.api.greenlake.hpe.com"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # SERIAL TO TEST
    # User provided: CNTBK9W52D
    # ID: 1fa9b880-b8c6-5848-8840-581f066650cd
    serial = "CNTBK9W52D"
    device_id = "1fa9b880-b8c6-5848-8840-581f066650cd"

    tests = [
        {
            "method": "GET",
            "url": f"{base_url}/platform/device_inventory/v1/devices",
            "desc": "Check if Inventory API exists"
        },
        {
            "method": "POST",
            "url": f"{base_url}/platform/device_inventory/v1/devices/archive",
            "json": {"serials": [serial]},
            "desc": "Archive Device (Classic Path on GLP)"
        },
        {
            "method": "DELETE",
            "url": f"{base_url}/devices/v1beta1/devices/{device_id}",
            "desc": "DELETE v1beta1"
        },
        {
            "method": "DELETE",
            "url": f"{base_url}/devices/v1/devices/{device_id}",
            "desc": "DELETE v1"
        },
         {
            "method": "POST",
            "url": f"{base_url}/devices/v1/devices/compute/unclaim",
            "json": {"serials": [serial]},
            "desc": "Unclaim Compute (Hypothetical)"
        }
    ]

    for test in tests:
        print(f"\n--- Testing: {test['desc']} ---")
        print(f"{test['method']} {test['url']}")
        try:
            if test['method'] == 'GET':
                 resp = requests.get(test['url'], headers=headers)
            elif test['method'] == 'POST':
                 resp = requests.post(test['url'], headers=headers, json=test.get('json'))
            elif test['method'] == 'DELETE':
                 resp = requests.delete(test['url'], headers=headers)
            
            print(f"Status: {resp.status_code}")
            try:
                print(f"Response: {resp.json()}")
            except:
                print(f"Response: {resp.text[:200]}...")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
