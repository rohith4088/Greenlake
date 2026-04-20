import csv
import re
from collections import defaultdict

input_file = '/Users/rohithr/Desktop/Greenlake_Everything/GLCP_cid_name_mapping.csv'

rows = []
with open(input_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

cid_map = defaultdict(list)
plat_id_to_cid = {}

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
        plat_id_to_cid[plat_id] = cid

unmapped = []
resolved_map = {}
for cid, entries in cid_map.items():
    msp_entries = [e for e in entries if e['type'] == 'MSP']
    if msp_entries:
        resolved_map[cid] = msp_entries[0]['platform_id']
    else:
        resolved_map[cid] = entries[0]['platform_id']

for i, row in enumerate(rows):
    cid_val = row.get('CID', '').strip()
    cust_id_val = row.get('Customer ID', '').strip()
    
    val_to_lookup = cid_val if cid_val else cust_id_val
    
    plat_id = resolved_map.get(val_to_lookup, '')
    if not plat_id:
        if val_to_lookup in plat_id_to_cid:
            plat_id = resolved_map.get(plat_id_to_cid[val_to_lookup], '')
            
    if not plat_id and val_to_lookup:
        unmapped.append((i+2, val_to_lookup))
        
print("Unmapped:", unmapped)
