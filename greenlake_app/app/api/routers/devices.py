# from fastapi import APIRouter, HTTPException, Depends
# from app.core.client import get_glp_client
# from pydantic import BaseModel
# from typing import List, Optional
# import requests

# router = APIRouter()

# class DeviceAction(BaseModel):
#     devices: List[str] # List of device IDs or Serials
#     application_id: Optional[str] = None
#     region: Optional[str] = None
#     subscription_key: Optional[str] = None

# @router.get("/")
# async def get_devices():
#     client = get_glp_client()
#     if not client:
#         raise HTTPException(status_code=401, detail="Client not configured")
    
#     from pycentral.glp.devices import Devices
#     from pycentral.glp.subscriptions import Subscriptions
    
#     devices_api = Devices()
#     subs_api = Subscriptions()
    
#     try:
#         devices = devices_api.get_all_devices(client)
        
#         # Enrich with subscription details
#         try:
#             subscriptions = subs_api.get_all_subscriptions(client)
#             # Create a map of subscription_key -> subscription_details
#             sub_map = {s.get('key'): s for s in subscriptions if s.get('key')}
            
#             for device in devices:
#                 # Device might have 'subscription' object or 'subscriptionId' etc.
#                 # Based on previous audit (devices.py), we saw response structure but not full device content.
#                 # Usually devices have a 'subscription' key which might be null or contain partial info.
#                 # Let's assume device['subscription'] has a 'key' or we match by device serial/id if subs have that info?
#                 # Actually, subscriptions are usually assigned to devices. 
#                 # Let's check if device has subscription info we can match.
#                 # If device has 'subscription_key' or similar.
#                 # Checking `devices.html` loop: `{% if device.subscription %}`.
#                 # The device object from GLP likely has a subscription object. 
#                 # Let's iterate and try to find matching key.
                
#                 dev_sub = device.get('subscription')
#                 if dev_sub and isinstance(dev_sub, dict):
#                     # Check if key is in dev_sub or if we need to look it up
#                     sub_key = dev_sub.get('key')
#                     if sub_key and sub_key in sub_map:
#                         full_sub = sub_map[sub_key]
#                         # Merge details we want
#                         dev_sub['startsAt'] = full_sub.get('startsAt')
#                         dev_sub['expiresAt'] = full_sub.get('expiresAt')
#                         dev_sub['status'] = full_sub.get('status')
#                         dev_sub['tier'] = full_sub.get('tier')
#         except Exception as e:
#             print(f"Error fetching subscriptions for enrichment: {e}")
#             # Continue without enrichment if it fails
#             pass
            
#         return devices
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# @router.post("/assign")
# async def assign_devices(action: DeviceAction):
#     client = get_glp_client()
#     if not client:
#         raise HTTPException(status_code=401, detail="Client not configured")
    
#     if not action.application_id or not action.region:
#         raise HTTPException(status_code=400, detail="Application ID and Region are required")

#     from pycentral.glp.devices import Devices
#     devices_api = Devices()
#     try:
#         # Check if devices are serials or IDs. Assuming serials for now based on common usage, 
#         # or we could try to detect. `assign_devices` takes `serial=True` if serials.
#         # Let's assume the frontend sends what we need. For now, default to serials as they are easier for users to identify.
#         # But if the list from get_devices has IDs, we should use IDs.
#         # get_all_devices returns items with 'id'. Let's assume IDs.
        
#         resp = devices_api.assign_devices(
#             client, 
#             devices=action.devices, 
#             application=action.application_id, 
#             region=action.region,
#             serial=False 
#         )
#         return resp
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# @router.post("/unassign")
# async def unassign_devices(action: DeviceAction):
#     client = get_glp_client()
#     if not client:
#         raise HTTPException(status_code=401, detail="Client not configured")
    
#     from pycentral.glp.devices import Devices
#     devices_api = Devices()
#     try:
#         resp = devices_api.unassign_devices(
#             client, 
#             devices=action.devices, 
#             serial=False
#         )
#         return resp
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# @router.post("/subscriptions/add")
# async def add_subscription(action: DeviceAction):
#     client = get_glp_client()
#     if not client:
#         raise HTTPException(status_code=401, detail="Client not configured")
    
#     if not action.subscription_key:
#          raise HTTPException(status_code=400, detail="Subscription Key/ID is required")

#     try:
#         token = client.token_info['glp']['access_token']
#         # Hardcoded endpoint for consistency with other working parts
#         url = "https://global.api.greenlake.hpe.com/devices/v1beta1/devices"
        
#         # Handle multiple devices
#         # requests.patch handles list of values for a key in params as multiple query parameters
#         params = {"id": action.devices}
        
#         headers = {
#             "Authorization": f"Bearer {token}",
#             "Content-Type": "application/merge-patch+json"
#         }
        
#         body = {"subscription": [{"id": action.subscription_key}]}
        
#         # Helper to invoke request
#         import requests
#         resp = requests.patch(url, headers=headers, params=params, json=body, timeout=30)
        
