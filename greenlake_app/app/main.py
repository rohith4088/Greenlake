from fastapi import FastAPI, Request, Form, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from app.api.endpoints import router as api_router
from app.api.routers import devices as devices_router
from app.core.client import get_glp_client
from app.auth.users import authenticate_user
from app.auth.session import read_session, set_session, clear_session
from app.auth.rbac import get_current_user, require_role
from app.audit.logger import get_recent_logs, get_log_stats
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

# ── Auth Routes ────────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    # If already logged in, redirect to home
    user = read_session(request)
    if user:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    user = authenticate_user(username, password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid username or password."},
            status_code=401,
        )
    response = RedirectResponse(url="/", status_code=302)
    set_session(response, user)
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    clear_session(response)
    return response


# ── Helper: session-aware template context ─────────────────────────────────────

def _ctx(request: Request, **kwargs):
    """Build a template context that always includes the current user."""
    user = read_session(request)
    return {"request": request, "current_user": user, **kwargs}


def _require_login(request: Request):
    """Return user or redirect to login for page routes."""
    user = read_session(request)
    if not user:
        return None
    return user


# ── Page Routes ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    user = _require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    client = get_glp_client()
    configured = client is not None
    return templates.TemplateResponse("index.html", _ctx(request, configured=configured))


@app.get("/devices", response_class=HTMLResponse)
async def read_devices(request: Request):
    user = _require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
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
            try:
                subscriptions = subs_api.get_all_subscriptions(client)
                sub_map = {s.get('key'): s for s in subscriptions if s.get('key')}
                from datetime import datetime
                now = datetime.utcnow()
                for device in devices:
                    dev_sub_data = device.get('subscription')
                    if isinstance(dev_sub_data, list) and len(dev_sub_data) > 0:
                        dev_sub = dev_sub_data[0]
                        device['subscription'] = dev_sub
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
                        dev_sub['skuDescription'] = full_sub.get('skuDescription', full_sub.get('description', 'N/A'))
                        dev_sub['subscriptionStatus'] = full_sub.get('subscriptionStatus')
                        dev_sub['availableQuantity'] = full_sub.get('availableQuantity')
                        dev_sub['quantity'] = full_sub.get('quantity')
                        expires_at = full_sub.get('expiresAt')
                        if expires_at:
                            try:
                                dt_str = expires_at.replace('Z', '')
                                if 'T' in dt_str:
                                    exp_dt = datetime.fromisoformat(dt_str)
                                else:
                                    exp_dt = datetime.strptime(dt_str.split(' ')[0], '%Y-%m-%d')
                                dev_sub['calculatedStatus'] = 'Expired' if exp_dt < now else 'Active'
                            except Exception:
                                dev_sub['calculatedStatus'] = 'Active'
                        else:
                            dev_sub['calculatedStatus'] = 'Active'
            except Exception as sub_err:
                print(f"Error enriching subscriptions: {sub_err}")
        except Exception as e:
            print(f"Error fetching devices: {e}")
    return templates.TemplateResponse("devices.html", _ctx(request, configured=configured, devices=devices))


@app.get("/reports", response_class=HTMLResponse)
async def read_reports(request: Request):
    user = _require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    client = get_glp_client()
    return templates.TemplateResponse("reports.html", _ctx(request, configured=client is not None))


@app.get("/bulk", response_class=HTMLResponse)
async def read_bulk(request: Request):
    user = _require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    client = get_glp_client()
    return templates.TemplateResponse("bulk.html", _ctx(request, configured=client is not None))


@app.get("/sites-groups", response_class=HTMLResponse)
async def read_sites_groups(request: Request):
    user = _require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    client = get_glp_client()
    return templates.TemplateResponse("sites_groups.html", _ctx(request, configured=client is not None))


# ── CCS Manager Routes (login required) ───────────────────────────────────────

@app.get("/ccs-manager")
async def redirect_ccs_manager(request: Request):
    user = _require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return RedirectResponse(url="/ccs-manager/devices")


@app.get("/ccs-manager/devices", response_class=HTMLResponse)
async def read_ccs_manager_devices(request: Request):
    user = _require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("ccs_devices.html", _ctx(request))


@app.get("/ccs-manager/subscriptions", response_class=HTMLResponse)
async def read_ccs_manager_subscriptions(request: Request):
    user = _require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("ccs_subscriptions.html", _ctx(request))


@app.get("/ccs-manager/users", response_class=HTMLResponse)
async def read_ccs_manager_users(request: Request):
    user = _require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("ccs_users.html", _ctx(request))


@app.get("/ccs-manager/audit-logs", response_class=HTMLResponse)
async def read_audit_logs(request: Request):
    user = _require_login(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    from app.auth.users import role_gte
    if not role_gte(user.get("role", "viewer"), "admin"):
        return HTMLResponse("<h2>403 — Admin access required.</h2>", status_code=403)
    logs  = get_recent_logs(limit=500)
    stats = get_log_stats()
    return templates.TemplateResponse("admin_logs.html", _ctx(request, logs=logs, stats=stats))
