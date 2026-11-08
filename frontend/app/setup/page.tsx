"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Alert, Button, Card, Field } from "@/components/ui";

export default function SetupPage() {
  const router = useRouter();
  const { login } = useAuth();
  const [checking, setChecking] = useState(true);
  const [form, setForm] = useState({ business_name: "", owner_name: "", username: "", password: "", confirm: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<{ needs_setup: boolean }>("/setup/status")
      .then((s) => {
        if (!s.needs_setup) router.replace("/login");
        else setChecking(false);
      })
      .catch((e) => {
        setError(e.message);
        setChecking(false);
      });
  }, [router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (form.password !== form.confirm) {
      setError("The two passwords are not the same.");
      return;
    }
    setBusy(true);
    try {
      await api("/setup", {
        method: "POST",
        body: {
          business_name: form.business_name,
          owner_name: form.owner_name,
          username: form.username,
          password: form.password,
        },
      });
      await login(form.username, form.password);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setBusy(false);
    }
  }

  if (checking) return <div className="flex min-h-screen items-center justify-center text-xl text-slate-600">Loading…</div>;

  return (
    <div className="flex min-h-screen items-center justify-center bg-blue-50 p-6">
      <Card className="w-full max-w-lg">
        <h1 className="text-3xl font-bold text-blue-900">Welcome to PharmaStock</h1>
        <p className="mb-6 mt-2 text-lg text-slate-600">Let us set up your business. You only do this once.</p>
        <form onSubmit={submit} className="space-y-4">
          {error && <Alert kind="error">{error}</Alert>}
          <Field label="Business name" value={form.business_name} onChange={(e) => setForm({ ...form, business_name: e.target.value })} required autoFocus />
          <Field label="Owner name" value={form.owner_name} onChange={(e) => setForm({ ...form, owner_name: e.target.value })} required />
          <Field
            label="Username"
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
            hint="Letters and numbers only, no spaces. You will use this to log in."
            autoComplete="username"
            required
          />
          <Field
            label="Password"
            type="password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            hint="At least 8 characters. Keep it safe."
            autoComplete="new-password"
            required
          />
          <Field
            label="Type the password again"
            type="password"
            value={form.confirm}
            onChange={(e) => setForm({ ...form, confirm: e.target.value })}
            autoComplete="new-password"
            required
          />
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "Please wait…" : "Start using PharmaStock"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
