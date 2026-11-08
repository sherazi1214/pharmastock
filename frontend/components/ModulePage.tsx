"use client";

import { useAuth } from "@/lib/auth";
import { Alert, Card, PageTitle } from "./ui";

/** Empty page for a menu item. Real content arrives in later phases. */
export default function ModulePage({
  title,
  perm,
  children,
}: {
  title: string;
  perm: string;
  children?: React.ReactNode;
}) {
  const { user, can } = useAuth();
  const allowed = perm === "owner" ? user?.role === "owner" : can(perm);

  return (
    <div>
      <PageTitle>{title}</PageTitle>
      {!allowed ? (
        <Alert kind="error">You do not have permission to open this page. Please ask the owner.</Alert>
      ) : (
        children ?? (
          <Card>
            <p className="text-lg text-slate-600">This page is empty for now. It will be built in a later phase.</p>
          </Card>
        )
      )}
    </div>
  );
}
