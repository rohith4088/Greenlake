import sys
import os
import json
import logging

# Add lib to path
sys.path.append(os.path.join(os.path.dirname(__file__), "lib"))

from app.core.client import get_glp_client
from pycentral.glp.subscriptions import Subscriptions
from pycentral.glp.devices import Devices
from pycentral.glp.user_management import UserMgmt

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def debug_data():
    client = get_glp_client()
    if not client:
        print("Client not configured! Please configure credentials.")
        return

    print("\n--- DEBUGGING SUBSCRIPTIONS ---")
    sub_api = Subscriptions()
    try:
        subs = sub_api.get_all_subscriptions(client)
        print(f"Found {len(subs)} subscriptions.")
        if len(subs) > 0:
            print("Sample Subscription 0:")
            print(json.dumps(subs[0], indent=2))
    except Exception as e:
        print(f"Error fetching subscriptions: {e}")

    print("\n--- DEBUGGING DEVICES ---")
    dev_api = Devices()
    try:
        devices = dev_api.get_all_devices(client)
        print(f"Found {len(devices)} devices.")
        if len(devices) > 0:
            print("Sample Device 0:")
            print(json.dumps(devices[0], indent=2))
            
            # Find a device with subscription
            for d in devices:
                if d.get('subscription'):
                    print("\nDevice WITH Subscription found:")
                    print(json.dumps(d, indent=2))
                    break
    except Exception as e:
        print(f"Error fetching devices: {e}")

    print("\n--- DEBUGGING USERS ---")
    user_api = UserMgmt()
    try:
        resp = user_api.get_users(client)
        if resp['code'] == 200:
            users = resp['msg']['items']
            print(f"Found {len(users)} users.")
            if len(users) > 0:
                print("Sample User 0:")
                print(json.dumps(users[0], indent=2))
        else:
             print(f"Error fetching users: {resp}")
    except Exception as e:
        print(f"Error fetching users: {e}")

if __name__ == "__main__":
    # Ensure settings are loaded
    from app.core.config import settings
    # Initialize client if needed (it usually loads from env/file)
    debug_data()
