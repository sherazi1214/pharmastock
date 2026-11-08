"use client";

import { ChangeEvent, FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, getToken } from "@/lib/api";
import { Alert, Button, Card, PageTitle } from "@/components/ui";
import { useAuth } from "@/lib/auth";

type Unit = { name: string; factor: number };
type Product = {
  id: number; name: string; generic_name: string; strength: string; dosage_form: string;
  manufacturer: string; pack_size: string; barcode: string; category: string;
  purchase_price?: number; wholesale_price: number; retail_price: number; mrp: number;
  minimum_stock: number; status: string; prescription_required: boolean;
  drap_registration_number: string; units: Unit[]; barcodes: string[];
};
type FormProduct = Omit<Product, "id">;
type ImportPreview = { new_count: number; duplicate_count: number; error_count: number; valid_rows: FormProduct[]; errors: {row:number|null;error:string}[] };
const blank: FormProduct = {
  name:"",generic_name:"",strength:"",dosage_form:"",manufacturer:"",pack_size:"",barcode:"",category:"",
  purchase_price:0,wholesale_price:0,retail_price:0,mrp:0,minimum_stock:0,status:"active",
  prescription_required:false,drap_registration_number:"",units:[{name:"Tablet",factor:1}],barcodes:[]
};
const columns = ["name","generic_name","strength","dosage_form","manufacturer","pack_size","barcode","category","purchase_price","wholesale_price","retail_price","mrp","minimum_stock","unit_name","unit_factor","prescription_required","drap_registration_number"];
function parseCsv(text:string): Record<string,string>[] {
  const rows:string[][]=[]; let row:string[]=[], field="", quoted=false;
  for(let i=0;i<text.length;i++){ const c=text[i];
    if(c==='"' && quoted && text[i+1]==='"'){field+='"';i++;}
    else if(c==='"'){quoted=!quoted;}
    else if(c==="," && !quoted){row.push(field);field="";}
    else if((c==="\n"||c==="\r")&&!quoted){if(c==="\r"&&text[i+1]==="\n")i++;row.push(field);if(row.some(x=>x.trim()))rows.push(row);row=[];field="";}
    else field+=c;
  }
  if(field.length||row.length){row.push(field);rows.push(row);}
  if(!rows.length)return [];
  const heads=rows.shift()!.map(x=>x.trim().toLowerCase().replaceAll(" ","_"));
  return rows.map(r=>Object.fromEntries(heads.map((h,i)=>[h,(r[i]??"").trim()])));
}
function toForm(p:Product):FormProduct { const {id,...rest}=p; return {...rest,units:p.units?.length?p.units:[{name:"Unit",factor:1}],barcodes:p.barcodes??[]}; }
function download(path:string){ const a=document.createElement("a");a.href=path;a.click(); }

