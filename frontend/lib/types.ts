export type Role = "owner" | "salesperson" | "stock_operator";

export const ROLE_LABELS: Record<Role, string> = {
  owner: "Owner / Admin",
  salesperson: "Salesperson",
  stock_operator: "Stock / Purchase Operator",
};

export type Me = {
  id: number;
  username: string;
  full_name: string;
  role: Role;
  permissions: string[];
  business: { id: number; name: string };
};