#         # Handle response
#         if resp.status_code in [200, 202]:
#              # Return JSON response expecting dict
#              try:
#                  return resp.json()
#              except:
#                  return {"code": resp.status_code, "msg": "Success"}
#         else:
#              # Try to parse error
#              try:
#                  err_msg = resp.json()
#              except:
#                  err_msg = resp.text
#              raise HTTPException(status_code=resp.status_code, detail=f"API Error: {err_msg}")

#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# @router.post("/subscriptions/remove")
# async def remove_subscription(action: DeviceAction):
#     client = get_glp_client()
#     if not client:
#         raise HTTPException(status_code=401, detail="Client not configured")
    
#     from pycentral.glp.devices import Devices
#     devices_api = Devices()
#     try:
#         resp = devices_api.remove_sub(
#             client, 
#             devices=action.devices, 
#             serial=False
#         )
#         return resp
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))

# @router.get("/apps")
# async def get_apps():
#     client = get_glp_client()
#     if not client:
#         raise HTTPException(status_code=401, detail="Client not configured")
        
#     from pycentral.glp.service_manager import ServiceManager
#     sm_api = ServiceManager()
#     try:
#         # Get all available service managers (applications)
#         # get_service_managers
#         resp = sm_api.get_service_managers(client)
#         if resp['code'] != 200:
#              raise HTTPException(status_code=resp['code'], detail=resp['msg'])
#         return resp['msg']['items']
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))


from fastapi import APIRouter, HTTPException, Depends
from app.core.client import get_glp_client
from pydantic import BaseModel
from typing import List, Optional
import requests

router = APIRouter()

class DeviceAction(BaseModel):
    devices: List[str] # List of device IDs or Serials
    application_id: Optional[str] = None
    region: Optional[str] = None
    subscription_key: Optional[str] = None

@router.get("/")
async def get_devices():
    client = get_glp_client()
    if not client:
        raise HTTPException(status_code=401, detail="Client not configured")
    
    from pycentral.glp.devices import Devices
    from pycentral.glp.subscriptions import Subscriptions
    
    devices_api = Devices()
    subs_api = Subscriptions()
    
    try:
        devices = devices_api.get_all_devices(client)
        
        # Enrich with subscription details
        try:
            subscriptions = subs_api.get_all_subscriptions(client)
            # Create a map of subscription_key -> subscription_details
            sub_map = {s.get('key'): s for s in subscriptions if s.get('key')}
            
            from datetime import datetime
            now = datetime.utcnow()
            
            for device in devices:
                dev_sub_data = device.get('subscription')
                # Handle both list and dict formats
                if isinstance(dev_sub_data, list) and len(dev_sub_data) > 0:
                    dev_sub = dev_sub_data[0]
                    device['subscription'] = dev_sub # Ensure it's a dict for templates
                elif isinstance(dev_sub_data, dict):
                    dev_sub = dev_sub_data
                else:
                    continue

                sub_key = dev_sub.get('key')
                if sub_key and sub_key in sub_map:
                    full_sub = sub_map[sub_key]
                    # Merge details we want
                    dev_sub['startsAt'] = full_sub.get('startsAt')
                    dev_sub['expiresAt'] = full_sub.get('expiresAt')
                    dev_sub['status'] = full_sub.get('status')
                    dev_sub['tier'] = full_sub.get('tier')
                    # Additional fields
                    dev_sub['skuDescription'] = full_sub.get('skuDescription', full_sub.get('description', 'N/A'))
                    dev_sub['subscriptionStatus'] = full_sub.get('subscriptionStatus')
                    dev_sub['availableQuantity'] = full_sub.get('availableQuantity')
                    dev_sub['quantity'] = full_sub.get('quantity')
                    
                    # Calculated Status logic
                    expires_at = full_sub.get('expiresAt')
                    if expires_at:
                        try:
                            # Handle common ISO format like 2025-01-01T00:00:00Z
                            dt_str = expires_at.replace('Z', '')
                            if 'T' in dt_str:
                                exp_dt = datetime.fromisoformat(dt_str)
                            else:
                                exp_dt = datetime.strptime(dt_str.split(' ')[0], '%Y-%m-%d')
                            
                            if exp_dt < now:
                                dev_sub['calculatedStatus'] = 'Expired'
                            else:
                                dev_sub['calculatedStatus'] = 'Active'
                        except Exception as e:
                            print(f"Date parse error for {expires_at}: {e}")
                            dev_sub['calculatedStatus'] = 'Active'
                    else:
                        dev_sub['calculatedStatus'] = 'Active'
                    
                    # Flatten for simple JS tables
                    device['sub_start'] = dev_sub.get('startsAt', 'N/A')
                    device['sub_end'] = dev_sub.get('expiresAt', 'N/A')
                    device['sub_status'] = dev_sub.get('calculatedStatus', 'Active')
                    device['sub_tier'] = dev_sub.get('tier', 'N/A')
                else:
                    # Case where subscription key doesn't match sub_map
                    device['sub_status'] = 'Unknown'
            else:
                # No subscription
                device['sub_status'] = 'No Sub'
                device['sub_start'] = '-'
                device['sub_end'] = '-'
                device['sub_tier'] = '-'
        except Exception as e:
            print(f"Error fetching subscriptions for enrichment: {e}")
            # Continue without enrichment if it fails
            pass
            
        return devices
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/assign")
async def assign_devices(action: DeviceAction):
    client = get_glp_client()
    if not client:
        raise HTTPException(status_code=401, detail="Client not configured")
    
    if not action.application_id or not action.region:
        raise HTTPException(status_code=400, detail="Application ID and Region are required")

    from pycentral.glp.devices import Devices
    devices_api = Devices()
    try:
        # Check if devices are serials or IDs. Assuming serials for now based on common usage, 
        # or we could try to detect. `assign_devices` takes `serial=True` if serials.
        # Let's assume the frontend sends what we need. For now, default to serials as they are easier for users to identify.
        # But if the list from get_devices has IDs, we should use IDs.
        # get_all_devices returns items with 'id'. Let's assume IDs.
        
        resp = devices_api.assign_devices(
            client, 
            devices=action.devices, 
            application=action.application_id, 
            region=action.region,
            serial=False 
        )
        return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/unassign")