export default function ProductsPage(){
  const {user,can}=useAuth();
  const canManage=user?.role==="owner"||can("manage_products");
  const canCost=user?.role==="owner"||can("view_purchase_price");
  const [items,setItems]=useState<Product[]>([]),[total,setTotal]=useState(0),[search,setSearch]=useState("");
  const [busy,setBusy]=useState(false),[error,setError]=useState(""),[notice,setNotice]=useState("");
  const [editing,setEditing]=useState<number|null>(null),[form,setForm]=useState<FormProduct>(blank);
  const [showForm,setShowForm]=useState(false),[scan,setScan]=useState(""),[scanResult,setScanResult]=useState("");
  const [preview,setPreview]=useState<ImportPreview|null>(null),[importBusy,setImportBusy]=useState(false);
  const fileRef=useRef<HTMLInputElement>(null),scanRef=useRef<HTMLInputElement>(null);
  const load=useCallback(async()=>{setBusy(true);setError("");try{const r=await api<{items:Product[];total:number}>(`/products?search=${encodeURIComponent(search)}&limit=100`);setItems(r.items);setTotal(r.total);}catch(e){setError(e instanceof Error?e.message:"Could not load products.");}finally{setBusy(false);}},[search]);
  useEffect(()=>{load();},[load]);
  function startNew(){setEditing(null);setForm({...blank,units:[{name:"Tablet",factor:1}]});setShowForm(true);setNotice("");setError("");}
  function edit(p:Product){setEditing(p.id);setForm(toForm(p));setShowForm(true);setNotice("");setError("");}
  function field<K extends keyof FormProduct>(key:K,value:FormProduct[K]){setForm(old=>({...old,[key]:value}));}
  async function save(e:FormEvent){e.preventDefault();setError("");setNotice("");
    if(form.retail_price>form.mrp){setError("Retail price must not exceed MRP.");return;}
    try{const payload={...form,name:form.name.trim(),units:form.units.map(u=>({name:u.name.trim(),factor:Number(u.factor)}))};
      await api(editing?`/products/${editing}`:"/products",{method:editing?"PUT":"POST",body:payload});
      setShowForm(false);setNotice(editing?"Product updated.":"Product saved.");await load();
    }catch(err){setError(err instanceof Error?err.message:"Could not save product.");}
  }
  async function deactivate(p:Product){if(!confirm(`Deactivate ${p.name}?`))return;try{await api(`/products/${p.id}/deactivate`,{method:"POST"});setNotice("Product deactivated.");await load();}catch(e){setError(e instanceof Error?e.message:"Could not deactivate product.");}}
  async function lookup(e?:FormEvent){e?.preventDefault();const code=scan.trim();if(!code)return;setError("");setNotice("");setScanResult("");
    try{const r=await api<{found:boolean;message?:string;product?:Product}>(`/products/barcode/${encodeURIComponent(code)}`);
      if(r.found&&r.product){setScanResult(`Found: ${r.product.name} — ${r.product.strength||"no strength entered"}`);setSearch(code);setItems([r.product]);setTotal(1);}
      else setScanResult(r.message||"No product found. Nothing was saved.");
    }catch(e){setError(e instanceof Error?e.message:"Barcode lookup failed.");}
  }
  async function importFile(e:ChangeEvent<HTMLInputElement>){const file=e.target.files?.[0];if(!file)return;setError("");setNotice("");setPreview(null);setImportBusy(true);
    try{const text=await file.text();let rows:Record<string,string>[];
      if(file.name.toLowerCase().endsWith(".csv")) rows=parseCsv(text.replace(/^\uFEFF/,""));
      else {setError("For this version, save the Excel sheet as CSV first, then upload it.");return;}
      if(!rows.length){setError("The file has no product rows.");return;}
      const r=await api<ImportPreview>("/products/import/preview",{method:"POST",body:{rows}});setPreview(r);
    }catch(e){setError(e instanceof Error?e.message:"Could not preview the file.");}
    finally{setImportBusy(false);if(fileRef.current)fileRef.current.value="";}
  }
  async function confirmImport(){if(!preview||!preview.valid_rows.length)return;setImportBusy(true);setError("");setNotice("");
    try{const r=await api<{saved_count:number}>("/products/import/confirm",{method:"POST",body:{rows:preview.valid_rows}});setNotice(`${r.saved_count} products imported.`);setPreview(null);await load();}
    catch(e){setError(e instanceof Error?e.message:"Import failed.");}finally{setImportBusy(false);}
  }
  return <div className="space-y-5">
    <PageTitle>Products</PageTitle>
    <p className="text-slate-600">Add medicines, manage prices, import a product list, or scan a barcode. Enter only medicine details you have verified.</p>
    {error&&<Alert kind="error">{error}</Alert>}{notice&&<Alert kind="success">{notice}</Alert>}
    <Card><div className="grid gap-3 md:grid-cols-[1fr_auto]">
      <form onSubmit={lookup} className="flex gap-2"><input ref={scanRef} value={scan} onChange={e=>setScan(e.target.value)} onKeyDown={e=>{if(e.key==="Enter"){e.preventDefault();lookup();}}} placeholder="Scan barcode, then press Enter" className="min-w-0 flex-1 rounded-lg border border-slate-300 px-4 py-3 text-lg"/><Button type="submit">Find barcode</Button></form>
      <div className="flex flex-wrap gap-2"><Button onClick={()=>download("/api/products/import/template")}>CSV template</Button><Button onClick={()=>download("/api/products/export/csv")}>Export CSV</Button><Button onClick={()=>download("/api/products/export/xlsx")}>Export Excel</Button></div>
    </div>
    {scanResult&&<p className="mt-3 rounded-lg bg-blue-50 p-3 font-medium text-blue-900">{scanResult}</p>}</Card>
    <Card><div className="flex flex-col gap-3 sm:flex-row"><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search name, generic, manufacturer or barcode" className="min-w-0 flex-1 rounded-lg border border-slate-300 px-4 py-3"/>{canManage&&<><Button onClick={startNew}>+ Add product</Button><Button onClick={()=>fileRef.current?.click()}>{importBusy?"Working…":"Import CSV"}</Button><input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden" onChange={importFile}/></>}</div>
      <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[850px] text-left text-sm"><thead><tr className="border-b bg-slate-50 text-slate-700">{["Product","Strength / Form","Manufacturer","Barcode","Retail","MRP","Status",...(canCost?["Purchase"]:[]),"Actions"].map(x=><th key={x} className="p-3">{x}</th>)}</tr></thead><tbody>
      {items.map(p=><tr key={p.id} className="border-b last:border-0"><td className="p-3"><div className="font-semibold">{p.name}</div><div className="text-slate-500">{p.generic_name}</div></td><td className="p-3">{[p.strength,p.dosage_form].filter(Boolean).join(" · ")||"—"}</td><td className="p-3">{p.manufacturer||"—"}</td><td className="p-3">{p.barcode||"—"}</td><td className="p-3">{p.retail_price.toFixed(2)}</td><td className="p-3">{p.mrp.toFixed(2)}</td><td className="p-3"><span className={p.status==="active"?"text-green-700":"text-slate-500"}>{p.status}</span></td>{canCost&&<td className="p-3">{p.purchase_price===undefined?"—":p.purchase_price.toFixed(2)}</td>}<td className="p-3"><div className="flex gap-2">{canManage&&<><button onClick={()=>edit(p)} className="font-semibold text-blue-700">Edit</button>{p.status==="active"&&<button onClick={()=>deactivate(p)} className="font-semibold text-red-700">Deactivate</button>}</>}</div></td></tr>)}
      {!items.length&&<tr><td colSpan={canCost?9:8} className="p-8 text-center text-slate-500">{busy?"Loading products…":"No products found. Add a product or import a CSV file."}</td></tr>}
      </tbody></table></div><p className="mt-3 text-sm text-slate-500">Showing {items.length} of {total} products.</p>
    </Card>
    {preview&&<Card><h2 className="text-xl font-bold">Import preview</h2><div className="my-3 grid gap-3 sm:grid-cols-3"><div className="rounded-lg bg-green-50 p-4"><div className="text-sm">New products</div><div className="text-2xl font-bold">{preview.new_count}</div></div><div className="rounded-lg bg-amber-50 p-4"><div className="text-sm">Duplicates</div><div className="text-2xl font-bold">{preview.duplicate_count}</div></div><div className="rounded-lg bg-red-50 p-4"><div className="text-sm">Errors</div><div className="text-2xl font-bold">{preview.error_count}</div></div></div>
      {preview.errors.length>0&&<div className="mb-4 max-h-48 overflow-auto rounded border border-red-200 p-3"><h3 className="font-semibold">Rows needing attention</h3>{preview.errors.map((x,i)=><p key={i} className="text-sm text-red-700">Row {x.row??"—"}: {x.error}</p>)}</div>}
      <p className="mb-3 text-sm text-slate-600">Only the valid new rows below will be saved. Errors and duplicates are skipped; nothing is saved until you confirm.</p><div className="flex gap-2"><Button disabled={!preview.valid_rows.length||importBusy} onClick={confirmImport}>{importBusy?"Saving…":`Confirm import (${preview.new_count})`}</Button><Button onClick={()=>setPreview(null)}>Cancel</Button></div>
    </Card>}
    {showForm&&<div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/40 p-4"><div className="mx-auto my-6 max-w-4xl rounded-xl bg-white p-6 shadow-xl"><div className="mb-4 flex items-center justify-between"><h2 className="text-2xl font-bold">{editing?"Edit product":"Add product"}</h2><button onClick={()=>setShowForm(false)} className="text-2xl" aria-label="Close">×</button></div>
      <form onSubmit={save} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {([
        ["name","Product name","text"],["generic_name","Generic name","text"],["strength","Strength (e.g. 10 mg)","text"],["dosage_form","Dosage form","text"],["manufacturer","Manufacturer","text"],["pack_size","Pack size","text"],["barcode","Main barcode","text"],["category","Category","text"],["drap_registration_number","DRAP registration number (optional)","text"],["purchase_price","Purchase price","number"],["wholesale_price","Wholesale price","number"],["retail_price","Retail price","number"],["mrp","MRP","number"],["minimum_stock","Minimum stock","number"]
      ] as [keyof FormProduct,string,string][]).filter(([key])=>key!=="purchase_price"||canCost).map(([key,label,type])=><label key={key} className="block text-sm font-medium text-slate-700">{label}<input required={key==="name"} type={type} min={type==="number"?0:undefined} step={type==="number"?"0.01":undefined} value={String(form[key]??"")} onChange={e=>field(key,(type==="number"?Number(e.target.value):e.target.value) as never)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-base"/></label>)}
      <label className="flex items-center gap-2 self-center"><input type="checkbox" checked={form.prescription_required} onChange={e=>field("prescription_required",e.target.checked)}/> Prescription required</label>
      <label className="block text-sm font-medium">Status<select value={form.status} onChange={e=>field("status",e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2"><option value="active">Active</option><option value="inactive">Inactive</option></select></label>
      <div className="sm:col-span-2 lg:col-span-3 rounded-lg border p-3"><h3 className="mb-2 font-semibold">Units (smallest unit must equal 1)</h3>{form.units.map((u,i)=><div key={i} className="mb-2 flex gap-2"><input aria-label="Unit name" value={u.name} onChange={e=>field("units",form.units.map((x,j)=>j===i?{...x,name:e.target.value}:x))} placeholder="e.g. Tablet, Strip, Box" className="flex-1 rounded border px-3 py-2"/><input aria-label="Unit factor" type="number" min="1" step="1" value={u.factor} onChange={e=>field("units",form.units.map((x,j)=>j===i?{...x,factor:Number(e.target.value)}:x))} className="w-28 rounded border px-3 py-2"/>{form.units.length>1&&<button type="button" onClick={()=>field("units",form.units.filter((_,j)=>j!==i))} className="text-red-700">Remove</button>}</div>)}<Button type="button" onClick={()=>field("units",[...form.units,{name:"",factor:1}])}>+ Add unit</Button><p className="mt-2 text-xs text-slate-500">Example: Tablet = 1, Strip = 10, Box = 100. Every larger factor must be a whole multiple of the preceding factor.</p></div>
      <div className="flex gap-2 sm:col-span-2 lg:col-span-3"><Button type="submit">{editing?"Save changes":"Save product"}</Button><Button type="button" onClick={()=>setShowForm(false)}>Cancel</Button></div>
      </form>
    </div></div>}
  </div>;
}
