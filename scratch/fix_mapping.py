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

# Extract mappings
cid_map = defaultdict(list)
plat_id_to_cid = {}

for row in rows:
    cid = row.get('CID', '').strip()
    plat_id = row.get('Platform customer ID', '').strip()
    detail = row.get('Detail/Error', '')
    if cid and plat_id:
        type_match = re.search(r'Type:\s*([A-Z]+)', detail)
        ctype = type_match.group(1) if type_match else 'UNKNOWN'
        
        # Extract Found IDs as backup matching
        found_ids = []
        found_match = re.search(r'Found IDs:\s*([^|]+)', detail)
        if found_match:
            found_ids = [fid.strip() for fid in found_match.group(1).split(',')]
            
        cid_map[cid].append({
            'platform_id': plat_id,
            'type': ctype,
            'name': row.get('customer_name', '').strip(),
            'found_ids': found_ids
        })
        plat_id_to_cid[plat_id] = cid
        for fid in found_ids:
            if fid != cid:
                cid_map[fid].append({
                    'platform_id': plat_id,
                    'type': ctype,
                    'name': row.get('customer_name', '').strip(),
                    'found_ids': found_ids
                })

# Resolve logic
resolved_map = {}
for cid, entries in cid_map.items():
    msp_entries = [e for e in entries if e['type'] == 'MSP']
    if msp_entries:
        resolved_map[cid] = msp_entries[0]['platform_id']
    else:
        resolved_map[cid] = entries[0]['platform_id']

# Process and deduplicate
seen_serials = set()
unique_rows = []
unmapped_serials = []

for row in rows:
    serial = row.get('serial', '').strip()
    cid_val = row.get('CID', '').strip()
    cust_id_val = row.get('Customer ID', '').strip()
    
    val_to_lookup = cid_val if cid_val else cust_id_val
    
    # Custom fix for typo
    if val_to_lookup == 'cfe9f420067c488dbdb2b49d4d5f5b71':
        val_to_lookup = 'cfee9f420067c488dbdb2b49d4d5f5b71'
        
    plat_id = resolved_map.get(val_to_lookup, '')
    if not plat_id:
        if val_to_lookup in plat_id_to_cid:
            plat_id = resolved_map.get(plat_id_to_cid[val_to_lookup], '')
            
    if not plat_id:
        unmapped_serials.append(serial)
        
    row['platform id'] = plat_id
    
    if serial:
        if serial in seen_serials:
            continue
        seen_serials.add(serial)
        
    unique_rows.append(row)

with open(output_file, 'w', encoding='utf-8', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(unique_rows)

print("Mapping resolution complete.")
print(f"Total unique rows written: {len(unique_rows)}")
print(f"Serials without platform ID: {len(unmapped_serials)} {unmapped_serials}")

