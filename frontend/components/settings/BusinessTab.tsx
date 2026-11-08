"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Alert, Button, Card, Field } from "@/components/ui";

type Biz = {
  business_name: string;
  owner_name: string;
  address: string;
  phone: string;
  licence_number: string;
  payment_methods: string[];
  near_expiry_days: number;
};

export default function BusinessTab() {
  const { refresh } = useAuth();
  const [biz, setBiz] = useState<Biz | null>(null);
  const [msg, setMsg] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const [newMethod, setNewMethod] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api<Biz>("/settings")
      .then(setBiz)
      .catch((e) => setMsg({ kind: "error", text: e.message }));
  }, []);

  if (!biz) return msg ? <Alert kind={msg.kind}>{msg.text}</Alert> : <p className="text-lg">Loading…</p>;

  const set = <K extends keyof Biz>(key: K, value: Biz[K]) => setBiz({ ...biz, [key]: value });

  function addMethod() {
    const name = newMethod.trim();
    if (!name || !biz) return;
    if (!biz.payment_methods.some((m) => m.toLowerCase() === name.toLowerCase())) {
      set("payment_methods", [...biz.payment_methods, name]);
    }
    setNewMethod("");
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!biz) return;
    setSaving(true);
    setMsg(null);
    try {
      setBiz(await api<Biz>("/settings", { method: "PUT", body: biz }));
      await refresh();
      setMsg({ kind: "success", text: "Settings saved." });
    } catch (err) {
      setMsg({ kind: "error", text: err instanceof Error ? err.message : "Could not save." });
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={save} className="max-w-3xl space-y-6">
      {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}

      <Card className="space-y-4">
        <h2 className="text-xl font-bold">Business information</h2>
        <Field label="Business name" value={biz.business_name} onChange={(e) => set("business_name", e.target.value)} required />
        <Field label="Owner name" value={biz.owner_name} onChange={(e) => set("owner_name", e.target.value)} required />
        <Field label="Address" value={biz.address} onChange={(e) => set("address", e.target.value)} />
        <Field label="Phone" value={biz.phone} onChange={(e) => set("phone", e.target.value)} />
        <Field label="Licence number" value={biz.licence_number} onChange={(e) => set("licence_number", e.target.value)} />
      </Card>

      <Card className="space-y-4">
        <h2 className="text-xl font-bold">Payment methods</h2>
        <div className="flex flex-wrap gap-2">
          {biz.payment_methods.map((m) => (
            <span key={m} className="flex items-center gap-2 rounded-full bg-blue-100 px-4 py-2 text-base font-semibold text-blue-900">
              {m}
              <button
                type="button"
                aria-label={`Remove ${m}`}
                onClick={() => set("payment_methods", biz.payment_methods.filter((x) => x !== m))}
                className="text-lg leading-none text-blue-700 hover:text-red-600"
              >
                ×
              </button>
            </span>
          ))}
        </div>
        <div className="flex items-end gap-3">
          <Field
            className="flex-1"
            label="Add a payment method"
            value={newMethod}
            onChange={(e) => setNewMethod(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addMethod();
              }
            }}
            placeholder="e.g. JazzCash"
          />
          <Button type="button" variant="secondary" onClick={addMethod}>
            Add
          </Button>
        </div>
      </Card>

      <Card className="space-y-4">
        <h2 className="text-xl font-bold">Expiry warning</h2>
        <Field
          label="Near-expiry days"
          type="number"
          min={1}
          max={3650}
          value={biz.near_expiry_days}
          onChange={(e) => set("near_expiry_days", Number(e.target.value))}
          hint="A medicine is shown as 'Near expiry' this many days before its expiry date. Default is 90."
        />
      </Card>

      <Button type="submit" disabled={saving}>
        {saving ? "Saving…" : "Save settings"}
      </Button>
    </form>
  );
}
