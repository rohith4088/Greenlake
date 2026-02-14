from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.core.client import GreenLakeClient
from app.core.config import settings
from typing import Optional

router = APIRouter()

class AuthConfig(BaseModel):
    mode: str  # "client_credentials" or "token"
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    access_token: Optional[str] = None
    cookie: Optional[str] = None
    url: Optional[str] = None

@router.post("/config")
async def update_auth_config(config: AuthConfig):
    try:
        client = GreenLakeClient.get_instance()
        
        if config.mode == "token":
            if not config.access_token:
                raise HTTPException(status_code=400, detail="Access Token is required for token mode")
            
            # Update settings
            settings.GLP_ACCESS_TOKEN = config.access_token
            settings.GLP_COOKIE = config.cookie
            
            # Persist to token.yaml
            import yaml
            token_data = {
                "glp": {
                    "access_token": config.access_token,
                    "cookies": {"cookie": config.cookie} if config.cookie else {},
                    "base_url": config.url or "https://global.api.greenlake.hpe.com"
                }
            }
            try:
                with open("token.yaml", "w") as f:
                    yaml.dump(token_data, f)
            except Exception as e:
                print(f"Failed to save token.yaml: {e}")

            # Reload client with new token
            GreenLakeClient.reload_with_token(
                token=config.access_token,
                cookie=config.cookie,
                url=config.url
            )
            return {"message": "Switched to Token/Cookie Authentication"}
            
        else:
            # Client Credentials
            c_id = config.client_id or settings.GLP_CLIENT_ID
            c_secret = config.client_secret or settings.GLP_CLIENT_SECRET
            
            if not c_id or not c_secret:
                raise HTTPException(status_code=400, detail="Client ID and Secret are required")
                
            settings.GLP_CLIENT_ID = c_id
            settings.GLP_CLIENT_SECRET = c_secret
            
            # Persist to token.yaml
            import yaml
            token_data = {
                "glp": {
                    "client_id": c_id,
                    "client_secret": c_secret,
                     "base_url": "https://global.api.greenlake.hpe.com"
                }
            }
            try:
                with open("token.yaml", "w") as f:
                    yaml.dump(token_data, f)
            except Exception as e:
                 print(f"Failed to save token.yaml: {e}")

            # Reload client
            GreenLakeClient.reload(c_id, c_secret)
            return {"message": "Switched to Client Credentials Authentication"}
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/config")
async def get_auth_config():
    # Return current mode (masked secrets)
    mode = "token" if settings.GLP_ACCESS_TOKEN else "client_credentials"
    return {
        "mode": mode,
        "client_id": settings.GLP_CLIENT_ID,
        "url": "https://global.api.greenlake.hpe.com", # Default or from settings
        "has_token": bool(settings.GLP_ACCESS_TOKEN),
        "has_cookie": bool(settings.GLP_COOKIE)
    }
