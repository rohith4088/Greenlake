import requests
import csv
import time

INPUT_FILE = "keys_to_fetch.csv"
OUTPUT_FILE = "subscription_details.csv"
BATCH_SIZE = 10
DEBUG_URL = "http://localhost:8000/api/bulk/debug-subs"

def main():
    # Read keys
    keys = []
    with open(INPUT_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('KEY'):
                keys.append(row['KEY'])
    
    print(f"Loaded {len(keys)} keys.")
    
    results = []
    
    # Process in batches
    for i in range(0, len(keys), BATCH_SIZE):
        batch = keys[i:i+BATCH_SIZE]
        keys_str = ",".join(batch)
        print(f"Fetching batch {i} - {i+len(batch)}...")
        
        try:
            resp = requests.get(DEBUG_URL, params={"keys": keys_str})
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    results.extend(data)
                else:
                    print(f"Unexpected response format: {data}")
            else:
                print(f"Error fetching batch: {resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"Request failed: {e}")
            
        time.sleep(1) # Be nice
        
    # Write results
    with open(OUTPUT_FILE, 'w', newline='') as f:
        fieldnames = ['key', 'id', 'tier', 'status', 'end_date']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow(r)
            
    print(f"Done. Results written to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
