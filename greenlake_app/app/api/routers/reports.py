# from fastapi import APIRouter, HTTPException, UploadFile, File, Form
# from fastapi.responses import JSONResponse
# from app.core.client import get_glp_client
# from typing import List, Optional
# import csv
# import io
# import asyncio

# router = APIRouter()

# @router.post("/generate")
# async def generate_report(
#     emails: Optional[str] = Form(None), # Comma separated for simple input
#     file: Optional[UploadFile] = File(None)
# ):
#     client = get_glp_client()
#     if not client:
#         raise HTTPException(status_code=401, detail="Client not configured")

#     target_emails = []
#     if emails:
#         target_emails.extend([e.strip() for e in emails.split(",") if e.strip()])
    
#     if file:
#         content = await file.read()
#         try:
#             # Decode bytes to string
#             text = content.decode('utf-8')
#             csv_reader = csv.reader(io.StringIO(text))
#             for row in csv_reader:
#                 # Assume first column is email
#                 if row and '@' in row[0]:
#                     target_emails.append(row[0].strip())
#         except Exception as e:
#             raise HTTPException(status_code=400, detail=f"Invalid CSV file: {str(e)}")

#     if not target_emails:
#         raise HTTPException(status_code=400, detail="No emails provided")

#     # De-duplicate
#     target_emails = list(set(target_emails))
    
#     # Process Reports
#     report_data = []
    
#     from pycentral.classic.msp import MSP
#     from pycentral.glp.user_management import UserMgmt
#     from pycentral.classic.audit_logs import Audit

#     msp_api = MSP()
#     user_api = UserMgmt()
#     audit_api = Audit()

#     # check if MSP
#     # check if MSP
#     is_msp = False
#     try:
#         msp_id = msp_api.get_msp_id(client)
#         if msp_id:
#             is_msp = True
#             customers = msp_api.get_all_customers(client)
#         else:
#             customers = []
#     except Exception as e:
#         print(f"MSP Check failed (assuming single tenant): {e}")
#         customers = []

#     # 1. Audit Trails (Global check if possible or per workspace? usually global for MSP if documented)
#     # The doc says "MSP Customer Would see logs of MSP's and tenants as well".
#     try:
#         audit_resp = audit_api.get_traillogs(client, username=email, limit=10)
#         if audit_resp['code'] == 200:
#             logs = audit_resp['msg']['items']
#             user_report['audit_trail_count'] = audit_resp['msg']['total']
#             user_report['recent_activity'] = [
#                 f"[{l.get('created_at_fmt', l.get('created_at'))}] {l.get('description')} (Target: {l.get('target')})" 
#                 for l in logs[:5]
#             ]
#     except Exception as e:
#         print(f"Audit fetch error for {email}: {e}")

#     # 2. Workspace & Role Scanning
#     # Check MSP Level
#     if is_msp:
#         try:
#             # Check MSP Users
#             # We have to fetch all/paged. Let's fetch first 100 which is reasonable for most.
#             msp_users = msp_api.get_msp_users(client, limit=100)
#             if msp_users['code'] == 200:
#                 for u in msp_users['msg']['users']:
#                     if u['username'].lower() == email.lower():
#                         user_report['workspaces'].append({
#                             "name": "MSP Account", 
#                             "role": u.get('role', 'Unknown'),
#                             "type": "MSP"
#                         })
#                         break
                        
#             # Check Customers
#             for cust in customers:
#                 # We have to fetch users for this customer.
#                 # Optimization: In real world, we would use async or parallel execution.
#                 # Here we do sequential logic for correctness.
#                 cust_users_resp = msp_api.get_customer_users(client, customer_id=cust['customer_id'], limit=100)
#                 if cust_users_resp and cust_users_resp['code'] == 200:
#                     for u in cust_users_resp['msg']['users']:
#                         if u['username'].lower() == email.lower():
#                             user_report['workspaces'].append({
#                                 "name": cust['customer_name'],
#                                 "role": u.get('role', 'Unknown'),
#                                 "type": "Tenant"
#                             })
#                             # Found user in this customer, stop checking this customer
#                             break
                            
#         except Exception as e:
#              print(f"MSP Scan error for {email}: {e}")

#     else:
#         # Single Tenant
#         try:
#             filter_str = f"username eq '{email}'"
#             users_resp = user_api.get_users(client, filter=filter_str)
#             if users_resp['code'] == 200 and users_resp['msg']['count'] > 0:
#                  # Found
#                  u = users_resp['msg']['items'][0]
#                  # Role might be in 'roles' list or 'role' field depending on API version.
#                  # GLP UserMgmt returns 'roles' which is a list.
#                  roles = u.get('roles', [])
#                  role_names = [r.get('name', r) for r in roles] if isinstance(roles, list) else [str(roles)]
                 
#                  user_report['workspaces'].append({
#                      "name": "Current Workspace",
#                      "role": ", ".join(role_names),
#                      "type": "Standalone"
#                  })
#         except Exception as e:
#              print(f"Single Tenant Scan error for {email}: {e}")

