"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ModulePage from "@/components/ModulePage";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Alert, Button, Card, Field, SelectField } from "@/components/ui";
import { newId } from "@/components/sales/Pos";
import { submitOrQueue } from "@/lib/offlineQueue";

type Customer = {
  id: number; name: string; customer_type: "retail" | "wholesale"; phone: string; address: string; licence_number: string;
  credit_allowed: boolean; credit_limit: number; outstanding: number;
};
type Price = { product_id: number; price: number; product_name: string; wholesale_price: number; mrp: number };
type Account = {
  customer: { id: number; name: string };
  outstanding: number; credit_left: number; payment_methods: string[];
  open_invoices: { id: number; invoice_number: string; created_at: string; total: number; paid_amount: number; due_amount: number }[];
  sales: { id: number; invoice_number: string; sale_type: string; created_at: string; total: number; paid_amount: number; due_amount: number; returned_total: number }[];
  payments: { id: number; amount: number; method: string; reference: string; created_at: string; received_by: string | null; applied_to: { invoice_number: string; amount: number }[] }[];
};
type Prod = { id: number; name: string; strength: string; mrp: number };

const blank = { name: "", customer_type: "retail", phone: "", address: "", licence_number: "", credit_allowed: false, credit_limit: "0" };

function CustomersInner() {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const [items, setItems] = useState<Customer[]>([]);
  const [form, setForm] = useState<typeof blank>(blank);
  const [editId, setEditId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [priceFor, setPriceFor] = useState<Customer | null>(null);
  const [prices, setPrices] = useState<Price[]>([]);
  const [psearch, setPsearch] = useState("");
  const [found, setFound] = useState<Prod[]>([]);
  const [pickedId, setPickedId] = useState("");
  const [priceValue, setPriceValue] = useState("");
  const [acc, setAcc] = useState<Account | null>(null);
  const [payAmount, setPayAmount] = useState("");
  const [payMethod, setPayMethod] = useState("");
  const [payRef, setPayRef] = useState("");
  const [paying, setPaying] = useState(false);
  const payUuid = useRef(newId()); // reused if the first try failed, so one payment is never saved twice

  const load = useCallback(async () => {
    try { setItems((await api<{ items: Customer[] }>("/customers")).items); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not load customers."); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function save(e: React.FormEvent) {
    e.preventDefault(); setError(""); setNotice("");
    const body = { ...form, credit_limit: Number(form.credit_limit || 0) };
    try {
      if (editId) await api(`/customers/${editId}`, { method: "PUT", body });
      else await api("/customers", { method: "POST", body });
      setNotice("Customer saved."); setForm(blank); setEditId(null); await load();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not save the customer."); }
  }

  function edit(c: Customer) {
    setEditId(c.id);
    setForm({ name: c.name, customer_type: c.customer_type, phone: c.phone, address: c.address, licence_number: c.licence_number,
      credit_allowed: c.credit_allowed, credit_limit: String(c.credit_limit) });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function openAccount(c: Customer) {
    setError(""); setNotice(""); setPriceFor(null); payUuid.current = newId(); setPayAmount(""); setPayRef("");
    try {
      const a = await api<Account>(`/customers/${c.id}/account`);
      setAcc(a); setPayMethod(a.payment_methods[0] ?? "");
    } catch (err) { setError(err instanceof Error ? err.message : "Could not open the account."); }
  }

  async function receivePayment() {
    if (!acc) return;
    const amount = Number(payAmount);
    if (!(amount > 0)) { setError("Enter the amount received."); return; }
    setPaying(true); setError(""); setNotice("");
    try {
      const out = await submitOrQueue<{ amount: number; outstanding: number; message: string }>(
        "customer_payment", { customer_id: acc.customer.id, amount, method: payMethod, reference: payRef }, payUuid.current, acc.customer.name);
      if (out.queued) {
        setNotice("Server not reachable. The payment is saved on this computer and will be sent automatically.");
      } else {
        const r = out.result;
        setNotice(`${r.message} Received ${r.amount.toFixed(2)}. Still owed: ${r.outstanding.toFixed(2)}.`);
      }
      payUuid.current = newId(); setPayAmount(""); setPayRef("");
      await openAccount({ id: acc.customer.id } as Customer); await load();
    } catch (err) { setError(err instanceof Error ? err.message : "The payment could not be saved."); }
    finally { setPaying(false); }
  }

  async function openPrices(c: Customer) {
    setAcc(null); setPriceFor(c); setError(""); setPsearch(""); setFound([]); setPickedId(""); setPriceValue("");
    try { setPrices((await api<{ items: Price[] }>(`/customers/${c.id}/prices`)).items); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not load prices."); }
  }

  useEffect(() => {
    const q = psearch.trim();
    if (q.length < 2) { setFound([]); return; }
    const t = setTimeout(() => {
      api<{ items: Prod[] }>(`/products?search=${encodeURIComponent(q)}&limit=20`).then((r) => setFound(r.items)).catch(() => setFound([]));
    }, 250);
    return () => clearTimeout(t);
  }, [psearch]);

  async function savePrice() {
    if (!priceFor || !pickedId) { setError("Choose a medicine first."); return; }
    setError("");
    try {
      await api(`/customers/${priceFor.id}/prices`, { method: "PUT", body: { product_id: Number(pickedId), price: Number(priceValue) } });
      setPickedId(""); setPriceValue(""); setPsearch(""); await openPrices(priceFor);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not save the price."); }
  }

  async function removePrice(pid: number) {
    if (!priceFor) return;
    try { await api(`/customers/${priceFor.id}/prices/${pid}`, { method: "DELETE" }); await openPrices(priceFor); }
    catch (err) { setError(err instanceof Error ? err.message : "Could not remove the price."); }
  }

  return (
    <div className="space-y-5">
      {error && <Alert kind="error">{error}</Alert>}
      {notice && <Alert kind="success">{notice}</Alert>}

      <Card>
        <h2 className="mb-4 text-xl font-bold">{editId ? "Edit customer" : "Add customer"}</h2>
        <form onSubmit={save} className="grid gap-4 md:grid-cols-3">
          <Field label="Name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <SelectField label="Type" value={form.customer_type} onChange={(e) => setForm({ ...form, customer_type: e.target.value })}>
            <option value="retail">Retail</option><option value="wholesale">Wholesale</option>
          </SelectField>
          <Field label="Phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          <Field label="Address" value={form.address} onChange={(e) => setForm({ ...form, address: e.target.value })} />
          <Field label="Licence number" value={form.licence_number} onChange={(e) => setForm({ ...form, licence_number: e.target.value })} />
          {isOwner && (
            <>
              <SelectField label="Credit (buy now, pay later)" value={form.credit_allowed ? "yes" : "no"} onChange={(e) => setForm({ ...form, credit_allowed: e.target.value === "yes" })}>
                <option value="no">Not allowed</option><option value="yes">Allowed</option>
              </SelectField>
              <Field label="Credit limit" type="number" min="0" step="0.01" value={form.credit_limit} onChange={(e) => setForm({ ...form, credit_limit: e.target.value })} />
            </>
          )}
          <div className="flex gap-3 md:col-span-3">
            <Button type="submit">Save customer</Button>
            {editId && <Button type="button" variant="secondary" onClick={() => { setEditId(null); setForm(blank); }}>Cancel</Button>}
          </div>
        </form>
      </Card>

      {acc && (
        <Card className="space-y-5 border-2 border-blue-300">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-xl font-bold">Account of {acc.customer.name}</h2>
            <Button type="button" variant="secondary" onClick={() => setAcc(null)}>Close</Button>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-lg bg-slate-50 p-4"><div className="text-slate-600">Customer owes</div><div className="text-3xl font-bold">{acc.outstanding.toFixed(2)}</div></div>
            <div className="rounded-lg bg-slate-50 p-4"><div className="text-slate-600">Credit still available</div><div className="text-3xl font-bold">{acc.credit_left.toFixed(2)}</div></div>
          </div>

          {acc.outstanding > 0 && (
            <div className="space-y-3 rounded-lg border-2 border-green-600 p-4">
              <h3 className="text-lg font-bold">Receive payment</h3>
              <p className="text-sm text-slate-600">The money is put against the oldest unpaid invoice first.</p>
              <div className="grid gap-3 md:grid-cols-4">
                <Field label="Amount received" type="number" min="0" step="0.01" value={payAmount} onChange={(e) => setPayAmount(e.target.value)} />
                <SelectField label="Paid by" value={payMethod} onChange={(e) => setPayMethod(e.target.value)}>
                  {acc.payment_methods.map((m) => <option key={m} value={m}>{m}</option>)}
                </SelectField>
                <Field label="Note (optional)" value={payRef} onChange={(e) => setPayRef(e.target.value)} />
                <div className="flex items-end"><Button type="button" onClick={receivePayment} disabled={paying}>{paying ? "Saving…" : "Save payment"}</Button></div>
              </div>
            </div>
          )}

          <div>
            <h3 className="mb-2 text-lg font-bold">Unpaid invoices (oldest first)</h3>
            <table className="w-full text-left">
              <thead><tr className="border-b bg-slate-50">{["Invoice", "Date", "Total", "Paid", "Unpaid"].map((h) => <th key={h} className="p-3">{h}</th>)}</tr></thead>
              <tbody>
                {acc.open_invoices.map((i) => (
                  <tr key={i.id} className="border-b"><td className="p-3 font-semibold">{i.invoice_number}</td><td className="p-3">{i.created_at.slice(0, 10)}</td>
                    <td className="p-3">{i.total.toFixed(2)}</td><td className="p-3">{i.paid_amount.toFixed(2)}</td><td className="p-3 font-semibold">{i.due_amount.toFixed(2)}</td></tr>
                ))}
                {!acc.open_invoices.length && <tr><td colSpan={5} className="p-4 text-center text-slate-500">No unpaid invoices.</td></tr>}
              </tbody>
            </table>
          </div>

          <div>
            <h3 className="mb-2 text-lg font-bold">Payments received</h3>
            <table className="w-full text-left">
              <thead><tr className="border-b bg-slate-50">{["Date", "Amount", "Paid by", "Put against", "Received by"].map((h) => <th key={h} className="p-3">{h}</th>)}</tr></thead>
              <tbody>
                {acc.payments.map((p) => (
                  <tr key={p.id} className="border-b"><td className="p-3">{p.created_at.replace("T", " ").slice(0, 16)}</td><td className="p-3 font-semibold">{p.amount.toFixed(2)}</td>
                    <td className="p-3">{p.method}{p.reference ? ` (${p.reference})` : ""}</td><td className="p-3">{p.applied_to.map((a) => `${a.invoice_number}: ${a.amount.toFixed(2)}`).join(", ")}</td><td className="p-3">{p.received_by ?? "—"}</td></tr>
                ))}
                {!acc.payments.length && <tr><td colSpan={5} className="p-4 text-center text-slate-500">No payments yet.</td></tr>}
              </tbody>
            </table>
          </div>

          <div>
            <h3 className="mb-2 text-lg font-bold">Sales history</h3>
            <table className="w-full text-left">
              <thead><tr className="border-b bg-slate-50">{["Invoice", "Date", "Type", "Total", "Returned", "Unpaid"].map((h) => <th key={h} className="p-3">{h}</th>)}</tr></thead>
              <tbody>
                {acc.sales.map((i) => (
                  <tr key={i.id} className="border-b"><td className="p-3 font-semibold">{i.invoice_number}</td><td className="p-3">{i.created_at.slice(0, 10)}</td><td className="p-3 capitalize">{i.sale_type}</td>
                    <td className="p-3">{i.total.toFixed(2)}</td><td className="p-3">{i.returned_total.toFixed(2)}</td><td className="p-3">{i.due_amount.toFixed(2)}</td></tr>
                ))}
                {!acc.sales.length && <tr><td colSpan={6} className="p-4 text-center text-slate-500">No sales yet.</td></tr>}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {priceFor && (
        <Card className="space-y-4 border-2 border-blue-300">
          <h2 className="text-xl font-bold">Special wholesale prices for {priceFor.name}</h2>
          <p className="text-sm text-slate-600">The price is for the biggest pack (for example one Box). It cannot be above the MRP.</p>
          <div className="grid gap-3 md:grid-cols-4">
            <Field label="Search medicine" value={psearch} onChange={(e) => setPsearch(e.target.value)} />
            <SelectField label="Medicine" value={pickedId} onChange={(e) => setPickedId(e.target.value)}>
              <option value="">Choose…</option>
              {found.map((p) => <option key={p.id} value={p.id}>{p.name} {p.strength}</option>)}
            </SelectField>
            <Field label="Special price" type="number" min="0" step="0.01" value={priceValue} onChange={(e) => setPriceValue(e.target.value)} />
            <div className="flex items-end gap-2"><Button type="button" onClick={savePrice}>Save price</Button><Button type="button" variant="secondary" onClick={() => setPriceFor(null)}>Close</Button></div>
          </div>
          <table className="w-full text-left">
            <thead><tr className="border-b bg-slate-50">{["Medicine", "Normal wholesale", "Special price", ""].map((h) => <th key={h} className="p-3">{h}</th>)}</tr></thead>
            <tbody>
              {prices.map((p) => (
                <tr key={p.product_id} className="border-b">
                  <td className="p-3">{p.product_name}</td><td className="p-3">{p.wholesale_price.toFixed(2)}</td>
                  <td className="p-3 font-semibold">{p.price.toFixed(2)}</td>
                  <td className="p-3"><button className="font-semibold text-red-700" onClick={() => removePrice(p.product_id)}>Remove</button></td>
                </tr>
              ))}
              {!prices.length && <tr><td colSpan={4} className="p-4 text-center text-slate-500">No special prices yet.</td></tr>}
            </tbody>
          </table>
        </Card>
      )}

      <Card>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[800px] text-left">
            <thead><tr className="border-b bg-slate-50">{["Name", "Type", "Phone", "Credit", "Owes", "Actions"].map((h) => <th key={h} className="p-3">{h}</th>)}</tr></thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id} className="border-b">
                  <td className="p-3 font-semibold">{c.name}</td>
                  <td className="p-3 capitalize">{c.customer_type}</td>
                  <td className="p-3">{c.phone || "—"}</td>
                  <td className="p-3">{c.credit_allowed ? `Limit ${c.credit_limit.toFixed(2)}` : "Not allowed"}</td>
                  <td className="p-3">{c.outstanding.toFixed(2)}</td>
                  <td className="p-3"><div className="flex gap-3">
                    <button className="font-semibold text-blue-700" onClick={() => openAccount(c)}>Account &amp; payments</button>
                    <button className="font-semibold text-blue-700" onClick={() => edit(c)}>Edit</button>
                    <button className="font-semibold text-blue-700" onClick={() => openPrices(c)}>Special prices</button>
                  </div></td>
                </tr>
              ))}
              {!items.length && <tr><td colSpan={6} className="p-6 text-center text-slate-500">No customers yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

export default function CustomersPage() {
  return (
    <ModulePage title="Customers" perm="manage_customers">
      <CustomersInner />
    </ModulePage>
  );
}
