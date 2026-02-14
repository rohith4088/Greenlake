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
    sub_api = Subscriptions()
    try:
        subs = sub_api.get_all_subscriptions(client)
        return subs
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
        return resp['msg']['items']
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
