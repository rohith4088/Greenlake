import asyncio
from app.core.client import get_glp_client
from app.api.routers.bulk import get_token, _async_lookup_device_uuid
import httpx
import json

async def main():
    client = get_glp_client()
    token = get_token(client)
    serial = 'CNLQKD553S'
    print(f"Checking device {serial}...")
    
    url = "https://global.api.greenlake.hpe.com/devices/v1beta1/devices"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"filter": f"serialNumber eq '{serial}'"}
    
    async with httpx.AsyncClient() as hc:
        resp = await hc.get(url, headers=headers, params=params)
        print("Device info:", json.dumps(resp.json(), indent=2))

if __name__ == "__main__":
    asyncio.run(main())
