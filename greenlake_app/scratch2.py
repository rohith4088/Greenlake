import asyncio
from app.core.client import get_glp_client
from app.lib.pycentral.glp.subscriptions import Subscriptions
import json

async def main():
    client = get_glp_client()
    subs_api = Subscriptions()
    subs = subs_api.get_all_subscriptions(client)
    for sub in subs:
        if sub.get('key') == 'PAYHHT6625UEUY':
            print("Found PAYHHT6625UEUY:", json.dumps(sub, indent=2))
            break
    else:
        print("Subscription PAYHHT6625UEUY not found.")

if __name__ == "__main__":
    asyncio.run(main())
