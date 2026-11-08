import { BarChart3, Boxes, LayoutDashboard, Pill, Receipt, Settings, ShoppingCart, Truck, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type MenuItem = { href: string; label: string; icon: LucideIcon; perm: string };

// Exactly 9 main menu items. perm "owner" means only the owner can open it.
export const MENU: MenuItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, perm: "view_dashboard" },
  { href: "/products", label: "Products", icon: Pill, perm: "view_products" },
  { href: "/purchase", label: "Purchase", icon: ShoppingCart, perm: "manage_purchases" },
  { href: "/sales", label: "Sales", icon: Receipt, perm: "manage_sales" },
  { href: "/stock", label: "Stock", icon: Boxes, perm: "view_stock" },
  { href: "/suppliers", label: "Suppliers", icon: Truck, perm: "manage_suppliers" },
  { href: "/customers", label: "Customers", icon: Users, perm: "manage_customers" },
  { href: "/reports", label: "Reports", icon: BarChart3, perm: "view_reports" },
  { href: "/settings", label: "Settings", icon: Settings, perm: "owner" },
];
