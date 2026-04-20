import csv
import re
from collections import defaultdict

input_file = '/Users/rohithr/Desktop/Greenlake_Everything/GLCP_cid_name_mapping.csv'
output_file = '/Users/rohithr/Desktop/Greenlake_Everything/GLCP_cid_name_mapping_fixed.csv'

rows = []
with open(input_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    for row in reader:
        rows.append(row)

# Build a mapping from CID -> List of {Platform customer ID, Type, customer_name}
cid_map = defaultdict(list)
for row in rows:
    cid = row.get('CID', '').strip()
    plat_id = row.get('Platform customer ID', '').strip()
    detail = row.get('Detail/Error', '')
    if cid and plat_id:
        type_match = re.search(r'Type:\s*([A-Z]+)', detail)
        ctype = type_match.group(1) if type_match else 'UNKNOWN'
        cid_map[cid].append({
            'platform_id': plat_id,
            'type': ctype,
            'name': row.get('customer_name', '').strip()
        })

# Also build a mapping from Customer ID to CID, just in case Customer ID in row 61+ is actually the CID.
# Looking at rows 61+, the 'Customer ID' column has values like 'ced8b9a7c56d4d5b9c047ed1de8f10db', which look like CIDs.

print("CID Map count:", len(cid_map))

# Now resolve the target platform ID for each CID.
# Rule: if a tenant cid is matched give the msp workspace id only.
resolved_map = {}
for cid, entries in cid_map.items():
    msp_entries = [e for e in entries if e['type'] == 'MSP']
    standalone_entries = [e for e in entries if e['type'] == 'STANDALONE']
    tenant_entries = [e for e in entries if e['type'] == 'TENANT']
    
    if msp_entries:
        resolved_map[cid] = msp_entries[0]['platform_id']
    elif standalone_entries:
        resolved_map[cid] = standalone_entries[0]['platform_id']
    elif tenant_entries:
        resolved_map[cid] = tenant_entries[0]['platform_id']
    else:
        resolved_map[cid] = entries[0]['platform_id']

# Process all rows to populate 'platform id' and remove duplicates.
# A duplicate row might mean same serial and same resolved platform id.
seen_serials = set()
unique_rows = []

for row in rows:
    serial = row.get('serial', '').strip()
    
    # The CID could be in 'CID' or 'Customer ID'
    cid_val = row.get('CID', '').strip()
    if not cid_val:
        cid_val = row.get('Customer ID', '').strip()
        
    resolved_plat_id = resolved_map.get(cid_val, '')
    if not resolved_plat_id:
        # Check if the Customer ID is already a Platform customer ID
        for plat_entries in cid_map.values():
            for e in plat_entries:
                if e['platform_id'] == cid_val:
                    resolved_plat_id = e['platform_id']
                    break
            if resolved_plat_id:
                break
                
    row['platform id'] = resolved_plat_id
    
    # We want to remove duplicates based on serial and platform id. 
    # But wait, does the user want the full file, or just the list of serials and platform IDs?
    # "do not want any duplicates and i want an detailed report on the analysis"
    # If the serial is already seen, it's a duplicate. But let's only consider rows that have a serial.
    if serial:
        if serial in seen_serials:
            continue
        seen_serials.add(serial)
    
    unique_rows.append(row)

with open(output_file, 'w', encoding='utf-8', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(unique_rows)

print(f"Total rows before: {len(rows)}")
print(f"Total rows after removing duplicates: {len(unique_rows)}")
