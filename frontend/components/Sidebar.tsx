"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { MENU } from "@/lib/menu";
import { ROLE_LABELS } from "@/lib/types";

export default function Sidebar() {
  const { user, can, logout } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  const items = MENU.filter((m) => (m.perm === "owner" ? user?.role === "owner" : can(m.perm)));

  async function handleLogout() {
    await logout();
    router.replace("/login");
  }

  return (
    <aside className="sticky top-0 flex h-screen w-64 shrink-0 flex-col bg-blue-800 text-white">
      <div className="border-b border-blue-600 px-5 py-6">
        <div className="text-sm uppercase tracking-wide text-blue-200">PharmaStock 2027</div>
        <div className="mt-1 text-xl font-bold leading-tight">{user?.business.name}</div>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4" aria-label="Main menu">
        {items.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 rounded-lg px-4 py-3 text-lg font-medium transition ${
                active ? "bg-white text-blue-800" : "text-blue-50 hover:bg-blue-700"
              }`}
            >
              <Icon size={22} aria-hidden />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-blue-600 px-5 py-4">
        <div className="text-base font-semibold">{user?.full_name}</div>
        <div className="mb-3 text-sm text-blue-200">{user ? ROLE_LABELS[user.role] : ""}</div>
        <button
          onClick={handleLogout}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-900 px-4 py-3 text-lg font-semibold hover:bg-blue-950"
        >
          <LogOut size={20} aria-hidden /> Log out
        </button>
      </div>
    </aside>
  );
}
