"use client";

import { useState } from "react";
import ModulePage from "@/components/ModulePage";
import Pos from "@/components/sales/Pos";
import History from "@/components/sales/History";
import SyncStatus from "@/components/SyncStatus";

export default function SalesPage() {
  const [tab, setTab] = useState<"new" | "history">("new");
  const tabBtn = (id: "new" | "history", label: string) => (
    <button
      type="button"
      onClick={() => setTab(id)}
      className={`rounded-lg px-5 py-3 text-lg font-semibold ${tab === id ? "bg-blue-700 text-white" : "border-2 border-blue-700 text-blue-700 hover:bg-blue-50"}`}
    >
      {label}
    </button>
  );
  return (
    <ModulePage title="Sales" perm="manage_sales">
      <div className="space-y-5">
        <SyncStatus />
        <div className="flex gap-3">{tabBtn("new", "New sale")}{tabBtn("history", "Past sales and returns")}</div>
        {tab === "new" ? <Pos /> : <History />}
      </div>
    </ModulePage>
  );
}
