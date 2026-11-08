"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ROLE_LABELS, type Role } from "@/lib/types";
import { Alert, Button, Card } from "@/components/ui";

type PermData = {
  permissions: { key: string; label: string }[];
  roles: Record<string, string[]>;
};

const EDITABLE: Role[] = ["salesperson", "stock_operator"];

export default function PermissionsTab() {
  const [data, setData] = useState<PermData | null>(null);
  const [msg, setMsg] = useState<{ kind: "error" | "success"; text: string } | null>(null);

  useEffect(() => {
    api<PermData>("/permissions")
      .then(setData)
      .catch((e) => setMsg({ kind: "error", text: e.message }));
  }, []);

  if (!data) return msg ? <Alert kind={msg.kind}>{msg.text}</Alert> : <p className="text-lg">Loading…</p>;

  function toggle(role: Role, key: string) {
    if (!data) return;
    const current = data.roles[role] ?? [];
    const next = current.includes(key) ? current.filter((k) => k !== key) : [...current, key];
    setData({ ...data, roles: { ...data.roles, [role]: next } });
  }

  async function save(role: Role) {
    if (!data) return;
    setMsg(null);
    try {
      await api(`/permissions/${role}`, { method: "PUT", body: { permissions: data.roles[role] } });
      setMsg({ kind: "success", text: `${ROLE_LABELS[role]} permissions saved.` });
    } catch (e) {
      setMsg({ kind: "error", text: e instanceof Error ? e.message : "Could not save." });
    }
  }

  return (
    <div className="space-y-6">
      {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}
      <Alert kind="info">The owner always has full access. Choose what each other role is allowed to do.</Alert>
      <div className="grid gap-6 lg:grid-cols-2">
        {EDITABLE.map((role) => (
          <Card key={role}>
            <h2 className="mb-4 text-xl font-bold">{ROLE_LABELS[role]}</h2>
            <div className="space-y-3">
              {data.permissions.map((p) => (
                <label key={p.key} className="flex cursor-pointer items-center gap-3 text-lg">
                  <input
                    type="checkbox"
                    className="h-6 w-6 accent-blue-700"
                    checked={(data.roles[role] ?? []).includes(p.key)}
                    onChange={() => toggle(role, p.key)}
                  />
                  {p.label}
                </label>
              ))}
            </div>
            <Button className="mt-6" onClick={() => save(role)}>
              Save
            </Button>
          </Card>
        ))}
      </div>
    </div>
  );
}
