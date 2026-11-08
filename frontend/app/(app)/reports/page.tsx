"use client";

import { useCallback, useEffect, useState } from "react";
import ModulePage from "@/components/ModulePage";
import { api } from "@/lib/api";
import { Alert, Button, Card, Field } from "@/components/ui";
import { downloadReport, fmt, printReport, type Report } from "@/lib/reportTools";

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const NEEDS_DATES = ["daily_sales", "monthly_sales", "purchase_history", "best_selling", "profit"];

function ReportsInner() {
  const now = new Date();
  const [list, setList] = useState<{ name: string; title: string }[]>([]);
  const [name, setName] = useState("daily_sales");
  const [from, setFrom] = useState(iso(new Date(now.getFullYear(), now.getMonth(), 1)));
  const [to, setTo] = useState(iso(now));
  const [rep, setRep] = useState<Report | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<{ items: { name: string; title: string }[] }>("/reports").then((r) => setList(r.items)).catch((e) => setError(e instanceof Error ? e.message : "Could not load the report list."));
  }, []);

  const open = useCallback(async (n: string, f: string, t: string) => {
    setError(""); setBusy(true);
    try { setRep(await api<Report>(`/reports/${n}?from=${f}&to=${t}`)); }
    catch (e) { setRep(null); setError(e instanceof Error ? e.message : "Could not open the report."); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => { open(name, from, to); }, [name]); // eslint-disable-line react-hooks/exhaustive-deps

  async function save(format: "csv" | "xlsx") {
    setError("");
    try { await downloadReport(name, format, from, to); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not create the file."); }
  }

  return (
    <div className="space-y-5">
      {error && <Alert kind="error">{error}</Alert>}
      <Card className="space-y-4">
        <div className="flex flex-wrap gap-2">
          {list.map((r) => (
            <button key={r.name} type="button" onClick={() => setName(r.name)}
              className={`rounded-lg px-4 py-3 text-base font-semibold ${name === r.name ? "bg-blue-700 text-white" : "border-2 border-blue-700 text-blue-700 hover:bg-blue-50"}`}>
              {r.title}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-end gap-4">
          {NEEDS_DATES.includes(name) && (
            <>
              <Field label="From" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
              <Field label="To" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </>
          )}
          <Button type="button" onClick={() => open(name, from, to)} disabled={busy}>{busy ? "Please wait…" : "Show report"}</Button>
          {rep && (
            <>
              <Button type="button" variant="secondary" onClick={() => printReport(rep)}>Print</Button>
              <Button type="button" variant="secondary" onClick={() => save("xlsx")}>Save as Excel</Button>
              <Button type="button" variant="secondary" onClick={() => save("csv")}>Save as CSV</Button>
            </>
          )}
        </div>
      </Card>

      {rep && (
        <Card>
          <h2 className="text-xl font-bold">{rep.title}</h2>
          {NEEDS_DATES.includes(rep.name) && <p className="mb-3 text-slate-600">From {rep.from_date} to {rep.to_date}</p>}
          {rep.note && <p className={`mb-3 ${rep.name === "profit" ? "rounded-lg bg-amber-50 p-3 font-semibold text-amber-900" : "text-sm text-slate-600"}`}>{rep.note}</p>}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left">
              <thead><tr className="border-b bg-slate-50">
                {rep.columns.map((c) => <th key={c.key} className={`p-3 ${c.type === "money" || c.type === "int" ? "text-right" : ""}`}>{c.label}</th>)}
              </tr></thead>
              <tbody>
                {rep.rows.map((r, i) => (
                  <tr key={i} className={`border-b ${rep.name === "profit" && i === rep.rows.length - 1 ? "bg-blue-50 text-lg font-bold" : ""}`}>
                    {rep.columns.map((c) => <td key={c.key} className={`p-3 ${c.type === "money" || c.type === "int" ? "text-right" : ""}`}>{fmt(r[c.key], c.type)}</td>)}
                  </tr>
                ))}
                {!rep.rows.length && <tr><td colSpan={rep.columns.length} className="p-6 text-center text-slate-500">Nothing to show for this report.</td></tr>}
                {rep.rows.length > 0 && Object.keys(rep.totals).length > 0 && rep.name !== "profit" && (
                  <tr className="border-t-2 bg-slate-50 font-bold">
                    {rep.columns.map((c, i) => <td key={c.key} className={`p-3 ${c.type === "money" || c.type === "int" ? "text-right" : ""}`}>{i === 0 ? "TOTAL" : fmt(rep.totals[c.key], c.type)}</td>)}
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

export default function ReportsPage() {
  return (
    <ModulePage title="Reports" perm="view_reports">
      <ReportsInner />
    </ModulePage>
  );
}
