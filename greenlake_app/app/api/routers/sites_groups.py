from fastapi import APIRouter, HTTPException, UploadFile, File, Depends, Body
from app.core.client import get_glp_client
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import csv
import io
from pycentral.scopes.site import Site
from pycentral.glp.devices import Devices as GLPDevices
# Aliasing to avoid conflict
from pycentral.classic.configuration import Devices as ClassicDevices

router = APIRouter()

# --- Models ---

class AutoGroupRule(BaseModel):
    attribute: str  # e.g., 'model', 'serial', 'mac'
    operator: str   # e.g., 'equals', 'contains', 'starts_with'
    value: str
    target_group: str

class AutoGroupRequest(BaseModel):
    rules: List[AutoGroupRule]

# --- Endpoints ---

@router.post("/sites/bulk-create")
async def bulk_create_sites(file: UploadFile = File(...)):
    """
    Creates sites in bulk from an uploaded CSV file.
    Expected CSV columns: name, address, city, state, country, zipcode
    """
    client = get_glp_client()
    if not client:
        raise HTTPException(status_code=401, detail="Client not configured")

    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a CSV file.")

    content = await file.read()
    try:
        # Decode bytes to string
        decoded_content = content.decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(decoded_content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading CSV file: {str(e)}")

    # Validate columns
    required_columns = ['name', 'address', 'city', 'state', 'country', 'zipcode']
    if not all(col in csv_reader.fieldnames for col in required_columns):
        raise HTTPException(status_code=400, detail=f"Missing required columns. Expected: {', '.join(required_columns)}")

    success_count = 0
    failure_count = 0
    errors = []

    for row in csv_reader:
        try:
            # Prepare site attributes
            site_attrs = {
                'name': row['name'],
                'address': row['address'],
                'city': row['city'],
                'state': row['state'],
                'country': row['country'],
                'zipcode': row['zipcode'],
                'timezone': row.get('timezone', 'UTC') # Default to UTC if not provided
            }
            
            # Create Site object and call create()
            site = Site(site_attributes=site_attrs, central_conn=client)
            if site.create():
                success_count += 1
            else:
                failure_count += 1
                errors.append(f"Failed to create site: {row['name']}")
        except Exception as e:
            failure_count += 1
            errors.append(f"Error creating site {row.get('name', 'Unknown')}: {str(e)}")

    return {
        "message": "Bulk site creation completed",
        "total_processed": success_count + failure_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "errors": errors
    }

@router.post("/groups/auto-group")
async def auto_group_devices(request: AutoGroupRequest):
    """
    Automatically moves devices to groups based on provided rules.
    """
    client = get_glp_client()
    if not client:
        raise HTTPException(status_code=401, detail="Client not configured")

    glp_devices_api = GLPDevices()
    classic_devices_api = ClassicDevices()

    try:
        # 1. Fetch all devices
        all_devices = glp_devices_api.get_all_devices(client)
        if not all_devices:
             return {"message": "No devices found to process", "moved_count": 0}

        # 2. Process rules and identify moves
        moves = {} # target_group -> list of serials
        
        for device in all_devices:
            serial = device.get('serial') # Check field name from previous output (serialNumber in GLP?)
            # Re-checking GLP device structure from previous logs/code...
            # endpoint in `devices.py` handled `get_all_devices`.
            # `glp/devices.py` -> `get_all_devices` returns list.
            # `scopes/device.py` maps `serialNumber` -> `serial`.
            # But here we are using `glp_devices_api.get_all_devices` which returns raw dict from API (or processed?)
            # `glp/devices.py` returns `device_list`. Let's assume keys are from API response.
            # Common keys: `serial`, `serial_number`, `serialNumber`. `model`, `aruba_part_no`...
            # Let's handle generic access or check `glp/devices.py` output structure more carefully?
            # `glp/devices.py` `get_all_devices` calls `get_device`.
            # `get_device` returns raw JSON. keys usually cameCamelCase?
            # Let's try to be robust.
            
            device_serial = device.get('serial') or device.get('serial_number') or device.get('serialNumber')
            if not device_serial:
                continue

            # Determine target group based on rules (first match wins)
            target = None
            for rule in request.rules:
                attr_val = str(device.get(rule.attribute, "")).lower()
                rule_val = str(rule.value).lower()
                
                match = False
                if rule.operator == 'equals':
                    match = attr_val == rule_val
                elif rule.operator == 'contains':
                    match = rule_val in attr_val
                elif rule.operator == 'starts_with':
                    match = attr_val.startswith(rule_val)
                elif rule.operator == 'ends_with':
                    match = attr_val.endswith(rule_val)
                
                if match:
                    target = rule.target_group
                    break # First rule match wins
            
            if target:
                if target not in moves:
                    moves[target] = []
                moves[target].append(device_serial)

        # 3. Execute moves
        results = []
        total_moved = 0
        
        for group, serials in moves.items():
            # Batch move
            # Note: `move_devices` limit check? `pycentral` usually handles some, but let's see.
            # `classic.configuration.Devices.move_devices` takes list of serials.
            try:
                resp = classic_devices_api.move_devices(client, group_name=group, device_serials=serials)
                results.append({
                    "group": group,
                    "count": len(serials),
                    "status": "Success" if resp.get('code') == 200 else "Failed",
                    "details": resp
                })
                if resp.get('code') == 200:
                    total_moved += len(serials)
            except Exception as e:
                results.append({
                    "group": group,
                    "count": len(serials),
                    "status": "Error",
                    "details": str(e)
                })

        return {
            "message": "Auto-grouping processing complete",
            "total_devices_checked": len(all_devices),
            "total_moved": total_moved,
            "results": results
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
