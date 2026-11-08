// Opens a print window with an A4 invoice or a small (80 mm) receipt.
// All text coming from the database is escaped before it is placed into the page.

export type PrintData = {
  business: { name: string; address: string; phone: string; licence_number: string };
  sale: {
    invoice_number: string; sale_type: string; created_at: string; customer_name: string | null;
    customer_phone?: string | null; customer_address?: string | null; subtotal: number; discount: number;
    total: number; paid_amount: number; due_amount: number; returned_total: number; payment_method: string;
  };
  items: {
    product_name: string; strength: string; unit_name: string; quantity: number; line_total: number;
    line_discount: number; net_total: number; pack_price: number; batches: { batch_number: string; expiry_date: string }[];
  }[];
};

function esc(v: unknown): string {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c] as string));
}
const m = (n: number) => Number(n).toFixed(2);

export function printSale(data: PrintData, layout: "a4" | "receipt") {
  const { business: b, sale: s, items } = data;
  const when = s.created_at.replace("T", " ").slice(0, 16);
  const head = `
    <h1>${esc(b.name)}</h1>
    <div>${esc(b.address)}</div>
    <div>${b.phone ? "Phone: " + esc(b.phone) : ""} ${b.licence_number ? " | Licence: " + esc(b.licence_number) : ""}</div>`;

  let body = "";
  if (layout === "a4") {
    body = `
      <div class="top">${head}<h2>${s.sale_type === "wholesale" ? "WHOLESALE INVOICE" : "SALE INVOICE"}</h2></div>
      <p><b>Invoice:</b> ${esc(s.invoice_number)} &nbsp; <b>Date:</b> ${esc(when)}<br/>
      <b>Customer:</b> ${esc(s.customer_name || "Walk-in customer")} ${s.customer_phone ? "(" + esc(s.customer_phone) + ")" : ""}
      ${s.customer_address ? "<br/>" + esc(s.customer_address) : ""}</p>
      <table><tr><th>#</th><th>Medicine</th><th>Batch / Expiry</th><th>Qty</th><th>Amount</th><th>Discount</th><th>Total</th></tr>
      ${items.map((i, n) => `<tr><td>${n + 1}</td><td>${esc(i.product_name)} ${esc(i.strength)}</td>
        <td>${i.batches.map((x) => esc(x.batch_number) + " / " + esc(x.expiry_date)).join("<br/>")}</td>
        <td>${esc(i.quantity)} ${esc(i.unit_name)}</td><td class="r">${m(i.line_total + i.line_discount)}</td>
        <td class="r">${m(i.line_discount)}</td><td class="r">${m(i.line_total)}</td></tr>`).join("")}
      </table>
      <table class="sum">
        <tr><td>Subtotal</td><td class="r">${m(s.subtotal)}</td></tr>
        <tr><td>Discount</td><td class="r">${m(s.discount)}</td></tr>
        <tr><td><b>Total</b></td><td class="r"><b>${m(s.total)}</b></td></tr>
        <tr><td>Paid (${esc(s.payment_method || "-")})</td><td class="r">${m(s.paid_amount)}</td></tr>
        <tr><td>Balance due</td><td class="r">${m(s.due_amount)}</td></tr>
      </table>
      <p class="small">Please check medicines and expiry dates before leaving. Thank you.</p>`;
  } else {
    body = `
      <div class="c">${head}<hr/><b>${esc(s.invoice_number)}</b> &nbsp; ${esc(when)}<br/>${esc(s.customer_name || "Walk-in customer")}</div><hr/>
      ${items.map((i) => `<div><b>${esc(i.product_name)} ${esc(i.strength)}</b><br/>
        ${esc(i.quantity)} ${esc(i.unit_name)} &nbsp; Batch ${i.batches.map((x) => esc(x.batch_number) + " exp " + esc(x.expiry_date)).join(", ")}
        <span class="rr">${m(i.line_total)}</span></div>`).join("<hr class='d'/>")}
      <hr/>
      <div>Discount <span class="rr">${m(s.discount)}</span></div>
      <div><b>TOTAL <span class="rr">${m(s.total)}</span></b></div>
      <div>Paid <span class="rr">${m(s.paid_amount)}</span></div>
      <div>Balance due <span class="rr">${m(s.due_amount)}</span></div>
      <hr/><div class="c">Thank you</div>`;
  }

  const css =
    layout === "a4"
      ? `@page{size:A4;margin:14mm}body{font:14px Arial,sans-serif;color:#000}h1{margin:0;font-size:24px}h2{margin:8px 0}
         table{width:100%;border-collapse:collapse;margin-top:10px}th,td{border:1px solid #888;padding:6px;text-align:left;vertical-align:top}
         .r{text-align:right}.sum{width:46%;margin-left:auto}.small{font-size:12px;color:#444}`
      : `@page{size:80mm auto;margin:3mm}body{font:12px Arial,sans-serif;width:74mm;color:#000}h1{margin:0;font-size:16px}
         .c{text-align:center}hr{border:0;border-top:1px dashed #000}hr.d{border-top:1px dotted #999}.rr{float:right}`;

  const w = window.open("", "_blank", "width=900,height=700");
  if (!w) {
    alert("Your browser blocked the print window. Please allow pop-ups for this site and try again.");
    return;
  }
  w.document.write(`<!doctype html><html><head><meta charset="utf-8"/><title>${esc(s.invoice_number)}</title><style>${css}</style></head><body>${body}<script>window.onload=function(){window.print()}</script></body></html>`);
  w.document.close();
}
