"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { submitOrQueue } from "@/lib/offlineQueue";
import { useAuth } from "@/lib/auth";
import { printSale, type PrintData } from "@/lib/printSale";
import { Alert, Button, Card } from "@/components/ui";

export type Unit = { name: string; factor: number };
export type PosProduct = {
  id: number; name: string; generic_name: string; strength: string; dosage_form: string;
  retail_price: number; wholesale_price: number; mrp: number; prescription_required: boolean;
  units: Unit[]; pack_factor: number; available_base: number; available_text: string; next_expiry: string | null;
};
type Customer = { id: number; name: string; customer_type: string; credit_allowed: boolean; credit_limit: number; outstanding: number };
type Line = { key: string; product: PosProduct; unit_name: string; quantity: string; discount: string };
type SaleResult = { id: number; invoice_number: string; total: number; due_amount: number; duplicate: boolean; message: string };

export function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "id-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 12);
}
const r2 = (n: number) => Math.round((n + Number.EPSILON) * 100) / 100;

export default function Pos() {
  const { can, user } = useAuth();
  const canDiscount = user?.role === "owner" || can("give_discount");
  const isOwner = user?.role === "owner";

  const [mode, setMode] = useState<"retail" | "wholesale">("retail");
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customerId, setCustomerId] = useState("");
  const [custPrices, setCustPrices] = useState<Record<string, number>>({});
  const [methods, setMethods] = useState<string[]>(["Cash"]);
  const [allowNegative, setAllowNegative] = useState(false);

  const [lines, setLines] = useState<Line[]>([]);
  const [scan, setScan] = useState("");
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<PosProduct[]>([]);
  const [invDiscount, setInvDiscount] = useState("0");
  const [method, setMethod] = useState("Cash");
  const [paid, setPaid] = useState("");
  const [notes, setNotes] = useState("");

  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [saving, setSaving] = useState(false);
  const [last, setLast] = useState<SaleResult | null>(null);
  const saleUuid = useRef(newId()); // one id per sale: pressing Save twice can never create two sales
  const scanRef = useRef<HTMLInputElement>(null);

  const loadBasics = useCallback(async () => {
    try {
      const [c, s] = await Promise.all([
        api<{ items: Customer[] }>("/sales/customers"),
        api<{ allow_negative_stock: boolean; payment_methods: string[] }>("/sales/settings"),
      ]);
      setCustomers(c.items);
      setMethods(s.payment_methods);
      setMethod((old) => (s.payment_methods.includes(old) ? old : s.payment_methods[0] ?? "Cash"));
      setAllowNegative(s.allow_negative_stock);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load sales data.");
    }
  }, []);
  useEffect(() => { loadBasics(); }, [loadBasics]);

  useEffect(() => {
    if (!customerId) { setCustPrices({}); return; }
    api<{ prices: Record<string, number> }>(`/sales/customer-prices/${customerId}`)
      .then((r) => setCustPrices(r.prices))
      .catch(() => setCustPrices({}));
  }, [customerId]);

  useEffect(() => {
    const q = search.trim();
    if (q.length < 2) { setResults([]); return; }
    const t = setTimeout(() => {
      api<{ items: PosProduct[] }>(`/sales/products?search=${encodeURIComponent(q)}`)
        .then((r) => setResults(r.items))
        .catch((e) => setError(e instanceof Error ? e.message : "Search failed."));
    }, 250);
    return () => clearTimeout(t);
  }, [search]);

  const customer = customers.find((c) => String(c.id) === customerId);

  function packPrice(p: PosProduct): number {
    if (mode === "retail") return p.retail_price;
    return custPrices[String(p.id)] ?? p.wholesale_price;
  }
  function unitFactor(l: Line): number {
    return l.product.units.find((u) => u.name === l.unit_name)?.factor ?? 1;
  }
  function lineGross(l: Line): number {
    const base = Number(l.quantity || 0) * unitFactor(l);
    return r2((packPrice(l.product) * base) / l.product.pack_factor);
  }
  function lineNet(l: Line): number {
    return r2(lineGross(l) - Number(l.discount || 0));
  }

  const subtotal = r2(lines.reduce((s, l) => s + lineNet(l), 0));
  const total = r2(subtotal - Number(invDiscount || 0));
  const paidNow = paid === "" ? total : Number(paid);
  const due = r2(total - paidNow);

  function addProduct(p: PosProduct) {
    setError(""); setInfo(""); setLast(null);
    const unit = mode === "retail" ? p.units[0]?.name : p.units[p.units.length - 1]?.name; // retail: smallest, wholesale: biggest
    setLines((old) => {
      const same = old.find((l) => l.product.id === p.id && l.unit_name === unit);
      if (same) return old.map((l) => (l === same ? { ...l, quantity: String(Number(l.quantity || 0) + 1) } : l));
      return [...old, { key: newId(), product: p, unit_name: unit ?? "", quantity: "1", discount: "0" }];
    });
    setSearch(""); setResults([]);
    scanRef.current?.focus();
  }

  async function doScan() {
    const code = scan.trim();
    if (!code) return;
    setScan(""); setError(""); setInfo("");
    try {
      const r = await api<{ found: boolean; message?: string; product?: PosProduct; gs1?: { batch: string | null; expiry: string | null } | null }>(
        `/sales/scan/${encodeURIComponent(code)}`);
      if (!r.found || !r.product) { setError(r.message ?? "Medicine not found."); return; }
      addProduct(r.product);
      if (r.gs1?.batch || r.gs1?.expiry)
        setInfo(`Scanned batch ${r.gs1.batch ?? "-"}, expiry ${r.gs1.expiry ?? "-"}. The system will sell the earliest-expiry batch first.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scan failed.");
    }
  }

  function setLine(key: string, patch: Partial<Line>) {
    setLines((old) => old.map((l) => (l.key === key ? { ...l, ...patch } : l)));
  }

  function reset() {
    setLines([]); setInvDiscount("0"); setPaid(""); setNotes(""); setCustomerId("");
    saleUuid.current = newId();
  }

  async function save() {
    setError(""); setInfo(""); setLast(null);
    if (!lines.length) { setError("Add at least one medicine."); return; }
    if (mode === "wholesale" && !customerId) { setError("Choose a customer for a wholesale sale."); return; }
    setSaving(true);
    try {
      const out = await submitOrQueue<SaleResult>("sale", {
        sale_type: mode,
        customer_id: customerId ? Number(customerId) : null,
        lines: lines.map((l) => ({ product_id: l.product.id, unit_name: l.unit_name, quantity: Number(l.quantity), discount: Number(l.discount || 0) })),
        discount: Number(invDiscount || 0),
        payment_method: method,
        paid_amount: paid === "" ? null : Number(paid),
        notes,
      }, saleUuid.current, mode);
      if (out.queued) {
        setInfo("Server not reachable. The sale is saved on this computer and will be sent automatically. Stock is checked when it is sent.");
        reset();
        return;
      }
      const res = out.result;
      setLast(res);
      setInfo(res.message);
      reset();
      loadBasics();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The sale could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  async function printLast(layout: "a4" | "receipt") {
    if (!last) return;
    try {
      printSale(await api<PrintData>(`/sales/${last.id}/print`), layout);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not prepare the invoice.");
    }
  }

  async function toggleNegative() {
    try {
      const r = await api<{ allow_negative_stock: boolean }>("/sales/settings", { method: "PUT", body: { allow_negative_stock: !allowNegative } });
      setAllowNegative(r.allow_negative_stock);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not change the setting.");
    }
  }

  const modeBtn = (m: "retail" | "wholesale", label: string) => (
    <button
      type="button"
      onClick={() => { setMode(m); setLines([]); setLast(null); }}
      className={`flex-1 rounded-xl px-6 py-5 text-2xl font-bold transition ${mode === m ? "bg-blue-700 text-white" : "border-2 border-blue-700 bg-white text-blue-700 hover:bg-blue-50"}`}
    >
      {label}
    </button>
  );

  return (
    <div className="space-y-5">
      <div className="flex gap-4">{modeBtn("retail", "Retail Sale")}{modeBtn("wholesale", "Wholesale Sale")}</div>

      {error && <Alert kind="error">{error}</Alert>}
      {info && <Alert kind="success">{info}</Alert>}
      {last && (
        <Card className="flex flex-wrap items-center gap-3">
          <div className="text-lg font-semibold">Invoice {last.invoice_number} — total {last.total.toFixed(2)}{last.due_amount > 0 ? `, balance due ${last.due_amount.toFixed(2)}` : ""}</div>
          <Button type="button" variant="secondary" onClick={() => printLast("a4")}>Print A4 invoice</Button>
          <Button type="button" variant="secondary" onClick={() => printLast("receipt")}>Print small receipt</Button>
        </Card>
      )}

      <Card className="space-y-4">
        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label className="mb-1 block text-base font-semibold">Scan medicine (scanner types here)</label>
            <input
              ref={scanRef} autoFocus value={scan} onChange={(e) => setScan(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); doScan(); } }}
              placeholder="Click here, then scan the barcode"
              className="w-full rounded-lg border-2 border-slate-300 px-4 py-3 text-lg focus:border-blue-600 focus:outline-none"
            />
          </div>
          <div className="relative">
            <label className="mb-1 block text-base font-semibold">Or search by name</label>
            <input
              value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Type at least 2 letters"
              className="w-full rounded-lg border-2 border-slate-300 px-4 py-3 text-lg focus:border-blue-600 focus:outline-none"
            />
            {results.length > 0 && (
              <div className="absolute z-10 mt-1 max-h-80 w-full overflow-y-auto rounded-lg border-2 border-slate-300 bg-white shadow-lg">
                {results.map((p) => (
                  <button key={p.id} type="button" onClick={() => addProduct(p)} className="block w-full border-b px-4 py-3 text-left hover:bg-blue-50">
                    <div className="font-semibold">{p.name} {p.strength}</div>
                    <div className="text-sm text-slate-600">In stock: {p.available_text || "0"}{p.next_expiry ? ` · earliest expiry ${p.next_expiry}` : ""}</div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label className="mb-1 block text-base font-semibold">Customer {mode === "wholesale" ? "(required)" : "(optional for retail)"}</label>
            <select value={customerId} onChange={(e) => setCustomerId(e.target.value)} className="w-full rounded-lg border-2 border-slate-300 bg-white px-4 py-3 text-lg">
              <option value="">{mode === "retail" ? "Walk-in customer" : "Choose customer"}</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            {customer && (
              <p className="mt-1 text-sm text-slate-600">
                Owes {customer.outstanding.toFixed(2)}. {customer.credit_allowed ? `Credit limit ${customer.credit_limit.toFixed(2)}.` : "Credit not allowed."}
              </p>
            )}
          </div>
        </div>
      </Card>

      <Card>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-left">
            <thead>
              <tr className="border-b bg-slate-50">
                {["Medicine", "Unit", "Quantity", "Price / unit", ...(canDiscount ? ["Discount"] : []), "Total", ""].map((h) => <th key={h} className="p-3">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => {
                const f = unitFactor(l);
                const perUnit = (packPrice(l.product) * f) / l.product.pack_factor;
                return (
                  <tr key={l.key} className="border-b align-top">
                    <td className="p-3">
                      <div className="font-semibold">{l.product.name} {l.product.strength}</div>
                      <div className="text-sm text-slate-500">In stock: {l.product.available_text || "0"}</div>
                      {l.product.prescription_required && <div className="text-sm font-semibold text-red-700">Prescription required</div>}
                    </td>
                    <td className="p-3">
                      <select value={l.unit_name} onChange={(e) => setLine(l.key, { unit_name: e.target.value })} className="rounded-lg border-2 border-slate-300 bg-white px-3 py-2 text-lg">
                        {l.product.units.map((u) => <option key={u.name} value={u.name}>{u.name}</option>)}
                      </select>
                    </td>
                    <td className="p-3">
                      <input type="number" min="1" step="1" value={l.quantity} onChange={(e) => setLine(l.key, { quantity: e.target.value })} className="w-24 rounded-lg border-2 border-slate-300 px-3 py-2 text-lg" />
                    </td>
                    <td className="p-3 text-lg">{perUnit.toFixed(2)}</td>
                    {canDiscount && (
                      <td className="p-3"><input type="number" min="0" step="0.01" value={l.discount} onChange={(e) => setLine(l.key, { discount: e.target.value })} className="w-28 rounded-lg border-2 border-slate-300 px-3 py-2 text-lg" /></td>
                    )}
                    <td className="p-3 text-lg font-semibold">{lineNet(l).toFixed(2)}</td>
                    <td className="p-3"><button type="button" onClick={() => setLines((o) => o.filter((x) => x.key !== l.key))} className="font-semibold text-red-700">Remove</button></td>
                  </tr>
                );
              })}
              {!lines.length && <tr><td colSpan={7} className="p-6 text-center text-lg text-slate-500">Scan or search a medicine to start the sale.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="grid gap-4 md:grid-cols-4">
        {canDiscount && (
          <div>
            <label className="mb-1 block text-base font-semibold">Extra discount</label>
            <input type="number" min="0" step="0.01" value={invDiscount} onChange={(e) => setInvDiscount(e.target.value)} className="w-full rounded-lg border-2 border-slate-300 px-4 py-3 text-lg" />
          </div>
        )}
        <div>
          <label className="mb-1 block text-base font-semibold">Payment method</label>
          <select value={method} onChange={(e) => setMethod(e.target.value)} className="w-full rounded-lg border-2 border-slate-300 bg-white px-4 py-3 text-lg">
            {methods.map((m) => <option key={m}>{m}</option>)}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-base font-semibold">Amount paid now</label>
          <input type="number" min="0" step="0.01" value={paid} onChange={(e) => setPaid(e.target.value)} placeholder={`Full: ${total.toFixed(2)}`} className="w-full rounded-lg border-2 border-slate-300 px-4 py-3 text-lg" />
          <p className="mt-1 text-sm text-slate-500">Leave empty if the customer pays everything. Less than the total = credit sale.</p>
        </div>
        <div className="rounded-lg bg-blue-50 p-3">
          <div className="text-sm">Total to pay</div>
          <div className="text-3xl font-bold text-blue-900">{total.toFixed(2)}</div>
          {due > 0.004 && <div className="text-sm font-semibold text-red-700">Credit: {due.toFixed(2)}</div>}
        </div>
        <div className="md:col-span-4">
          <label className="mb-1 block text-base font-semibold">Note (optional)</label>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={300} className="w-full rounded-lg border-2 border-slate-300 px-4 py-3 text-lg" />
        </div>
        <div className="md:col-span-4 flex flex-wrap gap-3">
          <Button type="button" onClick={save} disabled={saving || !lines.length} className="px-10 py-4 text-xl">{saving ? "Saving…" : "Save sale"}</Button>
          <Button type="button" variant="secondary" onClick={reset} disabled={saving}>Clear</Button>
        </div>
      </Card>

      {isOwner && (
        <Card className="flex flex-wrap items-center gap-4">
          <div className="flex-1">
            <div className="text-lg font-semibold">Allow selling more than the stock (exception)</div>
            <div className="text-sm text-slate-600">Normally OFF. When ON, a sale can make a batch negative. Use only for a short time and fix the stock afterwards.</div>
          </div>
          <Button type="button" variant={allowNegative ? "danger" : "secondary"} onClick={toggleNegative}>{allowNegative ? "ON — click to turn off" : "OFF — click to turn on"}</Button>
        </Card>
      )}
    </div>
  );
}
