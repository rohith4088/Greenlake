from app.core.client import GreenLakeClient
from app.lib.pycentral.glp.subscriptions import Subscriptions
import json

def debug_subscriptions():
    client = GreenLakeClient.get_instance()
    if not client:
        print("Client not configured")
        return

    keys_to_check = [
        "E67AA03F6CCFC4D5C8",
        "E441D3640B06F490E8",
        "EE257F4F3355844189" # The one mentioned in previous error
    ]

    subs_api = Subscriptions()
    
    print(f"{'KEY':<20} | {'ID':<36} | {'STATUS':<15} | {'END DATE':<20}")
    print("-" * 100)

    for key in keys_to_check:
        # 1. Try to resolve ID
        found, result = subs_api.get_sub_id(client, key)
        sub_id = result if found else "NOT FOUND"
        
        # 2. Fetch Details (using get_all_subscriptions and filtering, or specific get if available)
        # The API doesn't seem to have a direct 'get_by_key' except searching.
        
        status = "N/A"
        end_date = "N/A"
        
        if found:
            # We have ID, let's try to get details. 
            # In pycentral/glp/subscriptions.py, get_subscription uses filter.
            # Let's use that.
            resp = subs_api.get_subscription(client, filter=f"id eq '{sub_id}'")
            if resp['code'] == 200 and resp['msg']['count'] > 0:
                item = resp['msg']['items'][0]
                status = item.get('status', 'N/A')
                end_date = item.get('expiresAt', 'N/A')
            else:
                # Try filtering by key directly
                resp = subs_api.get_subscription(client, filter=f"key eq '{key}'")
                if resp['code'] == 200 and resp['msg']['count'] > 0:
                     item = resp['msg']['items'][0]
                     status = item.get('status', 'N/A')
                     end_date = item.get('expiresAt', 'N/A')
                     if sub_id == "NOT FOUND":
                         sub_id = item.get('id', 'FOUND_BY_KEY')

        print(f"{key:<20} | {sub_id:<36} | {status:<15} | {end_date:<20}")

if __name__ == "__main__":
    debug_subscriptions()
