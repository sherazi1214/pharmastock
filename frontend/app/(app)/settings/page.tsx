"use client";

import { useState } from "react";
import ModulePage from "@/components/ModulePage";
import BusinessTab from "@/components/settings/BusinessTab";
import UsersTab from "@/components/settings/UsersTab";
import PermissionsTab from "@/components/settings/PermissionsTab";
import ActivityTab from "@/components/settings/ActivityTab";

const TABS = [
  { id: "business", label: "Business" },
  { id: "users", label: "Users" },
  { id: "permissions", label: "Permissions" },
  { id: "activity", label: "Activity log" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function SettingsPage() {
  const [tab, setTab] = useState<TabId>("business");
  return (
    <ModulePage title="Settings" perm="owner">
      <div className="mb-6 flex flex-wrap gap-2 border-b-2 border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`-mb-0.5 rounded-t-lg border-b-4 px-5 py-3 text-lg font-semibold ${
              tab === t.id ? "border-blue-700 text-blue-800" : "border-transparent text-slate-600 hover:text-blue-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "business" && <BusinessTab />}
      {tab === "users" && <UsersTab />}
      {tab === "permissions" && <PermissionsTab />}
      {tab === "activity" && <ActivityTab />}
    </ModulePage>
  );
}
