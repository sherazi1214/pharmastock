"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Alert, Card } from "@/components/ui";

type Row = { id: number; username: string | null; action: string; details: string | null; created_at: string };

export default function ActivityTab() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Row[]>("/audit-logs?limit=200")
      .then(setRows)
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <Alert kind="error">{error}</Alert>;
  if (!rows) return <p className="text-lg">Loading…</p>;

  return (
    <Card className="overflow-x-auto p-0">
      <table className="w-full text-left text-base">
        <thead className="bg-slate-50 text-sm uppercase text-slate-600">
          <tr>
            <th className="px-4 py-3">When</th>
            <th className="px-4 py-3">User</th>
            <th className="px-4 py-3">What happened</th>
            <th className="px-4 py-3">Details</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-slate-200 align-top">
              <td className="whitespace-nowrap px-4 py-3">{new Date(r.created_at).toLocaleString()}</td>
              <td className="px-4 py-3">{r.username ?? "-"}</td>
              <td className="px-4 py-3 font-semibold">{r.action.replace(/_/g, " ")}</td>
              <td className="px-4 py-3 text-slate-600">{r.details ?? ""}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={4} className="px-4 py-6 text-slate-500">
                Nothing recorded yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Card>
  );
}
