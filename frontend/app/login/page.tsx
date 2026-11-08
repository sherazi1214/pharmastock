"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Alert, Button, Card, Field } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const { user, loading, login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && user) {
      router.replace("/dashboard");
      return;
    }
    api<{ needs_setup: boolean }>("/setup/status")
      .then((s) => {
        if (s.needs_setup) router.replace("/setup");
      })
      .catch((e) => setError(e.message));
  }, [loading, user, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(username, password);
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setPassword("");
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-blue-50 p-6">
      <Card className="w-full max-w-md">
        <h1 className="text-3xl font-bold text-blue-900">PharmaStock 2027</h1>
        <p className="mb-6 mt-2 text-lg text-slate-600">Please log in to continue.</p>
        <form onSubmit={submit} className="space-y-4">
          {error && <Alert kind="error">{error}</Alert>}
          <Field label="Username" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required autoFocus />
          <Field label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
          <Button type="submit" disabled={busy} className="w-full">
            {busy ? "Please wait…" : "Log in"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
