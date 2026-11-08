"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { printSale, type PrintData } from "@/lib/printSale";
import { Alert, Button, Card } from "@/components/ui";
import { newId, type Unit } from "./Pos";

type Row = {
  id: number; invoice_number: string; sale_type: string; total: number; paid_amount: number; due_amount: number;
  returned_total: number; payment_method: string; created_at: string; customer_name: string | null; sold_by: string | null;
};
type Detail = {
  sale: { id: number; invoice_number: string; total: number; due_amount: number; returned_total: number };
  items: { id: number; product_id: number; product_name: string; strength: string; unit_name: string; quantity: number; base_quantity: number; returned_base: number; net_total: number }[];
  returns: { id: number; action: string; reason: string; total: number; refund_amount: number; created_at: string }[];
};

export default function History() {
  const [rows, setRows] = useState<Row[]>([]);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [qty, setQty] = useState<Record<number, string>>({});
  const [unitFor, setUnitFor] = useState<Record<number, string>>({});
  const [unitsFor, setUnitsFor] = useState<Record<number, Unit[]>>({});
  const [action, setAction] = useState<"restock" | "write_off">("restock");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const returnUuid = useRef(newId()); // same id is reused if the first try failed, so a return is never saved twice

  const load = useCallback(async () => {
    try {
      const r = await api<{ items: Row[] }>(`/sales?search=${encodeURIComponent(search.trim())}`);
      setRows(r.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load sales.");
    }
  }, [search]);
  useEffect(() => { load(); }, [load]);

  async function print(id: number, layout: "a4" | "receipt") {
    try {
      printSale(await api<PrintData>(`/sales/${id}/print`), layout);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not prepare the invoice.");
    }
  }

  async function openReturn(id: number) {
    setError(""); setNotice(""); setQty({}); setReason(""); setAction("restock");
    returnUuid.current = newId();
    try {
      const d = await api<Detail>(`/sales/${id}`);
      setDetail(d);
      const units: Record<number, Unit[]> = {}; const chosen: Record<number, string> = {};
      for (const it of d.items) {
        const found = await api<{ items: { id: number; units: Unit[] }[] }>(`/sales/products?search=${encodeURIComponent(it.product_name)}`);
        const u = found.items.find((p) => p.id === it.product_id)?.units ?? [{ name: it.unit_name, factor: 1 }];
        units[it.id] = u; chosen[it.id] = u[0]?.name ?? it.unit_name;
      }
      setUnitsFor(units); setUnitFor(chosen);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not open the sale.");
    }
  }

  async function submitReturn() {
    if (!detail) return;
    const lines = detail.items
      .filter((it) => Number(qty[it.id] || 0) > 0)
      .map((it) => ({ sale_item_id: it.id, unit_name: unitFor[it.id], quantity: Number(qty[it.id]) }));
    if (!lines.length) { setError("Enter the quantity to return for at least one medicine."); return; }
    setSaving(true); setError("");
    try {
      const r = await api<{ total: number; due_reduced: number; refund_amount: number; message: string }>(
        `/sales/${detail.sale.id}/returns`,
        { method: "POST", body: { client_uuid: returnUuid.current, action, reason, lines } });
      setNotice(`Return saved: ${r.total.toFixed(2)}. Customer balance reduced by ${r.due_reduced.toFixed(2)}; money to give back: ${r.refund_amount.toFixed(2)}.`);
      setDetail(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The return could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-5">
      {error && <Alert kind="error">{error}</Alert>}
      {notice && <Alert kind="success">{notice}</Alert>}

      {detail && (
        <Card className="space-y-4 border-2 border-blue-300">
          <h2 className="text-2xl font-bold">Return from {detail.sale.invoice_number}</h2>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left">
              <thead><tr className="border-b bg-slate-50">{["Medicine", "Sold", "Already returned", "Return now", "Unit"].map((h) => <th key={h} className="p-3">{h}</th>)}</tr></thead>
              <tbody>
                {detail.items.map((it) => (
                  <tr key={it.id} className="border-b">
                    <td className="p-3 font-semibold">{it.product_name} {it.strength}</td>
                    <td className="p-3">{it.quantity} {it.unit_name}</td>
                    <td className="p-3">{it.returned_base} (smallest units)</td>
                    <td className="p-3"><input type="number" min="0" step="1" value={qty[it.id] ?? ""} onChange={(e) => setQty({ ...qty, [it.id]: e.target.value })} className="w-24 rounded-lg border-2 border-slate-300 px-3 py-2 text-lg" /></td>
                    <td className="p-3">
                      <select value={unitFor[it.id] ?? ""} onChange={(e) => setUnitFor({ ...unitFor, [it.id]: e.target.value })} className="rounded-lg border-2 border-slate-300 bg-white px-3 py-2 text-lg">
                        {(unitsFor[it.id] ?? []).map((u) => <option key={u.name}>{u.name}</option>)}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="mb-1 block text-base font-semibold">What happens to the medicine?</label>
              <select value={action} onChange={(e) => setAction(e.target.value as "restock" | "write_off")} className="w-full rounded-lg border-2 border-slate-300 bg-white px-4 py-3 text-lg">
                <option value="restock">Put back in stock (same batch)</option>
                <option value="write_off">Write off (damaged / cannot be sold)</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-base font-semibold">Reason (required)</label>
              <input value={reason} onChange={(e) => setReason(e.target.value)} className="w-full rounded-lg border-2 border-slate-300 px-4 py-3 text-lg" />
            </div>
          </div>
          <div className="flex gap-3">
            <Button type="button" onClick={submitReturn} disabled={saving || reason.trim().length < 3}>{saving ? "Saving…" : "Save return"}</Button>
            <Button type="button" variant="secondary" onClick={() => setDetail(null)}>Cancel</Button>
          </div>
        </Card>
      )}

      <Card>
        <div className="mb-3 flex gap-3">
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search invoice number or customer" className="w-full max-w-md rounded-lg border-2 border-slate-300 px-4 py-3 text-lg" />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] text-left">
            <thead><tr className="border-b bg-slate-50">{["Invoice", "Date", "Type", "Customer", "Total", "Due", "Returned", "Actions"].map((h) => <th key={h} className="p-3">{h}</th>)}</tr></thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id} className="border-b">
                  <td className="p-3 font-semibold">{s.invoice_number}</td>
                  <td className="p-3">{s.created_at.replace("T", " ").slice(0, 16)}</td>
                  <td className="p-3 capitalize">{s.sale_type}</td>
                  <td className="p-3">{s.customer_name ?? "Walk-in"}</td>
                  <td className="p-3">{s.total.toFixed(2)}</td>
                  <td className="p-3">{s.due_amount.toFixed(2)}</td>
                  <td className="p-3">{s.returned_total.toFixed(2)}</td>
                  <td className="p-3">
                    <div className="flex flex-wrap gap-3">
                      <button className="font-semibold text-blue-700" onClick={() => print(s.id, "a4")}>A4</button>
                      <button className="font-semibold text-blue-700" onClick={() => print(s.id, "receipt")}>Receipt</button>
                      <button className="font-semibold text-red-700" onClick={() => openReturn(s.id)}>Return</button>
                    </div>
                  </td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan={8} className="p-6 text-center text-slate-500">No sales yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
