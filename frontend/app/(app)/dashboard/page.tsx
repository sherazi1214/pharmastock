"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Alert, Card } from "@/components/ui";
import SyncStatus from "@/components/SyncStatus";

type Dash = {
  date: string; today_sales: number | null; today_invoices?: number; today_returns: number | null; today_purchases: number | null;
  stock_value: number | null; low_stock_count: number | null; near_expiry_count: number | null; customer_outstanding: number | null;
  shortcuts: { label: string; href: string }[];
};
const money = (n: number) => n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function DashboardPage() {
  const [d, setD] = useState<Dash | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<Dash>("/dashboard").then(setD).catch((e) => setError(e instanceof Error ? e.message : "Could not load the dashboard."));
  }, []);

  const tiles: { label: string; value: string; note?: string; warn?: boolean; href?: string }[] = [];
  if (d) {
    if (d.today_sales !== null) tiles.push({ label: "Today's sales", value: money(d.today_sales), note: `${d.today_invoices ?? 0} invoices` + (d.today_returns ? `, returns ${money(d.today_returns)}` : ""), href: "/sales" });
    if (d.today_purchases !== null) tiles.push({ label: "Today's purchases", value: money(d.today_purchases), href: "/purchase" });
    if (d.stock_value !== null) tiles.push({ label: "Stock value", value: money(d.stock_value), href: "/stock" });
    if (d.low_stock_count !== null) tiles.push({ label: "Low stock medicines", value: String(d.low_stock_count), warn: d.low_stock_count > 0, href: "/stock" });
    if (d.near_expiry_count !== null) tiles.push({ label: "Near expiry batches", value: String(d.near_expiry_count), warn: d.near_expiry_count > 0, href: "/stock" });
    if (d.customer_outstanding !== null) tiles.push({ label: "Customers owe", value: money(d.customer_outstanding), href: "/customers" });
  }

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Dashboard</h1>
      <SyncStatus showBackup />
      {error && <Alert kind="error">{error}</Alert>}
      {d && d.shortcuts.length > 0 && (
        <div className="flex flex-wrap gap-4">
          {d.shortcuts.map((s) => (
            <Link key={s.label} href={s.href} className="rounded-xl bg-blue-700 px-8 py-5 text-xl font-bold text-white hover:bg-blue-800">{s.label}</Link>
          ))}
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {tiles.map((t) => (
          <Link key={t.label} href={t.href ?? "#"}>
            <Card className={`h-full ${t.warn ? "border-2 border-amber-400" : ""}`}>
              <div className="text-lg text-slate-600">{t.label}</div>
              <div className="mt-1 text-4xl font-bold">{t.value}</div>
              {t.note && <div className="mt-1 text-slate-600">{t.note}</div>}
            </Card>
          </Link>
        ))}
      </div>
      {d && !tiles.length && <p className="text-slate-600">There are no figures to show for your role.</p>}
    </div>
  );
}
