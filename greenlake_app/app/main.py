from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from app.api.endpoints import router as api_router
from app.api.routers import devices as devices_router
from app.core.client import get_glp_client
import os

app = FastAPI(title="GreenLake Dashboard")

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Templates
templates = Jinja2Templates(directory="app/templates")

# Include API router
app.include_router(api_router, prefix="/api")
from app.api.routers.reports import router as reports_router
from app.api.routers.bulk import router as bulk_router
from app.api.routers.auth import router as auth_router

app.include_router(devices_router.router, prefix="/api/devices", tags=["devices"])
app.include_router(reports_router, prefix="/api/reports", tags=["reports"])
app.include_router(bulk_router, prefix="/api/bulk", tags=["bulk"])
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])

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
        try:
            devices_api = Devices()
            devices = devices_api.get_all_devices(client)
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
