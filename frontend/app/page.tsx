"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, getToken } from "@/lib/api";
import { Alert, Button } from "@/components/ui";

export default function Home() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  const decide = useCallback(async () => {
    setError(null);
    try {
      const s = await api<{ needs_setup: boolean }>("/setup/status");
      if (s.needs_setup) router.replace("/setup");
      else router.replace(getToken() ? "/dashboard" : "/login");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    }
  }, [router]);

  useEffect(() => {
    decide();
  }, [decide]);

  if (error) {
    return (
      <div className="mx-auto flex min-h-screen max-w-lg flex-col justify-center gap-4 p-6">
        <Alert kind="error">{error}</Alert>
        <Button onClick={decide}>Try again</Button>
      </div>
    );
  }
  return <div className="flex min-h-screen items-center justify-center text-xl text-slate-600">Loading…</div>;
}
