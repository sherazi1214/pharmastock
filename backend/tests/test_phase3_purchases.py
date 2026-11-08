from datetime import date, timedelta
from .conftest import setup_owner, login


def seed_product(client, headers):
    p = {
      "name":"Test Medicine", "generic_name":"", "strength":"10 mg", "dosage_form":"Tablet", "manufacturer":"", "pack_size":"100 tablets", "barcode":"PH3-TEST-001", "category":"", "purchase_price":10, "wholesale_price":12, "retail_price":15, "mrp":18, "minimum_stock":10, "status":"active", "prescription_required":False, "drap_registration_number":"", "units":[{"name":"Tablet","factor":1},{"name":"Strip","factor":10},{"name":"Box","factor":100}], "barcodes":[]
    }
    r=client.post('/api/products',headers=headers,json=p); assert r.status_code==201,r.text; return r.json()

def seed_supplier(client, headers):
    r=client.post('/api/suppliers',headers=headers,json={"name":"Verified Test Supplier","phone":"","address":"","licence_number":"","notes":""}); assert r.status_code==201,r.text; return r.json()['id']

def test_purchase_adds_exact_base_units_and_tracks_movement(client, owner_headers):
    p=seed_product(client,owner_headers); sid=seed_supplier(client,owner_headers)
    exp=(date.today()+timedelta(days=300)).isoformat()
    r=client.post('/api/purchases',headers=owner_headers,json={"supplier_id":sid,"invoice_number":"INV-1","purchase_date":date.today().isoformat(),"items":[{"product_id":p['id'],"unit_name":"Box","quantity":3,"unit_cost":100,"batch_number":"BATCH-1","expiry_date":exp}],"discount":0,"tax":0,"paid_amount":100,"notes":""})
    assert r.status_code==201,r.text
    stock=client.get('/api/stock',headers=owner_headers).json()['items']; assert stock[0]['quantity_base']==300
    supplier=client.get('/api/suppliers',headers=owner_headers).json()['items'][0]; assert round(supplier['outstanding'],2)==200
    movement=client.get('/api/stock/movements',headers=owner_headers).json()['items']; assert movement[0]['quantity_base']==300

def test_purchase_rejects_same_batch_different_expiry_without_partial_changes(client, owner_headers):
    p=seed_product(client,owner_headers); sid=seed_supplier(client,owner_headers); exp=(date.today()+timedelta(days=300)).isoformat()
    base={"supplier_id":sid,"purchase_date":date.today().isoformat(),"items":[{"product_id":p['id'],"unit_name":"Box","quantity":1,"unit_cost":100,"batch_number":"BATCH-X","expiry_date":exp}],"discount":0,"tax":0,"paid_amount":0,"notes":""}
    first=client.post('/api/purchases',headers=owner_headers,json={**base,"invoice_number":"INV-A"}); assert first.status_code==201,first.text
    before=client.get('/api/stock',headers=owner_headers).json()['items'][0]['quantity_base']
    second=client.post('/api/purchases',headers=owner_headers,json={**base,"invoice_number":"INV-B","items":[{**base['items'][0],"expiry_date":(date.today()+timedelta(days=400)).isoformat()}]})
    assert second.status_code==409
    after=client.get('/api/stock',headers=owner_headers).json()['items'][0]['quantity_base']; assert before==after==100
    purchases=client.get('/api/purchases',headers=owner_headers).json()['items']; assert len(purchases)==1

def test_supplier_payment_applies_oldest_invoice_first(client, owner_headers):
    p=seed_product(client,owner_headers); sid=seed_supplier(client,owner_headers); exp=(date.today()+timedelta(days=300)).isoformat()
    for n in ('INV-OLD','INV-NEW'):
      r=client.post('/api/purchases',headers=owner_headers,json={"supplier_id":sid,"invoice_number":n,"purchase_date":date.today().isoformat(),"items":[{"product_id":p['id'],"unit_name":"Box","quantity":1,"unit_cost":100,"batch_number":n,"expiry_date":exp}],"discount":0,"tax":0,"paid_amount":0,"notes":""}); assert r.status_code==201,r.text
    pay=client.post(f'/api/suppliers/{sid}/payments',headers=owner_headers,json={"amount":150,"method":"Cash","reference":""}); assert pay.status_code==201,pay.text
    inv=client.get(f'/api/suppliers/{sid}/history',headers=owner_headers).json()['purchases']; dues={x['invoice_number']:x['due_amount'] for x in inv}; assert dues['INV-OLD']==0 and dues['INV-NEW']==50
