from datetime import datetime, timezone, date
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from .db import get_db
from .deps import require_permission, require_owner

router = APIRouter(prefix="/api", tags=["purchases-stock-suppliers"])
def stamp(): return datetime.now(timezone.utc).isoformat()
def schema(c):
 c.executescript('''
 CREATE TABLE IF NOT EXISTS suppliers(id INTEGER PRIMARY KEY AUTOINCREMENT,business_id INTEGER NOT NULL,name TEXT NOT NULL,phone TEXT NOT NULL DEFAULT '',address TEXT NOT NULL DEFAULT '',licence_number TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',is_active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(business_id,name));
 CREATE TABLE IF NOT EXISTS purchases(id INTEGER PRIMARY KEY AUTOINCREMENT,business_id INTEGER NOT NULL,supplier_id INTEGER NOT NULL,invoice_number TEXT NOT NULL,purchase_date TEXT NOT NULL,subtotal REAL NOT NULL,discount REAL NOT NULL,tax REAL NOT NULL,total REAL NOT NULL,paid_amount REAL NOT NULL,due_amount REAL NOT NULL,notes TEXT NOT NULL DEFAULT '',created_by INTEGER,created_at TEXT NOT NULL,UNIQUE(business_id,supplier_id,invoice_number));
 CREATE TABLE IF NOT EXISTS purchase_items(id INTEGER PRIMARY KEY AUTOINCREMENT,business_id INTEGER NOT NULL,purchase_id INTEGER NOT NULL,product_id INTEGER NOT NULL,batch_id INTEGER NOT NULL,unit_name TEXT NOT NULL,quantity REAL NOT NULL,unit_factor INTEGER NOT NULL,base_quantity INTEGER NOT NULL,unit_cost REAL NOT NULL,discount REAL NOT NULL,tax REAL NOT NULL,line_total REAL NOT NULL);
 CREATE TABLE IF NOT EXISTS batches(id INTEGER PRIMARY KEY AUTOINCREMENT,business_id INTEGER NOT NULL,product_id INTEGER NOT NULL,batch_number TEXT NOT NULL,expiry_date TEXT NOT NULL,quantity_base INTEGER NOT NULL DEFAULT 0,unit_cost REAL NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'active',status_reason TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(business_id,product_id,batch_number));
 CREATE TABLE IF NOT EXISTS stock_movements(id INTEGER PRIMARY KEY AUTOINCREMENT,business_id INTEGER NOT NULL,product_id INTEGER NOT NULL,batch_id INTEGER,kind TEXT NOT NULL,quantity_base INTEGER NOT NULL,reason TEXT NOT NULL DEFAULT '',reference_type TEXT NOT NULL DEFAULT '',reference_id INTEGER,created_by INTEGER,created_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS supplier_payments(id INTEGER PRIMARY KEY AUTOINCREMENT,business_id INTEGER NOT NULL,supplier_id INTEGER NOT NULL,amount REAL NOT NULL,method TEXT NOT NULL DEFAULT 'Cash',reference TEXT NOT NULL DEFAULT '',created_by INTEGER,created_at TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS supplier_payment_allocations(id INTEGER PRIMARY KEY AUTOINCREMENT,business_id INTEGER NOT NULL,payment_id INTEGER NOT NULL,purchase_id INTEGER NOT NULL,amount REAL NOT NULL);
 CREATE INDEX IF NOT EXISTS idx_batches_business_expiry ON batches(business_id,expiry_date);
 CREATE INDEX IF NOT EXISTS idx_movements_business_product ON stock_movements(business_id,product_id,id);
 ''')
class SupplierIn(BaseModel):
 name:str=Field(min_length=1,max_length=200); phone:str=''; address:str=''; licence_number:str=''; notes:str=''
class PurchaseItemIn(BaseModel):
 product_id:int; unit_name:str; quantity:float=Field(gt=0); unit_cost:float=Field(ge=0); batch_number:str=Field(min_length=1,max_length=100); expiry_date:str; discount:float=Field(default=0,ge=0); tax:float=Field(default=0,ge=0)
class PurchaseIn(BaseModel):
 supplier_id:int; invoice_number:str=Field(min_length=1,max_length=100); purchase_date:str; items:list[PurchaseItemIn]=Field(min_length=1); discount:float=Field(default=0,ge=0); tax:float=Field(default=0,ge=0); paid_amount:float=Field(default=0,ge=0); notes:str=''
