from fastapi import APIRouter, HTTPException, Depends
from app.core.client import get_glp_client, GreenLakeClient
from pydantic import BaseModel

router = APIRouter()

class ConfigUpdate(BaseModel):
    client_id: str
    client_secret: str

@router.post("/config")
async def update_config(config: ConfigUpdate):
    GreenLakeClient.reload(config.client_id, config.client_secret)
    return {"status": "Config updated"}


@router.get("/subscriptions")
async def get_subscriptions():
    client = get_glp_client()
    if not client:
        raise HTTPException(status_code=401, detail="Client not configured")
    
    from pycentral.glp.subscriptions import Subscriptions
    from datetime import datetime
    sub_api = Subscriptions()
    try:
        subs = sub_api.get_all_subscriptions(client)
        now = datetime.utcnow()
        
        enriched_subs = []
        for sub in subs:
            # Map fields for app.js
            # Handle potential nested or alternate key names
            sub['start_date'] = sub.get('startsAt') or sub.get('startDate', 'N/A')
            sub['end_date'] = sub.get('expiresAt') or sub.get('endDate', 'N/A')
            
            # Calculated Status
            expires_at = sub.get('expiresAt') or sub.get('endDate')
            if expires_at:
                try:
                    dt_str = str(expires_at).replace('Z', '')
                    if 'T' in dt_str:
                        exp_dt = datetime.fromisoformat(dt_str)
                    else:
                        try:
                            # Try with time
                            exp_dt = datetime.strptime(dt_str.split('.')[0], '%Y-%m-%d %H:%M:%S')
                        except ValueError:
                            # Try date only
                            exp_dt = datetime.strptime(dt_str.split(' ')[0], '%Y-%m-%d')
                    
                    if exp_dt < now:
                        sub['calculatedStatus'] = 'Expired'
                    else:
                        sub['calculatedStatus'] = 'Active'
                except:
                    sub['calculatedStatus'] = 'Active'
                
                # If we want 'status' column in JS to show Active/Expired
                # but keep original status in another field if needed.
                # app.js renderTable uses 'status' field.
                sub['original_status'] = sub.get('status')
                sub['status'] = sub['calculatedStatus']
            else:
                sub['calculatedStatus'] = 'Active'
                # If original status exists, use it, otherwise default
                sub['status'] = sub.get('status', 'Active')
            
            enriched_subs.append(sub)
            
        return enriched_subs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users")
async def get_users():
    client = get_glp_client()
    if not client:
        raise HTTPException(status_code=401, detail="Client not configured")
    
    from pycentral.glp.user_management import UserMgmt
    user_api = UserMgmt()
    try:
        # get_users returns dict with 'msg' having 'items'
        resp = user_api.get_users(client)
        if resp['code'] != 200:
             raise HTTPException(status_code=resp['code'], detail=resp['msg'])
        
        users = resp['msg']['items']
        if users:
             print("DEBUG: Sample User Data:", users[0]) # Inspect raw data

        for user in users:
            # Fix Email: check email, emailAddress, or fallback to username
            user['email'] = user.get('email') or user.get('emailAddress') or user.get('username', 'N/A')
            
            # Flatten roles for app.js
            roles = user.get('roles', [])
            if not roles:
                # Try alternate key
                roles = user.get('assignedRoles', [])

            if isinstance(roles, list) and roles:

                role_names = []
                for r in roles:
                    if isinstance(r, dict):
                         role_names.append(r.get('name') or r.get('roleName') or str(r))
                    else:
                         role_names.append(str(r))
                user['role'] = ", ".join(role_names)
            else:
                user['role'] = str(roles) if roles else "No Role"
        
        return users
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))




