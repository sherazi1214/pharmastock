"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Alert, Button, Card, Field } from "@/components/ui";
import { discardItem, getQueue, QUEUE_EVENT, retryErrors, flushQueue, type QueueItem } from "@/lib/offlineQueue";

type Backup = { id: number; filename: string; kind: string; status: string; label: string; size_bytes: number; created_at: string; verified_at: string | null; message: string; total_records: number; exists: boolean };
type Status = { cloud: { state: string; message: string }; waiting_for_cloud: number; backup_warning: string | null };

export default function BackupPanel() {
  const [items, setItems] = useState<Backup[]>([]);
  const [folder, setFolder] = useState("");
  const [st, setSt] = useState<Status | null>(null);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [restoreId, setRestoreId] = useState<number | null>(null);
  const [confirm, setConfirm] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api<{ items: Backup[]; folder: string }>("/backups");
      setItems(r.items); setFolder(r.folder);
      setSt(await api<Status>("/sync/status"));
    } catch (e) { setError(e instanceof Error ? e.message : "Could not load backups."); }
    setQueue(getQueue());
  }, []);
  useEffect(() => {
    load();
    const on = () => setQueue(getQueue());
    window.addEventListener(QUEUE_EVENT, on);
    return () => window.removeEventListener(QUEUE_EVENT, on);
  }, [load]);

  async function backupNow() {
    setBusy(true); setError(""); setNotice("");
    try {
      const b = await api<Backup>("/backups", { method: "POST" });
      if (b.status === "verified") setNotice(`Backed up and verified (${b.total_records} records checked). File: ${b.filename}`);
      else setError(`Backup FAILED. ${b.message}`);
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Backup failed."); }
    finally { setBusy(false); }
  }

  async function restore() {
    if (restoreId === null) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const r = await api<{ message: string; safety_backup: string }>(`/backups/${restoreId}/restore`, { method: "POST", body: { confirm } });
      setNotice(`${r.message} Your data before the restore was saved as ${r.safety_backup}.`);
      setRestoreId(null); setConfirm(""); await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Restore failed."); }
    finally { setBusy(false); }
  }

  return (
    <div className="space-y-5">
      {error && <Alert kind="error">{error}</Alert>}
      {notice && <Alert kind="success">{notice}</Alert>}

      <Card className="space-y-3">
        <h2 className="text-xl font-bold">Backup</h2>
        <p className="text-slate-600">A backup is called &quot;verified&quot; only after the copy has been checked. If you see FAILED, there is no backup.</p>
        {st?.backup_warning && <Alert kind="error">{st.backup_warning}</Alert>}
        <Button type="button" onClick={backupNow} disabled={busy}>{busy ? "Please wait…" : "Make backup now"}</Button>
        {folder && <p className="text-sm text-slate-600">Backup folder on this computer: <b>{folder}</b>. Copy these files to a USB drive or another computer too.</p>}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[700px] text-left">
            <thead><tr className="border-b bg-slate-50">{["Date", "Type", "Result", "Records", "Size", ""].map((h) => <th key={h} className="p-3">{h}</th>)}</tr></thead>
            <tbody>
              {items.map((b) => (
                <tr key={b.id} className="border-b">
                  <td className="p-3">{b.created_at.replace("T", " ").slice(0, 16)}</td>
                  <td className="p-3">{b.kind === "before-restore" ? "Safety copy" : "Manual"}</td>
                  <td className={`p-3 font-semibold ${b.status === "verified" ? "text-green-700" : "text-red-700"}`}>{b.label}{b.status !== "verified" && b.message ? ` - ${b.message}` : ""}</td>
                  <td className="p-3">{b.status === "verified" ? b.total_records : "-"}</td>
                  <td className="p-3">{b.status === "verified" ? `${(b.size_bytes / 1024 / 1024).toFixed(2)} MB` : "-"}</td>
                  <td className="p-3">{b.status === "verified" && b.exists && <button className="font-semibold text-red-700" onClick={() => { setRestoreId(b.id); setConfirm(""); }}>Restore</button>}</td>
                </tr>
              ))}
              {!items.length && <tr><td colSpan={6} className="p-6 text-center text-slate-500">No backup has been made yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>

      {restoreId !== null && (
        <Card className="space-y-3 border-2 border-red-400">
          <h2 className="text-xl font-bold text-red-800">Restore this backup?</h2>
          <p>Everything entered after this backup will be replaced by the backup. A safety copy of your current data is made first. Type <b>RESTORE</b> to continue.</p>
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Type RESTORE" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            <Button type="button" onClick={restore} disabled={busy || confirm.trim().toUpperCase() !== "RESTORE"}>Restore now</Button>
            <Button type="button" variant="secondary" onClick={() => setRestoreId(null)}>Cancel</Button>
          </div>
        </Card>
      )}

      <Card className="space-y-3">
        <h2 className="text-xl font-bold">Sync</h2>
        <p><b>Cloud:</b> {st?.cloud.message ?? "…"}</p>
        {queue.length > 0 ? (
          <>
            <p className="font-semibold">Saved on this computer, not yet on the server: {queue.length}</p>
            <div className="flex gap-3"><Button type="button" onClick={() => flushQueue().then(load)}>Send now</Button>
              {queue.some((q) => q.status === "error") && <Button type="button" variant="secondary" onClick={() => retryErrors()}>Try refused items again</Button>}</div>
            <table className="w-full text-left"><thead><tr className="border-b bg-slate-50">{["Type", "Time", "State", ""].map((h) => <th key={h} className="p-3">{h}</th>)}</tr></thead>
              <tbody>{queue.map((q) => (
                <tr key={q.client_uuid} className="border-b"><td className="p-3 capitalize">{q.kind.replace("_", " ")} {q.label}</td><td className="p-3">{q.created_at.replace("T", " ").slice(0, 16)}</td>
                  <td className={`p-3 ${q.status === "error" ? "font-semibold text-red-700" : ""}`}>{q.status === "error" ? `Refused: ${q.message}` : "Waiting"}</td>
                  <td className="p-3">{q.status === "error" && <button className="font-semibold text-red-700" onClick={() => discardItem(q.client_uuid)}>Delete</button>}</td></tr>))}</tbody></table>
          </>
        ) : <p className="text-slate-600">Nothing is waiting on this computer.</p>}
      </Card>
    </div>
  );
}