async def unassign_devices(action: DeviceAction):
    client = get_glp_client()
    if not client:
        raise HTTPException(status_code=401, detail="Client not configured")
    
    from pycentral.glp.devices import Devices
    devices_api = Devices()
    try:
        resp = devices_api.unassign_devices(
            client, 
            devices=action.devices, 
            serial=False
        )
        return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/subscriptions/add")
async def add_subscription(action: DeviceAction):
    client = get_glp_client()
    if not client:
        raise HTTPException(status_code=401, detail="Client not configured")
    
    if not action.subscription_key:
         raise HTTPException(status_code=400, detail="Subscription Key/ID is required")

    from pycentral.glp.subscriptions import Subscriptions
    subs_api = Subscriptions()
    
    # Try to resolve key to ID
    # The error suggests the API expects an ID (e.g. valid UUID or specific format) 
    # but got a Key (e.g. EE257F4F3355844189).
    # We should try to look up the ID associated with this Key.
    
    sub_id = action.subscription_key
    try:
        # Check if it looks like a key (alphanumeric, maybe not UUID)
        # Or just always try to find it.
        found, result = subs_api.get_sub_id(client, action.subscription_key)
        if found:
            sub_id = result
            print(f"Resolved Subscription Key {action.subscription_key} to ID {sub_id}")
        else:
             print(f"Could not resolve key {action.subscription_key} to ID: {result}. Trying as is.")
             # Fallback to hardcoded lookup if API fails?
             # Or maybe the key IS the ID?
    except Exception as e:
        print(f"Error resolving subscription key: {e}")
        import traceback
        traceback.print_exc()

    print(f"Final Subscription ID to be used: {sub_id}")

    try:
        token = client.token_info['glp']['access_token']
        # Hardcoded endpoint for consistency with other working parts
        url = "https://global.api.greenlake.hpe.com/devices/v1beta1/devices"
        
        # Handle multiple devices - use list of tuples for multiple id params
        # requests.patch handles list of tuples as multiple query parameters
        params = [("id", device_id) for device_id in action.devices]
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/merge-patch+json"
        }
        
        body = {"subscription": [{"id": sub_id}]}
        
        # Helper to invoke request
        import requests
        resp = requests.patch(url, headers=headers, params=params, json=body, timeout=30)
        
        # Handle response
        if resp.status_code in [200, 202]:
             # Return JSON response expecting dict
             try:
                 return resp.json()
             except:
                 return {"code": resp.status_code, "msg": "Success"}
        else:
             # Try to parse error
             try:
                 err_msg = resp.json()
             except:
                 err_msg = resp.text
             raise HTTPException(status_code=resp.status_code, detail=f"API Error: {err_msg}")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/subscriptions/remove")
async def remove_subscription(action: DeviceAction):
    client = get_glp_client()
    if not client:
        raise HTTPException(status_code=401, detail="Client not configured")
    
    from pycentral.glp.devices import Devices
    devices_api = Devices()
    try:
        resp = devices_api.remove_sub(
            client, 
            devices=action.devices, 
            serial=False
        )
        return resp
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/apps")
async def get_apps():
    client = get_glp_client()
    if not client:
        raise HTTPException(status_code=401, detail="Client not configured")
        
    from pycentral.glp.service_manager import ServiceManager
    sm_api = ServiceManager()
    try:
        # Get all available service managers (applications)
        # get_service_managers
        resp = sm_api.get_service_managers(client)
        if resp['code'] != 200:
             raise HTTPException(status_code=resp['code'], detail=resp['msg'])
        return resp['msg']['items']
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))