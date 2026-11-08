"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { QUEUE_EVENT, flushQueue, queueCounts, startAutoSync } from "@/lib/offlineQueue";

type Status = {
  cloud: { configured: boolean; state: string; message: string };
  backup_warning: string | null; hours_since_backup: number | null; waiting_for_cloud: number;
};

export default function SyncStatus({ showBackup = false }: { showBackup?: boolean }) {
  const [counts, setCounts] = useState({ pending: 0, error: 0 });
  const [st, setSt] = useState<Status | null>(null);
  const [reachable, setReachable] = useState(true);

  const refresh = useCallback(async () => {
    setCounts(queueCounts());
    try { setSt(await api<Status>("/sync/status")); setReachable(true); }
    catch { setReachable(false); }
  }, []);

  useEffect(() => {
    startAutoSync();
    refresh();
    const t = setInterval(refresh, 20000);
    const on = () => setCounts(queueCounts());
    window.addEventListener(QUEUE_EVENT, on);
    return () => { clearInterval(t); window.removeEventListener(QUEUE_EVENT, on); };
  }, [refresh]);

  // Only the real facts are shown. "Synced" is never shown unless a cloud is connected and caught up.
  let label = "Local only", tone = "bg-slate-100 text-slate-800", detail = "Saved on this computer. Cloud sync is not configured.";
  if (!reachable) { label = counts.pending ? `Offline - ${counts.pending} waiting` : "Server not reachable"; tone = "bg-amber-100 text-amber-900"; detail = "New sales are kept on this computer and sent when the server is back."; }
  else if (counts.error) { label = `Error - ${counts.error} not saved`; tone = "bg-red-100 text-red-800"; detail = "Some saved items were refused by the server. Open Sync details."; }
  else if (counts.pending) { label = `Pending - ${counts.pending}`; tone = "bg-amber-100 text-amber-900"; detail = "Waiting to be sent to the server."; }
  else if (st?.cloud.configured) { label = "Local only"; detail = st.cloud.message; }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <span className={`rounded-full px-4 py-2 text-base font-semibold ${tone}`} title={detail}>{label}</span>
      <span className="text-sm text-slate-600">{detail}</span>
      {(counts.pending > 0 || counts.error > 0) && (
        <button type="button" className="text-sm font-semibold text-blue-700 underline" onClick={() => flushQueue().then(refresh)}>Send now</button>
      )}
      {showBackup && st?.backup_warning && <Link href="/settings/backup" className="text-sm font-semibold text-red-700 underline">{st.backup_warning} Make a backup</Link>}
    </div>
  );
}