#     report_data.append(user_report)

#     return JSONResponse(content=report_data)


from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from app.core.client import get_glp_client
from typing import List, Optional
import csv
import io
import asyncio

router = APIRouter()

@router.post("/generate")
async def generate_report(
    emails: Optional[str] = Form(None), # Comma separated for simple input
    file: Optional[UploadFile] = File(None)
):
    client = get_glp_client()
    if not client:
        raise HTTPException(status_code=401, detail="Client not configured")

    target_emails = []
    if emails:
        target_emails.extend([e.strip() for e in emails.split(",") if e.strip()])
    
    if file:
        content = await file.read()
        try:
            # Decode bytes to string
            text = content.decode('utf-8')
            csv_reader = csv.reader(io.StringIO(text))
            for row in csv_reader:
                # Assume first column is email
                if row and '@' in row[0]:
                    target_emails.append(row[0].strip())
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid CSV file: {str(e)}")

    if not target_emails:
        raise HTTPException(status_code=400, detail="No emails provided")

    # De-duplicate
    target_emails = list(set(target_emails))
    
    # Process Reports
    report_data = []
    
    from pycentral.classic.msp import MSP
    from pycentral.glp.user_management import UserMgmt
    from pycentral.classic.audit_logs import Audit

    msp_api = MSP()
    user_api = UserMgmt()
    audit_api = Audit()

    # check if MSP
    is_msp = False
    try:
        msp_id = msp_api.get_msp_id(client)
        if msp_id:
            is_msp = True
            customers = msp_api.get_all_customers(client)
        else:
            customers = []
    except Exception as e:
        print(f"MSP Check failed (assuming single tenant): {e}")
        customers = []

    # Loop through each email
    for email in target_emails:
        # Initialize user report
        user_report = {
            'email': email,
            'workspaces': [],
            'audit_trail_count': 0,
            'recent_activity': []
        }
        
        # 1. Audit Trails (Global check if possible or per workspace? usually global for MSP if documented)
        # The doc says "MSP Customer Would see logs of MSP's and tenants as well".
        try:
            audit_resp = audit_api.get_traillogs(client, username=email, limit=10)
            if audit_resp['code'] == 200:
                logs = audit_resp['msg']['items']
                user_report['audit_trail_count'] = audit_resp['msg']['total']
                user_report['recent_activity'] = [
                    f"[{l.get('created_at_fmt', l.get('created_at'))}] {l.get('description')} (Target: {l.get('target')})" 
                    for l in logs[:5]
                ]
        except Exception as e:
            print(f"Audit fetch error for {email}: {e}")

    # 2. Workspace & Role Scanning
    # Check MSP Level
    if is_msp:
        try:
            # Check MSP Users
            # We have to fetch all/paged. Let's fetch first 100 which is reasonable for most.
            msp_users = msp_api.get_msp_users(client, limit=100)
            if msp_users['code'] == 200:
                for u in msp_users['msg']['users']:
                    if u['username'].lower() == email.lower():
                        user_report['workspaces'].append({
                            "name": "MSP Account", 
                            "role": u.get('role', 'Unknown'),
                            "type": "MSP"
                        })
                        break
                        
            # Check Customers
            for cust in customers:
                # We have to fetch users for this customer.
                # Optimization: In real world, we would use async or parallel execution.
                # Here we do sequential logic for correctness.
                cust_users_resp = msp_api.get_customer_users(client, customer_id=cust['customer_id'], limit=100)
                if cust_users_resp and cust_users_resp['code'] == 200:
                    for u in cust_users_resp['msg']['users']:
                        if u['username'].lower() == email.lower():
                            user_report['workspaces'].append({
                                "name": cust['customer_name'],
                                "role": u.get('role', 'Unknown'),
                                "type": "Tenant"
                            })
                            # Found user in this customer, stop checking this customer
                            break
                            
        except Exception as e:
             print(f"MSP Scan error for {email}: {e}")

    else:
        # Single Tenant
        try:
            filter_str = f"username eq '{email}'"
            users_resp = user_api.get_users(client, filter=filter_str)
            if users_resp['code'] == 200 and users_resp['msg']['count'] > 0:
                 # Found
                 u = users_resp['msg']['items'][0]
                 # Role might be in 'roles' list or 'role' field depending on API version.
                 # GLP UserMgmt returns 'roles' which is a list.
                 roles = u.get('roles', [])
                 role_names = [r.get('name', r) for r in roles] if isinstance(roles, list) else [str(roles)]
                 
                 user_report['workspaces'].append({
                     "name": "Current Workspace",
                     "role": ", ".join(role_names),
                     "type": "Standalone"
                 })
        except Exception as e:
             print(f"Single Tenant Scan error for {email}: {e}")

        # Add the user report to the results
        report_data.append(user_report)

    return JSONResponse(content=report_data)