class PaymentIn(BaseModel): amount:float=Field(gt=0); method:str='Cash'; reference:str=''
class AdjustmentIn(BaseModel): product_id:int; batch_id:int; quantity_base:int; reason:str=Field(min_length=3,max_length=300); kind:str='adjustment'
class BatchStatusIn(BaseModel): status:str; reason:str=Field(min_length=3,max_length=300)

@router.get('/suppliers')
def suppliers(user=Depends(require_permission('manage_suppliers')),c=Depends(get_db)):
 schema(c); b=user['business_id']; rows=c.execute('''SELECT s.*,COALESCE((SELECT SUM(p.due_amount) FROM purchases p WHERE p.business_id=s.business_id AND p.supplier_id=s.id),0) outstanding,(SELECT COUNT(*) FROM purchases p WHERE p.business_id=s.business_id AND p.supplier_id=s.id) purchase_count FROM suppliers s WHERE s.business_id=? ORDER BY s.name''',(b,)).fetchall(); return {'items':[dict(x) for x in rows]}
@router.post('/suppliers',status_code=201)
def add_supplier(x:SupplierIn,user=Depends(require_permission('manage_suppliers')),c=Depends(get_db)):
 schema(c); b=user['business_id']; now=stamp()
 try: cur=c.execute('INSERT INTO suppliers(business_id,name,phone,address,licence_number,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(b,x.name.strip(),x.phone,x.address,x.licence_number,x.notes,now,now)); c.commit(); return {'id':cur.lastrowid,'ok':True}
 except Exception as e: c.rollback(); raise HTTPException(409,'Supplier name already exists or could not be saved.')
@router.put('/suppliers/{sid}')
def edit_supplier(sid:int,x:SupplierIn,user=Depends(require_permission('manage_suppliers')),c=Depends(get_db)):
 schema(c); cur=c.execute('UPDATE suppliers SET name=?,phone=?,address=?,licence_number=?,notes=?,updated_at=? WHERE id=? AND business_id=?',(x.name.strip(),x.phone,x.address,x.licence_number,x.notes,stamp(),sid,user['business_id']));
 if not cur.rowcount: raise HTTPException(404,'Supplier not found.')
 return {'ok':True}
@router.get('/suppliers/{sid}/history')
def supplier_history(sid:int,user=Depends(require_permission('manage_suppliers')),c=Depends(get_db)):
 schema(c); b=user['business_id']; s=c.execute('SELECT id,name FROM suppliers WHERE id=? AND business_id=?',(sid,b)).fetchone()
 if not s: raise HTTPException(404,'Supplier not found.')
 return {'supplier':dict(s),'purchases':[dict(r) for r in c.execute('SELECT * FROM purchases WHERE business_id=? AND supplier_id=? ORDER BY purchase_date DESC,id DESC',(b,sid))], 'payments':[dict(r) for r in c.execute('SELECT * FROM supplier_payments WHERE business_id=? AND supplier_id=? ORDER BY id DESC',(b,sid))]}
@router.post('/suppliers/{sid}/payments',status_code=201)
def supplier_payment(sid:int,x:PaymentIn,user=Depends(require_permission('manage_suppliers')),c=Depends(get_db)):
 schema(c); b=user['business_id']; c.execute('BEGIN IMMEDIATE')
 try:
  if not c.execute('SELECT id FROM suppliers WHERE id=? AND business_id=?',(sid,b)).fetchone(): raise HTTPException(404,'Supplier not found.')
  cur=c.execute('INSERT INTO supplier_payments(business_id,supplier_id,amount,method,reference,created_by,created_at) VALUES(?,?,?,?,?,?,?)',(b,sid,x.amount,x.method,x.reference,user['id'],stamp())); pid=cur.lastrowid; remaining=x.amount
  invoices=c.execute('SELECT id,due_amount FROM purchases WHERE business_id=? AND supplier_id=? AND due_amount>0 ORDER BY purchase_date,id',(b,sid)).fetchall()
  for inv in invoices:
   if remaining<=0: break
   applied=min(remaining,inv['due_amount']); c.execute('UPDATE purchases SET paid_amount=paid_amount+?,due_amount=MAX(0,due_amount-?) WHERE id=? AND business_id=?',(applied,applied,inv['id'],b)); c.execute('INSERT INTO supplier_payment_allocations(business_id,payment_id,purchase_id,amount) VALUES(?,?,?,?)',(b,pid,inv['id'],applied)); remaining-=applied
  c.commit(); return {'id':pid,'amount':x.amount,'allocated':round(x.amount-remaining,2),'unallocated':round(remaining,2)}
 except Exception: c.rollback(); raise
@router.get('/products-for-purchase')
def products_for_purchase(user=Depends(require_permission('manage_purchases')),c=Depends(get_db),search:str=''):
 from .routes_products import ensure_schema
 ensure_schema(c); b=user['business_id']; q=f'%{search.strip()}%'; rows=c.execute("SELECT id,name,strength,barcode,purchase_price FROM products WHERE business_id=? AND status='active' AND (name LIKE ? OR barcode LIKE ?) ORDER BY name LIMIT 100",(b,q,q)).fetchall(); items=[]
 for r in rows:
  d=dict(r); d['units']=[dict(u) for u in c.execute('SELECT name,factor FROM product_units WHERE business_id=? AND product_id=? ORDER BY factor',(b,r['id']))]; items.append(d)
 return {'items':items}
@router.post('/purchases',status_code=201)
def create_purchase(x:PurchaseIn,user=Depends(require_permission('manage_purchases')),c=Depends(get_db)):
 from .routes_products import ensure_schema
 schema(c); ensure_schema(c); b=user['business_id']; today=date.today()
 try: pd=date.fromisoformat(x.purchase_date)
 except ValueError: raise HTTPException(400,'Enter a valid purchase date.')
 if pd>today: raise HTTPException(400,'Purchase date cannot be in the future.')
 c.execute('BEGIN IMMEDIATE')
 try:
  if not c.execute('SELECT id FROM suppliers WHERE id=? AND business_id=? AND is_active=1',(x.supplier_id,b)).fetchone(): raise HTTPException(404,'Choose an active supplier.')
  if c.execute('SELECT id FROM purchases WHERE business_id=? AND supplier_id=? AND invoice_number=?',(b,x.supplier_id,x.invoice_number.strip())).fetchone(): raise HTTPException(409,'This supplier invoice number already exists.')
  subtotal=0; prepared=[]
  for it in x.items:
   p=c.execute('SELECT id,name,purchase_price FROM products WHERE id=? AND business_id=? AND status=\'active\'',(it.product_id,b)).fetchone()
   if not p: raise HTTPException(404,'A selected product was not found or is inactive.')
   unit=c.execute('SELECT name,factor FROM product_units WHERE business_id=? AND product_id=? AND name=?',(b,it.product_id,it.unit_name)).fetchone()
   if not unit: raise HTTPException(400,f'Invalid unit for {p["name"]}.')
   if not it.batch_number.strip(): raise HTTPException(400,'Batch number is required.')
   try: exp=date.fromisoformat(it.expiry_date)
   except ValueError: raise HTTPException(400,'Enter a valid expiry date.')
   if exp<today: raise HTTPException(400,f'Expiry date for {p["name"]} is in the past.')
   existing=c.execute('SELECT id,expiry_date,status FROM batches WHERE business_id=? AND product_id=? AND batch_number=?',(b,it.product_id,it.batch_number.strip())).fetchone()
   if existing and existing['expiry_date']!=it.expiry_date: raise HTTPException(409,'Same batch number cannot have a different expiry date.')
   if existing and existing['status']!='active': raise HTTPException(409,'This batch is blocked, recalled or quarantined; receiving stock into it is not allowed.')
   base=round(it.quantity*unit['factor'])
   if abs(base-it.quantity*unit['factor'])>1e-7: raise HTTPException(400,'Quantity does not convert to a whole base unit.')
   line=max(0,it.quantity*it.unit_cost-it.discount)+it.tax; subtotal+=line
   prepared.append((it,p,unit,existing,int(base),line))
  total=max(0,subtotal-x.discount)+x.tax
  if x.paid_amount>total+0.00001: raise HTTPException(400,'Paid amount cannot exceed purchase total.')
  now=stamp(); cur=c.execute('INSERT INTO purchases(business_id,supplier_id,invoice_number,purchase_date,subtotal,discount,tax,total,paid_amount,due_amount,notes,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(b,x.supplier_id,x.invoice_number.strip(),x.purchase_date,subtotal,x.discount,x.tax,total,x.paid_amount,max(0,total-x.paid_amount),x.notes,user['id'],now)); purchase_id=cur.lastrowid
  for it,p,unit,existing,base,line in prepared:
   if existing: batch_id=existing['id']; c.execute('UPDATE batches SET quantity_base=quantity_base+?,unit_cost=?,updated_at=? WHERE id=? AND business_id=?',(base,it.unit_cost,now,batch_id,b))
   else: batch_id=c.execute('INSERT INTO batches(business_id,product_id,batch_number,expiry_date,quantity_base,unit_cost,status,created_at,updated_at) VALUES(?,?,?,?,?,?,\'active\',?,?)',(b,it.product_id,it.batch_number.strip(),it.expiry_date,base,it.unit_cost,now,now)).lastrowid
   c.execute('INSERT INTO purchase_items(business_id,purchase_id,product_id,batch_id,unit_name,quantity,unit_factor,base_quantity,unit_cost,discount,tax,line_total) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(b,purchase_id,it.product_id,batch_id,it.unit_name,it.quantity,unit['factor'],base,it.unit_cost,it.discount,it.tax,line))
   c.execute('INSERT INTO stock_movements(business_id,product_id,batch_id,kind,quantity_base,reason,reference_type,reference_id,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(b,it.product_id,batch_id,'purchase',base,f'Purchase invoice {x.invoice_number}','purchase',purchase_id,user['id'],now))
  c.commit(); return {'id':purchase_id,'total':round(total,2),'due_amount':round(max(0,total-x.paid_amount),2),'message':'Purchase saved; stock and supplier balance updated.'}
 except Exception: c.rollback(); raise
@router.get('/purchases')
def purchases(user=Depends(require_permission('manage_purchases')),c=Depends(get_db)):
 schema(c); b=user['business_id']; rows=c.execute('SELECT p.*,s.name supplier_name FROM purchases p JOIN suppliers s ON s.id=p.supplier_id AND s.business_id=p.business_id WHERE p.business_id=? ORDER BY p.id DESC LIMIT 200',(b,)).fetchall(); return {'items':[dict(r) for r in rows]}
@router.get('/purchases/{pid}/print')
def purchase_print(pid:int,user=Depends(require_permission('manage_purchases')),c=Depends(get_db)):
 schema(c); b=user['business_id']; p=c.execute('SELECT p.*,s.name supplier_name,s.phone supplier_phone FROM purchases p JOIN suppliers s ON s.id=p.supplier_id AND s.business_id=p.business_id WHERE p.id=? AND p.business_id=?',(pid,b)).fetchone()
 if not p: raise HTTPException(404,'Purchase not found.')
 items=c.execute('SELECT i.*,pr.name product_name,ba.batch_number,ba.expiry_date FROM purchase_items i JOIN products pr ON pr.id=i.product_id AND pr.business_id=i.business_id JOIN batches ba ON ba.id=i.batch_id AND ba.business_id=i.business_id WHERE i.purchase_id=? AND i.business_id=?',(pid,b)).fetchall()
 return {'purchase':dict(p),'items':[dict(r) for r in items]}
@router.get('/stock')
def stock(user=Depends(require_permission('view_stock')),c=Depends(get_db)):
 schema(c); b=user['business_id']; settings=c.execute('SELECT near_expiry_days FROM businesses WHERE id=?',(b,)).fetchone(); near_days=int(settings['near_expiry_days']) if settings else 90; can_cost=user['role']=='owner' or 'view_purchase_price' in user.get('permissions',[]); rows=c.execute('''SELECT ba.*,p.name product_name,p.minimum_stock,p.purchase_price product_cost,(SELECT pi.unit_cost*1.0/pi.unit_factor FROM purchase_items pi WHERE pi.batch_id=ba.id AND pi.business_id=ba.business_id ORDER BY pi.id DESC LIMIT 1) cost_base FROM batches ba JOIN products p ON p.id=ba.product_id AND p.business_id=ba.business_id WHERE ba.business_id=? ORDER BY ba.expiry_date,p.name''',(b,)).fetchall(); out=[]
 product_totals={};
 for r in rows: product_totals[r['product_id']]=product_totals.get(r['product_id'],0)+r['quantity_base']
 for r in rows:
  d=dict(r); qty=d['quantity_base']; threshold=d['minimum_stock']; exp=date.fromisoformat(d['expiry_date']); status=d['status'].capitalize() if d['status']!='active' else ('Expired' if exp<date.today() else 'Near expiry' if (exp-date.today()).days<=near_days else 'Low' if product_totals.get(d['product_id'],0)<=threshold else 'OK'); d['display_status']=status; d['stock_value']=round(qty*(d['cost_base'] or 0),2) if can_cost else None
  units=[dict(u) for u in c.execute('SELECT name,factor FROM product_units WHERE business_id=? AND product_id=? ORDER BY factor DESC',(b,d['product_id']))]; remaining=qty; parts=[]
  for unit in units:
   count=remaining//unit['factor']
   if count: parts.append(f"{count} {unit['name']}"); remaining%=unit['factor']
  d['display_quantity']=' '.join(parts) if parts else f"0 {units[-1]['name'] if units else 'Unit'}"
  if not can_cost: d.pop('unit_cost',None); d.pop('product_cost',None); d.pop('cost_base',None)
  out.append(d)
 return {'items':out,'total_units':sum(x['quantity_base'] for x in out),'stock_value':round(sum(x['stock_value'] or 0 for x in out),2) if can_cost else None}
@router.get('/stock/movements')
def movements(user=Depends(require_permission('view_stock')),c=Depends(get_db),limit:int=Query(default=200,ge=1,le=1000)):
 schema(c); b=user['business_id']; rows=c.execute('''SELECT m.*,p.name product_name,ba.batch_number,ba.expiry_date,u.full_name user_name FROM stock_movements m JOIN products p ON p.id=m.product_id AND p.business_id=m.business_id LEFT JOIN batches ba ON ba.id=m.batch_id AND ba.business_id=m.business_id LEFT JOIN users u ON u.id=m.created_by AND u.business_id=m.business_id WHERE m.business_id=? ORDER BY m.id DESC LIMIT ?''',(b,limit)).fetchall(); return {'items':[dict(r) for r in rows]}
@router.post('/stock/adjustments',status_code=201)
def adjust(x:AdjustmentIn,user=Depends(require_permission('adjust_stock')),c=Depends(get_db)):
 schema(c); b=user['business_id']; c.execute('BEGIN IMMEDIATE')
 try:
  batch=c.execute('SELECT * FROM batches WHERE id=? AND business_id=? AND product_id=?',(x.batch_id,b,x.product_id)).fetchone()
  if not batch: raise HTTPException(404,'Batch not found for this product.')
  if x.kind not in ('adjustment','damaged','supplier_return'): raise HTTPException(400,'Choose adjustment, damaged or supplier_return.')
  if x.kind=='supplier_return' and x.quantity_base<=0: raise HTTPException(400,'Supplier return quantity must be positive.')
  delta=-abs(x.quantity_base) if x.kind in ('damaged','supplier_return') else x.quantity_base
  if batch['quantity_base']+delta<0: raise HTTPException(400,'There is not enough stock in this batch.')
  now=stamp(); c.execute('UPDATE batches SET quantity_base=quantity_base+?,updated_at=? WHERE id=? AND business_id=?',(delta,now,x.batch_id,b)); c.execute('INSERT INTO stock_movements(business_id,product_id,batch_id,kind,quantity_base,reason,reference_type,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(b,x.product_id,x.batch_id,x.kind,delta,x.reason.strip(),'adjustment',user['id'],now)); c.commit(); return {'ok':True,'quantity_change':delta}
 except Exception: c.rollback(); raise
@router.post('/stock/batches/{batch_id}/status')
def batch_status(batch_id:int,x:BatchStatusIn,user=Depends(require_owner),c=Depends(get_db)):
 schema(c); b=user['business_id']
 if x.status not in ('active','blocked','recalled','quarantine'): raise HTTPException(400,'Status must be active, blocked, recalled or quarantine.')
 cur=c.execute('UPDATE batches SET status=?,status_reason=?,updated_at=? WHERE id=? AND business_id=?',(x.status,x.reason.strip(),stamp(),batch_id,b))
 if not cur.rowcount: raise HTTPException(404,'Batch not found.')
 row=c.execute('SELECT product_id,quantity_base FROM batches WHERE id=? AND business_id=?',(batch_id,b)).fetchone(); c.execute('INSERT INTO stock_movements(business_id,product_id,batch_id,kind,quantity_base,reason,reference_type,created_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(b,row['product_id'],batch_id,'status_change',0,f'{x.status}: {x.reason.strip()}','batch',user['id'],stamp())); c.commit(); return {'ok':True}
