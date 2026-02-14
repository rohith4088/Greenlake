import sys
import os

# Add lib to path so we can import pycentral as if it were a top-level package or just import relatively
# Adjusting python path to include app/lib
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "lib"))

from pycentral import NewCentralBase
from app.core.config import settings

class GreenLakeClient:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            # Check if we have token first
            if settings.GLP_ACCESS_TOKEN:
                token_info = {
                    "glp": {
                        "access_token": settings.GLP_ACCESS_TOKEN,
                        "cookies": {"cookie": settings.GLP_COOKIE} if settings.GLP_COOKIE else {}
                    }
                }
                # Base URL needs to be set if not default
                if not token_info["glp"].get("base_url"):
                     token_info["glp"]["base_url"] = "https://global.api.greenlake.hpe.com"
                     
                cls._instance = NewCentralBase(token_info=token_info)
            # Check if we have env vars or file
            elif settings.GLP_CLIENT_ID and settings.GLP_CLIENT_SECRET:
                token_info = {
                    "glp": {
                        "client_id": settings.GLP_CLIENT_ID,
                        "client_secret": settings.GLP_CLIENT_SECRET
                    }
                }
                cls._instance = NewCentralBase(token_info=token_info)
            elif os.path.exists(settings.TOKEN_FILE):
                cls._instance = NewCentralBase(token_info=settings.TOKEN_FILE)
            else:
                 # Return None or raise error if not configured
                 pass
        return cls._instance

    @classmethod
    def reload(cls, client_id, client_secret):
        token_info = {
            "glp": {
                "client_id": client_id,
                "client_secret": client_secret
            }
        }
        cls._instance = NewCentralBase(token_info=token_info)
        return cls._instance

    @classmethod
    def reload_with_token(cls, token, cookie=None, url=None):
        token_info = {
            "glp": {
                "access_token": token,
                "cookies": {"cookie": cookie} if cookie else {},
                "base_url": url or "https://global.api.greenlake.hpe.com"
            }
        }
        cls._instance = NewCentralBase(token_info=token_info)
        return cls._instance

def get_glp_client():
    return GreenLakeClient.get_instance()
