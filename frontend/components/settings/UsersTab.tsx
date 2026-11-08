"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { ROLE_LABELS, type Role } from "@/lib/types";
import { Alert, Button, Card, Field, SelectField } from "@/components/ui";

type U = {
  id: number;
  username: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  locked: boolean;
  last_login_at: string | null;
};

const ROLES: Role[] = ["owner", "salesperson", "stock_operator"];

export default function UsersTab() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<U[]>([]);
  const [msg, setMsg] = useState<{ kind: "error" | "success"; text: string } | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ full_name: "", username: "", password: "", role: "salesperson" as Role });
  const [resetId, setResetId] = useState<number | null>(null);
  const [newPassword, setNewPassword] = useState("");

  const load = useCallback(async () => {
    try {
      setUsers(await api<U[]>("/users"));
    } catch (e) {
      setMsg({ kind: "error", text: e instanceof Error ? e.message : "Could not load users." });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function run(action: () => Promise<unknown>, success: string) {
    setMsg(null);
    try {
      await action();
      setMsg({ kind: "success", text: success });
      await load();
    } catch (e) {
      setMsg({ kind: "error", text: e instanceof Error ? e.message : "Something went wrong." });
    }
  }

  async function addUser(e: React.FormEvent) {
    e.preventDefault();
    await run(async () => {
      await api("/users", { method: "POST", body: form });
      setForm({ full_name: "", username: "", password: "", role: "salesperson" });
      setAdding(false);
    }, "User added.");
  }

  async function savePassword(id: number) {
    await run(async () => {
      await api(`/users/${id}/reset-password`, { method: "POST", body: { new_password: newPassword } });
      setResetId(null);
      setNewPassword("");
    }, "Password changed. The user must log in again.");
  }

  return (
    <div className="space-y-6">
      {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}

      <div>
        <Button onClick={() => setAdding(!adding)} variant={adding ? "secondary" : "primary"}>
          {adding ? "Cancel" : "+ Add user"}
        </Button>
      </div>

      {adding && (
        <Card>
          <form onSubmit={addUser} className="grid max-w-3xl gap-4 sm:grid-cols-2">
            <Field label="Full name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required />
            <Field
              label="Username"
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              hint="Letters and numbers only, no spaces"
              autoComplete="off"
              required
            />
            <Field
              label="Password"
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              hint="At least 8 characters"
              autoComplete="new-password"
              required
            />
            <SelectField label="Role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABELS[r]}
                </option>
              ))}
            </SelectField>
            <div className="sm:col-span-2">
              <Button type="submit">Save user</Button>
            </div>
          </form>
        </Card>
      )}

      <Card className="overflow-x-auto p-0">
        <table className="w-full text-left text-base">
          <thead className="bg-slate-50 text-sm uppercase text-slate-600">
            <tr>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">Username</th>
              <th className="px-4 py-3">Role</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const isMe = u.id === me?.id;
              return (
                <tr key={u.id} className="border-t border-slate-200 align-top">
                  <td className="px-4 py-3 font-semibold">{u.full_name}{isMe && <span className="ml-2 text-sm text-slate-500">(you)</span>}</td>
                  <td className="px-4 py-3">{u.username}</td>
                  <td className="px-4 py-3">
                    <select
                      aria-label={`Role of ${u.username}`}
                      value={u.role}
                      disabled={isMe}
                      onChange={(e) => run(() => api(`/users/${u.id}`, { method: "PATCH", body: { role: e.target.value } }), "Role changed.")}
                      className="rounded-lg border-2 border-slate-300 bg-white px-2 py-2 disabled:bg-slate-100"
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {ROLE_LABELS[r]}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-3">
                    {!u.is_active ? (
                      <span className="font-semibold text-red-700">Disabled</span>
                    ) : u.locked ? (
                      <span className="font-semibold text-amber-700">Locked</span>
                    ) : (
                      <span className="font-semibold text-green-700">Active</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="secondary"
                        className="px-3 py-2 text-base"
                        onClick={() => {
                          setResetId(resetId === u.id ? null : u.id);
                          setNewPassword("");
                        }}
                      >
                        Reset password
                      </Button>
                      {!isMe && (
                        <Button
                          variant={u.is_active ? "danger" : "primary"}
                          className="px-3 py-2 text-base"
                          onClick={() =>
                            run(
                              () => api(`/users/${u.id}`, { method: "PATCH", body: { is_active: !u.is_active } }),
                              u.is_active ? "User disabled." : "User enabled.",
                            )
                          }
                        >
                          {u.is_active ? "Disable" : "Enable"}
                        </Button>
                      )}
                    </div>
                    {resetId === u.id && (
                      <div className="mt-3 flex items-end gap-2">
                        <Field
                          label="New password"
                          type="password"
                          value={newPassword}
                          onChange={(e) => setNewPassword(e.target.value)}
                          autoComplete="new-password"
                          hint="At least 8 characters"
                        />
                        <Button className="mb-6" onClick={() => savePassword(u.id)}>
                          Save
                        </Button>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
