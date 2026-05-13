
from fastapi import APIRouter, HTTPException, Depends
from app.core.client import get_glp_client
from pydantic import BaseModel
from typing import List, Optional, Any, Dict
import requests
import io
import base64
import json

router = APIRouter()

# ── Analytics Models ──────────────────────────────────────────────────────────

class AnalyticsRequest(BaseModel):
    devices: List[Dict[str, Any]]

# ── Analytics Helper ──────────────────────────────────────────────────────────

def _fig_to_b64(fig) -> str:
    """Convert a matplotlib figure to a base64 PNG string."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=130,
                facecolor=fig.get_facecolor())
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


@router.post("/analytics")
async def device_analytics(payload: AnalyticsRequest):
    """
    Accept a list of device objects (as returned by /api/devices/),
    compute analytics with pandas/matplotlib/seaborn and return:
      - 4 chart images (base64 PNG)
      - a structured insights summary
    """
    try:
        import pandas as pd
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import seaborn as sns
        import numpy as np
        from datetime import datetime

        devices = payload.devices
        if not devices:
            raise HTTPException(status_code=400, detail="No device data provided")

        # ── Build DataFrame ──────────────────────────────────────────────────
        rows = []
        for d in devices:
            sub = d.get("subscription") or {}
            if isinstance(sub, list):
                sub = sub[0] if sub else {}

            expires_raw = sub.get("expiresAt") or sub.get("sub_end") or d.get("sub_end")
            starts_raw  = sub.get("startsAt")  or sub.get("sub_start") or d.get("sub_start")

            expires_dt = None
            if expires_raw and expires_raw not in ("-", "N/A", ""):
                try:
                    expires_dt = pd.to_datetime(str(expires_raw).replace("Z", ""), utc=False)
                except Exception:
                    pass

            starts_dt = None
            if starts_raw and starts_raw not in ("-", "N/A", ""):
                try:
                    starts_dt = pd.to_datetime(str(starts_raw).replace("Z", ""), utc=False)
                except Exception:
                    pass

            cal_status = (sub.get("calculatedStatus") or d.get("sub_status") or "Unknown")
            if not cal_status or cal_status in ("-", ""):
                cal_status = "No Sub"

            rows.append({
                "serial":     d.get("serialNumber", "N/A"),
                "model":      d.get("model", "Unknown"),
                "status":     d.get("status", "Unknown"),
                "sub_status": cal_status,
                "sub_tier":   sub.get("tier") or d.get("sub_tier") or "N/A",
                "expires_dt": expires_dt,
                "starts_dt":  starts_dt,
                "app":        (d.get("application") or {}).get("name", "Unassigned") if isinstance(d.get("application"), dict) else ("Assigned" if d.get("application") else "Unassigned"),
            })

        df = pd.DataFrame(rows)
        now = datetime.utcnow()
        total = len(df)

        # ── Shared Dark Theme ────────────────────────────────────────────────
        BG     = "#0f1117"
        CARD   = "#1a1d2e"
        ACCENT = "#4cd137"
        PALETTE = ["#4cd137", "#e74c3c", "#f1c40f", "#3498db", "#9b59b6",
                   "#e67e22", "#1abc9c", "#e91e63"]

        plt.rcParams.update({
            "figure.facecolor":  BG,
            "axes.facecolor":    CARD,
            "axes.edgecolor":    "#2a2d3e",
            "axes.labelcolor":   "#c0c4d8",
            "xtick.color":       "#7f8598",
            "ytick.color":       "#7f8598",
            "text.color":        "#e0e3f0",
            "grid.color":        "#2a2d3e",
            "grid.linestyle":    "--",
            "grid.alpha":        0.5,
            "font.family":       "DejaVu Sans",
            "font.size":         9,
        })

        charts = {}

        # ── Chart 1: Subscription Status Donut ──────────────────────────────
        status_counts = df["sub_status"].value_counts()
        colors_map = {"Active": "#4cd137", "Expired": "#e74c3c",
                      "No Sub": "#f1c40f", "Unknown": "#7f8598"}
        colors1 = [colors_map.get(s, "#3498db") for s in status_counts.index]

        fig1, ax1 = plt.subplots(figsize=(5, 4.5), facecolor=BG)
        wedges, texts, autotexts = ax1.pie(
            status_counts.values,
            labels=None,
            autopct="%1.1f%%",
            colors=colors1,
            startangle=140,
            pctdistance=0.75,
            wedgeprops={"linewidth": 2, "edgecolor": BG, "width": 0.55},
        )
        for at in autotexts:
            at.set_fontsize(8)
            at.set_color("#e0e3f0")
        legend1 = ax1.legend(
            handles=[mpatches.Patch(color=c, label=l)
                     for c, l in zip(colors1, status_counts.index)],
            loc="lower center", bbox_to_anchor=(0.5, -0.12),
            ncol=len(status_counts), frameon=False,
            prop={"size": 8}
        )
        for text in legend1.get_texts():
            text.set_color("#c0c4d8")
        ax1.set_title("Subscription Status", color="#e0e3f0", fontsize=11,
                      fontweight="bold", pad=10)
        ax1.text(0, 0, str(total), ha="center", va="center",
                 fontsize=20, fontweight="bold", color="#e0e3f0")
        ax1.text(0, -0.18, "devices", ha="center", va="center",
                 fontsize=8, color="#7f8598")
        fig1.tight_layout()
        charts["subscription_status"] = _fig_to_b64(fig1)
        plt.close(fig1)

        # ── Chart 2: Device Model Distribution ──────────────────────────────
        model_counts = df["model"].value_counts().head(10)
        fig2, ax2 = plt.subplots(figsize=(6, 4.5), facecolor=BG)
        bar_colors = [PALETTE[i % len(PALETTE)] for i in range(len(model_counts))]
        bars = ax2.barh(model_counts.index[::-1], model_counts.values[::-1],
                        color=bar_colors[::-1], height=0.6)
        for bar, val in zip(bars, model_counts.values[::-1]):
            ax2.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height() / 2,
                     str(val), va="center", ha="left", fontsize=8,
                     color="#c0c4d8")
        ax2.set_xlabel("Count", color="#c0c4d8")
        ax2.set_title("Device Models (Top 10)", color="#e0e3f0",
                      fontsize=11, fontweight="bold")
        ax2.grid(axis="x")
        ax2.tick_params(axis="y", labelsize=8)
        fig2.tight_layout()
        charts["model_distribution"] = _fig_to_b64(fig2)
        plt.close(fig2)

        # ── Chart 3: Subscription Tier Breakdown ─────────────────────────────
        tier_counts = df["sub_tier"].value_counts()
        valid_tiers = tier_counts[tier_counts.index != "N/A"]
        if valid_tiers.empty:
            valid_tiers = tier_counts  # show all if all N/A

        fig3, ax3 = plt.subplots(figsize=(5, 4.5), facecolor=BG)
        tier_colors = [PALETTE[i % len(PALETTE)] for i in range(len(valid_tiers))]
        wedges3, texts3, auto3 = ax3.pie(
            valid_tiers.values,
            labels=None,
            autopct="%1.1f%%",
            colors=tier_colors,
            startangle=90,
            pctdistance=0.78,
            wedgeprops={"linewidth": 2, "edgecolor": BG, "width": 0.5},
        )
        for at in auto3:
            at.set_fontsize(8)
            at.set_color("#e0e3f0")
        legend3 = ax3.legend(
            handles=[mpatches.Patch(color=c, label=l)
                     for c, l in zip(tier_colors, valid_tiers.index)],
            loc="lower center", bbox_to_anchor=(0.5, -0.14),
            ncol=min(3, len(valid_tiers)), frameon=False,
            prop={"size": 8}
        )
        for text in legend3.get_texts():
            text.set_color("#c0c4d8")
        ax3.set_title("Subscription Tiers", color="#e0e3f0",
                      fontsize=11, fontweight="bold", pad=10)
        fig3.tight_layout()
        charts["tier_breakdown"] = _fig_to_b64(fig3)
        plt.close(fig3)

        # ── Chart 4: Expiry Timeline ─────────────────────────────────────────
        exp_df = df.dropna(subset=["expires_dt"]).copy()
        fig4, ax4 = plt.subplots(figsize=(6, 4.5), facecolor=BG)

        if not exp_df.empty:
            exp_df["month"] = exp_df["expires_dt"].dt.to_period("M")
            monthly = exp_df.groupby("month").size().sort_index()
            x_labels = [str(p) for p in monthly.index]
            x_pos = np.arange(len(x_labels))

            future_mask = [pd.Period(p) >= pd.Period(now.strftime("%Y-%m"), freq="M")
                           for p in monthly.index]
            bar_c = [ACCENT if f else "#e74c3c" for f in future_mask]
            ax4.bar(x_pos, monthly.values, color=bar_c, width=0.7)
            ax4.set_xticks(x_pos)
            ax4.set_xticklabels(x_labels, rotation=45, ha="right", fontsize=7)
            ax4.set_ylabel("Devices", color="#c0c4d8")
            ax4.grid(axis="y")
            # legend
            past_patch   = mpatches.Patch(color="#e74c3c", label="Expired")
            future_patch = mpatches.Patch(color=ACCENT,    label="Active/Future")
            legend4 = ax4.legend(handles=[past_patch, future_patch], frameon=False,
                       prop={"size": 8})
            for text in legend4.get_texts():
                text.set_color("#c0c4d8")
        else:
            ax4.text(0.5, 0.5, "No subscription\nexpiry data available",
                     ha="center", va="center", transform=ax4.transAxes,
                     fontsize=12, color="#7f8598")

        ax4.set_title("Subscription Expiry Timeline", color="#e0e3f0",
                      fontsize=11, fontweight="bold")
        fig4.tight_layout()
        charts["expiry_timeline"] = _fig_to_b64(fig4)
        plt.close(fig4)

        # ── Compute AI Insights ──────────────────────────────────────────────
        active_count  = (df["sub_status"] == "Active").sum()
        expired_count = (df["sub_status"] == "Expired").sum()
        nosub_count   = (df["sub_status"] == "No Sub").sum()
        unassigned    = (df["app"] == "Unassigned").sum()
        top_model     = df["model"].mode()[0] if not df["model"].mode().empty else "N/A"

        expiring_soon = 0
        if not exp_df.empty:
            cutoff = pd.Timestamp(now) + pd.Timedelta(days=30)
            expiring_soon = int(
                ((exp_df["expires_dt"] >= pd.Timestamp(now)) &
                 (exp_df["expires_dt"] <= cutoff)).sum()
            )

        health_score = round((active_count / total) * 100, 1) if total else 0

        insights = {
            "total_devices":   total,
            "active_subs":     int(active_count),
            "expired_subs":    int(expired_count),
            "no_sub":          int(nosub_count),
            "unassigned":      int(unassigned),
            "expiring_30d":    expiring_soon,
            "top_model":       top_model,
            "health_score":    health_score,
            "top_tier":        (valid_tiers.index[0]
                                if not valid_tiers.empty else "N/A"),
            "unique_models":   int(df["model"].nunique()),
        }

        return {"charts": charts, "insights": insights}

    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Analytics libraries not installed: {e}. "
                   f"Run: pip install pandas matplotlib seaborn numpy"
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Analytics error: {e}")


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
                    # No subscription, set defaults
                    device['sub_status'] = 'No Sub'
                    device['sub_start'] = '-'
                    device['sub_end'] = '-'
                    device['sub_tier'] = '-'
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
                            # Handle different date formats
                            # Common ISO format like 2025-01-01T00:00:00Z or 2025-01-01 00:00:00
                            dt_str = str(expires_at).replace('Z', '')
                            if 'T' in dt_str:
                                exp_dt = datetime.fromisoformat(dt_str)
                            else:
                                # Fallback or simple date
                                try:
                                    exp_dt = datetime.strptime(dt_str.split('.')[0], '%Y-%m-%d %H:%M:%S')
                                except ValueError:
                                     exp_dt = datetime.strptime(dt_str.split(' ')[0], '%Y-%m-%d')
                            
                            if exp_dt < now:
                                dev_sub['calculatedStatus'] = 'Expired'
                            else:
                                dev_sub['calculatedStatus'] = 'Active'
                        except Exception as e:
                            print(f"Date parse error for {expires_at}: {e}")
                            dev_sub['calculatedStatus'] = 'Active' # Default if parsing fails
                    else:
                         # No expiration date might mean permanent or active
                        dev_sub['calculatedStatus'] = 'Active'
                    
                    # Flatten for simple JS tables
                    device['sub_start'] = dev_sub.get('startsAt', 'N/A')
                    device['sub_end'] = dev_sub.get('expiresAt', 'N/A')
                    device['sub_status'] = dev_sub.get('calculatedStatus', 'Active')
                    device['sub_tier'] = dev_sub.get('tier', 'N/A')
                else:
                    # Case where subscription key doesn't match sub_map
                    device['sub_status'] = 'Unknown'
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