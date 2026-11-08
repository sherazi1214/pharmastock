// Offline queue: if the server cannot be reached, the sale / purchase / payment is kept in this browser
// (with its client_uuid) and sent again automatically. The server saves each client_uuid only once.
import { api } from "@/lib/api";

export type Kind = "sale" | "purchase" | "customer_payment" | "supplier_payment";
export type QueueItem = {
  client_uuid: string; kind: Kind; payload: Record<string, unknown>; created_at: string;
  attempts: number; status: "pending" | "error"; message?: string; label?: string;
};
type PushResult = { client_uuid: string; status: "saved" | "duplicate" | "error" | "retry"; id?: number; message: string; invoice_number?: string };

const KEY = "pharmastock.queue.v1";
export const QUEUE_EVENT = "pharmastock-queue";
let flushing = false;

function read(): QueueItem[] {
  try { const v = JSON.parse(localStorage.getItem(KEY) || "[]"); return Array.isArray(v) ? v : []; } catch { return []; }
}
function write(items: QueueItem[]) {
  localStorage.setItem(KEY, JSON.stringify(items));
  window.dispatchEvent(new Event(QUEUE_EVENT));
}

export function getQueue(): QueueItem[] { return read(); }
export function queueCounts() {
  const q = read();
  return { pending: q.filter((i) => i.status === "pending").length, error: q.filter((i) => i.status === "error").length };
}

export function isNetworkError(e: unknown): boolean {
  if (typeof navigator !== "undefined" && navigator.onLine === false) return true;
  if (e instanceof TypeError) return true;
  const m = e instanceof Error ? e.message : String(e);
  return /failed to fetch|networkerror|network request failed|load failed|could not reach|cannot reach|unreachable|connection refused|econnrefused|err_connection|server is not responding/i.test(m);
}

export function enqueue(kind: Kind, payload: Record<string, unknown>, client_uuid: string, label = "") {
  const q = read();
  if (q.some((i) => i.client_uuid === client_uuid)) return; // same item pressed twice
  q.push({ client_uuid, kind, payload, created_at: new Date().toISOString(), attempts: 0, status: "pending", label });
  write(q);
}

export function discardItem(client_uuid: string) { write(read().filter((i) => i.client_uuid !== client_uuid)); }
export function retryErrors() { write(read().map((i) => (i.status === "error" ? { ...i, status: "pending", message: undefined } : i))); }

/** Sends waiting items in order. Returns false if the server could not be reached. */
export async function flushQueue(): Promise<boolean> {
  if (flushing) return true;
  flushing = true;
  try {
    for (let guard = 0; guard < 100; guard++) {
      const waiting = read().filter((i) => i.status === "pending").slice(0, 20);
      if (!waiting.length) return true;
      let results: PushResult[];
      try {
        results = (await api<{ results: PushResult[] }>("/sync/push", {
          method: "POST", body: { items: waiting.map((i) => ({ client_uuid: i.client_uuid, kind: i.kind, payload: i.payload })) },
        })).results;
      } catch (e) {
        write(read().map((i) => (waiting.some((w) => w.client_uuid === i.client_uuid) ? { ...i, attempts: i.attempts + 1 } : i)));
        if (isNetworkError(e)) return false;
        // server answered with an error for the whole batch (e.g. logged out): keep items, try later
        return false;
      }
      const done = new Set(results.filter((r) => r.status === "saved" || r.status === "duplicate").map((r) => r.client_uuid));
      const bad = new Map(results.filter((r) => r.status === "error").map((r) => [r.client_uuid, r.message]));
      write(read().filter((i) => !done.has(i.client_uuid)).map((i) => (bad.has(i.client_uuid) ? { ...i, status: "error" as const, message: bad.get(i.client_uuid) } : i)));
      if (results.some((r) => r.status === "retry")) return true; // try again on the next round
    }
    return true;
  } finally {
    flushing = false;
  }
}

let started = false;
export function startAutoSync() {
  if (started || typeof window === "undefined") return;
  started = true;
  const run = () => { flushQueue(); };
  window.addEventListener("online", run);
  setInterval(run, 15000);
  run();
}

export type Submitted<T> = { queued: false; result: T } | { queued: true };

/**
 * Saves a record. Online -> saved at once. Server unreachable -> kept in the queue and sent later.
 * A normal server refusal (not enough stock, credit limit...) is thrown as an Error and NOT queued.
 */
export async function submitOrQueue<T = Record<string, unknown>>(
  kind: Kind, body: Record<string, unknown>, client_uuid: string, label = ""
): Promise<Submitted<T>> {
  try {
    if (kind === "sale") return { queued: false, result: await api<T>("/sales", { method: "POST", body: { ...body, client_uuid } }) };
    if (kind === "customer_payment") {
      const { customer_id, ...rest } = body;
      return { queued: false, result: await api<T>(`/customers/${customer_id}/payments`, { method: "POST", body: { ...rest, client_uuid } }) };
    }
    const r = (await api<{ results: PushResult[] }>("/sync/push", { method: "POST", body: { items: [{ client_uuid, kind, payload: body }] } })).results[0];
    if (r.status === "error" || r.status === "retry") throw new Error(r.message || "Could not save. Please try again.");
    return { queued: false, result: r as unknown as T };
  } catch (e) {
    if (isNetworkError(e)) { enqueue(kind, body, client_uuid, label); return { queued: true }; }
    throw e;
  }
}
