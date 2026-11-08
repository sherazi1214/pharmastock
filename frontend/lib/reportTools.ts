// Print and download helpers for reports. Text from the database is escaped before it is put into the print page.
import { api } from "@/lib/api";

export type Col = { key: string; label: string; type: "text" | "int" | "money" | "date" };
export type Report = {
  name: string; title: string; business_name?: string; from_date: string; to_date: string; columns: Col[];
  rows: Record<string, string | number | null>[]; totals: Record<string, number>; note: string;
};

function esc(v: unknown): string {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] as string));
}
export function fmt(v: string | number | null | undefined, type: Col["type"]): string {
  if (v === null || v === undefined || v === "") return "";
  if (type === "money" && typeof v === "number") return v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return String(v);
}

export function printReport(rep: Report) {
  const businessName = rep.business_name ?? "";
  const w = window.open("", "_blank", "width=900,height=700");
  if (!w) { alert("Please allow pop-ups to print."); return; }
  const head = rep.columns.map((c) => `<th class="${c.type === "money" || c.type === "int" ? "r" : ""}">${esc(c.label)}</th>`).join("");
  const body = rep.rows.map((r) => `<tr>${rep.columns.map((c) => `<td class="${c.type === "money" || c.type === "int" ? "r" : ""}">${esc(fmt(r[c.key], c.type))}</td>`).join("")}</tr>`).join("");
  const foot = rep.rows.length && Object.keys(rep.totals).length
    ? `<tr class="t">${rep.columns.map((c, i) => `<td class="${c.type === "money" || c.type === "int" ? "r" : ""}">${i === 0 ? "TOTAL" : esc(fmt(rep.totals[c.key], c.type))}</td>`).join("")}</tr>` : "";
  w.document.write(`<!doctype html><html><head><title>${esc(rep.title)}</title><style>
    body{font-family:Arial,sans-serif;margin:24px;color:#111} h1{margin:0 0 4px;font-size:22px} .sub{color:#444;margin-bottom:14px}
    table{border-collapse:collapse;width:100%;font-size:13px} th,td{border:1px solid #999;padding:6px 8px;text-align:left} th{background:#eee}
    .r{text-align:right} .t td{font-weight:bold;background:#f5f5f5} .note{margin-top:12px;font-size:12px;color:#444}
    @media print{body{margin:8mm}}</style></head><body>
    <h1>${esc(rep.title)}</h1><div class="sub">${esc(businessName)} &nbsp; From ${esc(rep.from_date)} to ${esc(rep.to_date)} &nbsp; Printed ${esc(new Date().toLocaleString())}</div>
    <table><thead><tr>${head}</tr></thead><tbody>${body}${foot}</tbody></table>
    ${rep.note ? `<div class="note">${esc(rep.note)}</div>` : ""}
    <script>window.onload=function(){window.print();}<\/script></body></html>`);
  w.document.close();
}

export async function downloadReport(name: string, format: "csv" | "xlsx", from: string, to: string) {
  const q = `format=${format}&from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`;
  const r = await api<{ filename: string; mime: string; data_base64: string }>(`/reports/${name}/export?${q}`);
  const bin = atob(r.data_base64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([bytes], { type: r.mime }));
  const a = document.createElement("a");
  a.href = url; a.download = r.filename; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
