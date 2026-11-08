import csv
import io
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .db import get_db
from .deps import require_permission

router = APIRouter(prefix="/api/products", tags=["products"])

def now():
    return datetime.now(timezone.utc).isoformat()

def ensure_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS products (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      business_id INTEGER NOT NULL REFERENCES businesses(id),
      name TEXT NOT NULL, generic_name TEXT NOT NULL DEFAULT '', strength TEXT NOT NULL DEFAULT '',
      dosage_form TEXT NOT NULL DEFAULT '', manufacturer TEXT NOT NULL DEFAULT '', pack_size TEXT NOT NULL DEFAULT '',
      barcode TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '', purchase_price REAL NOT NULL DEFAULT 0,
      wholesale_price REAL NOT NULL DEFAULT 0, retail_price REAL NOT NULL DEFAULT 0, mrp REAL NOT NULL DEFAULT 0,
      minimum_stock REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active',
      prescription_required INTEGER NOT NULL DEFAULT 0, drap_registration_number TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_products_business_name ON products(business_id,name);
    CREATE TABLE IF NOT EXISTS product_units (
      id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
      name TEXT NOT NULL, factor INTEGER NOT NULL CHECK(factor>0), sort_order INTEGER NOT NULL DEFAULT 0,
      UNIQUE(business_id,product_id,name), FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS product_barcodes (
      id INTEGER PRIMARY KEY AUTOINCREMENT, business_id INTEGER NOT NULL, product_id INTEGER NOT NULL,
      barcode TEXT NOT NULL, UNIQUE(business_id,barcode), FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_product_barcodes_code ON product_barcodes(business_id,barcode);
    """)
    conn.commit()

class UnitIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    factor: int = Field(ge=1)

class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    generic_name: str = ""
    strength: str = ""
    dosage_form: str = ""
    manufacturer: str = ""
    pack_size: str = ""
    barcode: str = ""
    category: str = ""
    purchase_price: float = Field(default=0, ge=0)
    wholesale_price: float = Field(default=0, ge=0)
    retail_price: float = Field(default=0, ge=0)
    mrp: float = Field(default=0, ge=0)
    minimum_stock: float = Field(default=0, ge=0)
    status: str = "active"
    prescription_required: bool = False
    drap_registration_number: str = ""
    units: list[UnitIn] = Field(default_factory=lambda: [UnitIn(name="Unit", factor=1)])
    barcodes: list[str] = Field(default_factory=list)

def checked_units(units):
    if not units: raise HTTPException(400, "Add at least one unit.")
    values=[]; names=set()
    for unit in units:
        name=unit.name.strip()
        if not name or name.lower() in names: raise HTTPException(400,"Unit names must be unique.")
        names.add(name.lower()); values.append((name,unit.factor))
    values.sort(key=lambda x:x[1])
    if values[0][1] != 1: raise HTTPException(400,"The smallest unit must have factor 1.")
    for i in range(1,len(values)):
        if values[i][1] % values[i-1][1] != 0:
            raise HTTPException(400,"Each larger unit must be a whole multiple of the smaller unit.")
    return values

def as_product(row, conn, business_id):
    d=dict(row); d["prescription_required"]=bool(d["prescription_required"])
    d["units"]=[dict(x) for x in conn.execute("SELECT name,factor,sort_order FROM product_units WHERE business_id=? AND product_id=? ORDER BY factor",(business_id,d["id"]))]
    d["barcodes"]=[x["barcode"] for x in conn.execute("SELECT barcode FROM product_barcodes WHERE business_id=? AND product_id=? ORDER BY id",(business_id,d["id"]))]
    return d

def save(conn,business_id,data,product_id=None):
    name=data.name.strip()
    if not name: raise HTTPException(400,"Product name is required.")
    if data.retail_price > data.mrp: raise HTTPException(400,"Retail price must not exceed MRP.")
    if data.status not in ("active","inactive"): raise HTTPException(400,"Invalid product status.")
    units=checked_units(data.units)
    codes=list(dict.fromkeys([x.strip() for x in [data.barcode,*data.barcodes] if x and x.strip()]))
    for code in codes:
        existing=conn.execute("SELECT product_id FROM product_barcodes WHERE business_id=? AND barcode=?",(business_id,code)).fetchone()
        if existing and existing["product_id"] != product_id: raise HTTPException(409,f"Barcode {code} is already attached to another product.")
        existing=conn.execute("SELECT id FROM products WHERE business_id=? AND barcode=?",(business_id,code)).fetchone()
        if existing and existing["id"] != product_id: raise HTTPException(409,f"Barcode {code} is already used.")
    fields=(name,data.generic_name,data.strength,data.dosage_form,data.manufacturer,data.pack_size,data.barcode,data.category,data.purchase_price,data.wholesale_price,data.retail_price,data.mrp,data.minimum_stock,data.status,int(data.prescription_required),data.drap_registration_number)
    stamp=now()
    if product_id:
        if not conn.execute("SELECT id FROM products WHERE id=? AND business_id=?",(product_id,business_id)).fetchone(): raise HTTPException(404,"Product not found.")
        conn.execute("""UPDATE products SET name=?,generic_name=?,strength=?,dosage_form=?,manufacturer=?,pack_size=?,barcode=?,category=?,purchase_price=?,wholesale_price=?,retail_price=?,mrp=?,minimum_stock=?,status=?,prescription_required=?,drap_registration_number=?,updated_at=? WHERE id=? AND business_id=?""",(*fields,stamp,product_id,business_id))
        conn.execute("DELETE FROM product_units WHERE business_id=? AND product_id=?",(business_id,product_id))
        conn.execute("DELETE FROM product_barcodes WHERE business_id=? AND product_id=?",(business_id,product_id))
    else:
        cur=conn.execute("""INSERT INTO products(business_id,name,generic_name,strength,dosage_form,manufacturer,pack_size,barcode,category,purchase_price,wholesale_price,retail_price,mrp,minimum_stock,status,prescription_required,drap_registration_number,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(*fields,stamp,stamp))
        product_id=cur.lastrowid
    for i,(unit,factor) in enumerate(units):
        conn.execute("INSERT INTO product_units(business_id,product_id,name,factor,sort_order) VALUES(?,?,?,?,?)",(business_id,product_id,unit,factor,i))
    for code in codes:
        conn.execute("INSERT INTO product_barcodes(business_id,product_id,barcode) VALUES(?,?,?)",(business_id,product_id,code))
    return product_id

@router.get("")
def list_products(search:str="",limit:int=Query(100,ge=1,le=1000),offset:int=Query(0,ge=0),user=Depends(require_permission("view_products")),conn=Depends(get_db)):
    ensure_schema(conn); b=user["business_id"]; q=f"%{search.strip()}%"
    rows=conn.execute("SELECT * FROM products WHERE business_id=? AND (name LIKE ? OR generic_name LIKE ? OR barcode LIKE ? OR manufacturer LIKE ?) ORDER BY name LIMIT ? OFFSET ?",(b,q,q,q,q,limit,offset)).fetchall()
    total=conn.execute("SELECT COUNT(*) n FROM products WHERE business_id=? AND (name LIKE ? OR generic_name LIKE ? OR barcode LIKE ? OR manufacturer LIKE ?)",(b,q,q,q,q)).fetchone()["n"]
    result=[as_product(x,conn,b) for x in rows]
    # Avoid returning purchase price without permission.
    if user["role"]!="owner" and "view_purchase_price" not in user["permissions"]:
        for x in result: x.pop("purchase_price",None)
    return {"items":result,"total":total}

@router.post("")
def create_product(data:ProductIn,user=Depends(require_permission("manage_products")),conn=Depends(get_db)):
    ensure_schema(conn); pid=save(conn,user["business_id"],data); conn.commit()
    return as_product(conn.execute("SELECT * FROM products WHERE id=? AND business_id=?",(pid,user["business_id"])).fetchone(),conn,user["business_id"])

@router.put("/{product_id}")
def update_product(product_id:int,data:ProductIn,user=Depends(require_permission("manage_products")),conn=Depends(get_db)):
    ensure_schema(conn); save(conn,user["business_id"],data,product_id); conn.commit()
    return as_product(conn.execute("SELECT * FROM products WHERE id=? AND business_id=?",(product_id,user["business_id"])).fetchone(),conn,user["business_id"])

@router.post("/{product_id}/deactivate")
def deactivate_product(product_id:int,user=Depends(require_permission("manage_products")),conn=Depends(get_db)):
    ensure_schema(conn)
    cur=conn.execute("UPDATE products SET status='inactive',updated_at=? WHERE id=? AND business_id=?",(now(),product_id,user["business_id"]))
    if not cur.rowcount: raise HTTPException(404,"Product not found.")
    conn.commit(); return {"ok":True,"status":"inactive"}

@router.get("/barcode/{code}")
def barcode_lookup(code:str,user=Depends(require_permission("view_products")),conn=Depends(get_db)):
    ensure_schema(conn); b=user["business_id"]
    row=conn.execute("""SELECT p.* FROM products p LEFT JOIN product_barcodes pb ON pb.product_id=p.id AND pb.business_id=p.business_id WHERE p.business_id=? AND p.status='active' AND (p.barcode=? OR pb.barcode=?) LIMIT 1""",(b,code,code)).fetchone()
    if not row: return {"found":False,"message":"No product matches this barcode. Nothing was saved.","barcode":code}
    return {"found":True,"product":as_product(row,conn,b)}

@router.post("/barcode/attach")
def attach_barcode(payload:dict,user=Depends(require_permission("manage_products")),conn=Depends(get_db)):
    ensure_schema(conn); b=user["business_id"]; code=str(payload.get("barcode","")).strip(); pid=payload.get("product_id")
    if not code or not isinstance(pid,int): raise HTTPException(400,"Choose a product and enter a barcode.")
    if not conn.execute("SELECT id FROM products WHERE id=? AND business_id=?",(pid,b)).fetchone(): raise HTTPException(404,"Product not found.")
    try: conn.execute("INSERT INTO product_barcodes(business_id,product_id,barcode) VALUES(?,?,?)",(b,pid,code)); conn.commit()
    except Exception: raise HTTPException(409,"This barcode is already attached to a product.")
    return {"ok":True}

def parse_gs1(code:str):
    raw=code.strip()
    if raw.startswith("]d2"): raw=raw[3:]
    if not raw.startswith("01") or len(raw)<16 or not raw[2:16].isdigit():
        return {"is_gs1":False,"gtin":None,"batch":None,"expiry":None,"serial":None}
    result={"is_gs1":True,"gtin":raw[2:16],"batch":None,"expiry":None,"serial":None}
    tail=raw[16:].replace("\x1d","|"); i=0
    while i<len(tail):
        if tail[i]=="|": i+=1; continue
        ai=tail[i:i+2]; i+=2
        if ai=="17" and len(tail[i:])>=6 and tail[i:i+6].isdigit():
            value=tail[i:i+6]; i+=6; yy,mm,dd=int(value[:2]),int(value[2:4]),int(value[4:6])
            result["expiry"]=f"{2000+yy:04d}-{mm:02d}-{dd:02d}" if 1<=mm<=12 and 1<=dd<=31 else None
        elif ai in ("10","21"):
            end=tail.find("|",i); value=tail[i:] if end<0 else tail[i:end]
            result["batch" if ai=="10" else "serial"]=value or None
            i=len(tail) if end<0 else end+1
        else: break
    return result

@router.get("/barcode/parse-gs1/{code:path}")
def parse_gs1_route(code:str,user=Depends(require_permission("view_products"))):
    return parse_gs1(code)

@router.get("/import/template")
def template(user=Depends(require_permission("manage_products"))):
    content="name,generic_name,strength,dosage_form,manufacturer,pack_size,barcode,category,purchase_price,wholesale_price,retail_price,mrp,minimum_stock,unit_name,unit_factor,prescription_required,drap_registration_number\nDEMO Sample Product,DEMO generic,10 mg,Tablet,DEMO Manufacturer,10 tablets,DEMO-0001,DEMO,10,12,15,18,5,Tablet,1,false,DEMO-REG\n"
    return StreamingResponse(io.BytesIO(content.encode("utf-8-sig")),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=pharmastock-products-template.csv"})

def validate_import(rows):
    valid=[]; errors=[]; seen=set()
    for num,raw in enumerate(rows,start=2):
        r={str(k or "").strip().lower().replace(" ","_"):("" if v is None else str(v).strip()) for k,v in raw.items()}
        name=r.get("name","")
        if not name: errors.append({"row":num,"error":"Product name is required."}); continue
        try:
            prices={k:float(r.get(k) or 0) for k in ("purchase_price","wholesale_price","retail_price","mrp","minimum_stock")}
            if any(v<0 for v in prices.values()): raise ValueError("Prices and minimum stock cannot be negative.")
            if prices["mrp"]>0 and prices["retail_price"]>prices["mrp"]: raise ValueError("Retail price must not exceed MRP.")
            factor=int(float(r.get("unit_factor") or 1))
            if factor<1 or factor!=float(r.get("unit_factor") or 1): raise ValueError("Unit factor must be a whole number greater than zero.")
        except (ValueError,TypeError) as e:
            errors.append({"row":num,"error":str(e)}); continue
        barcode=r.get("barcode",""); key=("barcode",barcode) if barcode else ("name",name.lower())
        if key in seen: errors.append({"row":num,"error":"Duplicate barcode or product name in this file."}); continue
        seen.add(key)
        valid.append({"name":name,"generic_name":r.get("generic_name",""),"strength":r.get("strength",""),"dosage_form":r.get("dosage_form",""),"manufacturer":r.get("manufacturer",""),"pack_size":r.get("pack_size",""),"barcode":barcode,"category":r.get("category",""),**prices,"status":"active","prescription_required":r.get("prescription_required","").lower() in ("1","true","yes"),"drap_registration_number":r.get("drap_registration_number",""),"units":[{"name":r.get("unit_name") or "Unit","factor":1}],"barcodes":[]})
    return valid,errors

@router.post("/import/preview")
def import_preview(payload:dict,user=Depends(require_permission("manage_products")),conn=Depends(get_db)):
    ensure_schema(conn); rows=payload.get("rows")
    if not isinstance(rows,list): raise HTTPException(400,"Import rows are required.")
    valid,errors=validate_import(rows); b=user["business_id"]
    names={x["name"].lower() for x in conn.execute("SELECT name FROM products WHERE business_id=?",(b,))}
    codes={x["barcode"] for x in conn.execute("SELECT barcode FROM product_barcodes WHERE business_id=?",(b,))}
    codes.update(x["barcode"] for x in conn.execute("SELECT barcode FROM products WHERE business_id=? AND barcode<>''",(b,)))
    new=[]
    for item in valid:
        if item["name"].lower() in names or (item["barcode"] and item["barcode"] in codes):
            errors.append({"row":None,"error":f'Duplicate existing product: {item["name"]}.'})
        else: new.append(item)
    return {"new_count":len(new),"duplicate_count":sum("Duplicate" in e["error"] for e in errors),"error_count":len(errors),"valid_rows":new,"errors":errors}

@router.post("/import/confirm")
def import_confirm(payload:dict,user=Depends(require_permission("manage_products")),conn=Depends(get_db)):
    ensure_schema(conn); rows=payload.get("rows")
    if not isinstance(rows,list): raise HTTPException(400,"Confirm only after preview.")
    b=user["business_id"]
    try:
        # Revalidate database duplicates inside transaction before writing.
        existing_names={x["name"].lower() for x in conn.execute("SELECT name FROM products WHERE business_id=?",(b,))}
        existing_codes={x["barcode"] for x in conn.execute("SELECT barcode FROM products WHERE business_id=? AND barcode<>''",(b,))}
        for row in rows:
            data=ProductIn(**row)
            if data.name.lower() in existing_names or (data.barcode and data.barcode in existing_codes):
                raise HTTPException(409,f"Duplicate product found during confirmation: {data.name}")
            save(conn,b,data); existing_names.add(data.name.lower())
            if data.barcode: existing_codes.add(data.barcode)
        conn.commit()
    except Exception:
        conn.rollback(); raise
    return {"saved_count":len(rows)}

@router.get("/export/{kind}")
def export_products(kind:str,user=Depends(require_permission("view_products")),conn=Depends(get_db)):
    ensure_schema(conn); b=user["business_id"]
    rows=[dict(x) for x in conn.execute("SELECT * FROM products WHERE business_id=? ORDER BY name",(b,))]
    if user["role"]!="owner" and "view_purchase_price" not in user["permissions"]:
        for row in rows: row.pop("purchase_price",None)
    cols=list(rows[0].keys()) if rows else ["name","generic_name","strength","dosage_form","manufacturer","pack_size","barcode","category","wholesale_price","retail_price","mrp","minimum_stock","status","prescription_required","drap_registration_number"]
    output=io.BytesIO()
    if kind=="csv":
        s=io.StringIO(); w=csv.DictWriter(s,fieldnames=cols,extrasaction="ignore"); w.writeheader(); w.writerows(rows); output.write(s.getvalue().encode("utf-8-sig"))
        mime="text/csv"; filename="pharmastock-products.csv"
    elif kind=="xlsx":
        try: from openpyxl import Workbook
        except ImportError: raise HTTPException(500,"Excel export dependency is missing.")
        wb=Workbook(); ws=wb.active; ws.title="Products"; ws.append(cols)
        for row in rows: ws.append([row.get(c) for c in cols])
        wb.save(output); mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"; filename="pharmastock-products.xlsx"
    else: raise HTTPException(400,"Export format must be csv or xlsx.")
    output.seek(0)
    return StreamingResponse(output,media_type=mime,headers={"Content-Disposition":f'attachment; filename="{filename}"'})
