"use client";

import { useId } from "react";

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger";
};

export function Button({ variant = "primary", className = "", ...props }: ButtonProps) {
  const styles = {
    primary: "bg-blue-700 text-white hover:bg-blue-800",
    secondary: "border-2 border-blue-700 bg-white text-blue-700 hover:bg-blue-50",
    danger: "bg-red-600 text-white hover:bg-red-700",
  };
  return (
    <button
      {...props}
      className={`rounded-lg px-5 py-3 text-lg font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${styles[variant]} ${className}`}
    />
  );
}

type FieldProps = React.InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string };

export function Field({ label, hint, className = "", ...props }: FieldProps) {
  const id = useId();
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1 block text-base font-semibold text-slate-800">
        {label}
      </label>
      <input
        id={id}
        {...props}
        className="w-full rounded-lg border-2 border-slate-300 px-4 py-3 text-lg focus:border-blue-600 focus:outline-none"
      />
      {hint && <p className="mt-1 text-sm text-slate-500">{hint}</p>}
    </div>
  );
}

export function SelectField({
  label,
  className = "",
  children,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement> & { label: string }) {
  const id = useId();
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1 block text-base font-semibold text-slate-800">
        {label}
      </label>
      <select
        id={id}
        {...props}
        className="w-full rounded-lg border-2 border-slate-300 bg-white px-4 py-3 text-lg focus:border-blue-600 focus:outline-none"
      >
        {children}
      </select>
    </div>
  );
}

export function Alert({ kind, children }: { kind: "error" | "success" | "info"; children: React.ReactNode }) {
  const styles = {
    error: "border-red-300 bg-red-50 text-red-800",
    success: "border-green-300 bg-green-50 text-green-800",
    info: "border-blue-200 bg-blue-50 text-blue-900",
  };
  return (
    <div role={kind === "error" ? "alert" : "status"} className={`rounded-lg border-2 px-4 py-3 text-base ${styles[kind]}`}>
      {children}
    </div>
  );
}

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-slate-200 bg-white p-6 shadow-sm ${className}`}>{children}</div>;
}

export function PageTitle({ children }: { children: React.ReactNode }) {
  return <h1 className="mb-6 text-3xl font-bold text-blue-900">{children}</h1>;
}
