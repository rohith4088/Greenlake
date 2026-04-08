from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from app.api.endpoints import router as api_router
from app.api.routers import devices as devices_router
from app.core.client import get_glp_client
import os

app = FastAPI(title="GreenLake Dashboard")

app.mount("/static", StaticFiles(directory="app/static"), name="static")


templates = Jinja2Templates(directory="app/templates")

app.include_router(api_router, prefix="/api")
from app.api.routers.reports import router as reports_router
from app.api.routers.bulk import router as bulk_router
from app.api.routers.auth import router as auth_router
from app.api.routers.ccs_manager import router as ccs_router

app.include_router(devices_router.router, prefix="/api/devices", tags=["devices"])
app.include_router(reports_router, prefix="/api/reports", tags=["reports"])
app.include_router(bulk_router, prefix="/api/bulk", tags=["bulk"])
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(ccs_router, prefix="/api/ccs", tags=["ccs-manager"])
from app.api.routers import sites_groups
app.include_router(sites_groups.router, prefix="/api", tags=["sites-groups"])

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    client = get_glp_client()
    configured = client is not None
    return templates.TemplateResponse("index.html", {"request": request, "configured": configured})

@app.get("/devices", response_class=HTMLResponse)
async def read_devices(request: Request):
    client = get_glp_client()
    configured = client is not None
    devices = []
    if configured:
        from pycentral.glp.devices import Devices
        from pycentral.glp.subscriptions import Subscriptions
        try:
            devices_api = Devices()
            subs_api = Subscriptions()
            devices = devices_api.get_all_devices(client)
            
            # Enrich with subscription details
            try:
                subscriptions = subs_api.get_all_subscriptions(client)
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
                                    # Fallback or simple date
                                    exp_dt = datetime.strptime(dt_str.split(' ')[0], '%Y-%m-%d')
                                
                                if exp_dt < now:
                                    dev_sub['calculatedStatus'] = 'Expired'
                                else:
                                    dev_sub['calculatedStatus'] = 'Active'
                            except Exception as e:
                                print(f"Date parse error for {expires_at}: {e}")
                                dev_sub['calculatedStatus'] = 'Active' # Default to active if can't parse
                        else:
                            dev_sub['calculatedStatus'] = 'Active'
            except Exception as sub_err:
                print(f"Error enriching subscriptions: {sub_err}")
                
        except Exception as e:
            print(f"Error fetching devices: {e}")
    return templates.TemplateResponse("devices.html", {"request": request, "configured": configured, "devices": devices})

@app.get("/reports", response_class=HTMLResponse)
async def read_reports(request: Request):
    client = get_glp_client()
    configured = client is not None
    return templates.TemplateResponse("reports.html", {"request": request, "configured": configured})

@app.get("/bulk", response_class=HTMLResponse)
async def read_bulk(request: Request):
    client = get_glp_client()
    configured = client is not None
    return templates.TemplateResponse("bulk.html", {"request": request, "configured": configured})

@app.get("/sites-groups", response_class=HTMLResponse)
async def read_sites_groups(request: Request):
    client = get_glp_client()
    configured = client is not None
    return templates.TemplateResponse("sites_groups.html", {"request": request, "configured": configured})

@app.get("/ccs-manager", response_class=HTMLResponse)
async def read_ccs_manager(request: Request):
    client = get_glp_client()
    configured = client is not None
    return templates.TemplateResponse("ccs_manager.html", {"request": request, "configured": configured})
