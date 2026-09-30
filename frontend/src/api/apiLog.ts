/**
 * Client-side API call log for traceability.
 *
 * Keeps the most recent calls in memory (inspect with `window.__parkfinderApiLog` in DevTools)
 * and prints each call to the console in development builds. Each entry carries the same
 * request id the backend writes to backend/logs/api.log, so a call can be traced end to end.
 */

export interface ApiLogEntry {
  requestId: string;
  method: "GET";
  url: string;
  status: number | null;
  outcome: "success" | "error" | "aborted" | "timeout" | "network_error";
  durationMs: number;
  timestamp: string;
}

const MAX_ENTRIES = 50;
const entries: ApiLogEntry[] = [];

export function newRequestId(): string {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().replace(/-/g, "")
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
  return `web-${random}`.slice(0, 64);
}

export function logApiCall(entry: ApiLogEntry): void {
  entries.push(entry);
  if (entries.length > MAX_ENTRIES) entries.shift();
  if (import.meta.env.DEV && import.meta.env.MODE !== "test") {
    const log = entry.outcome === "success" || entry.outcome === "aborted" ? console.info : console.warn;
    log(
      `[api] ${entry.method} ${entry.url} -> ${entry.status ?? entry.outcome} (${entry.durationMs} ms) id=${entry.requestId}`,
    );
  }
}

export function getApiLog(): readonly ApiLogEntry[] {
  return entries.slice();
}

export function clearApiLog(): void {
  entries.length = 0;
}

if (typeof window !== "undefined") {
  Object.defineProperty(window, "__parkfinderApiLog", { get: getApiLog, configurable: true });
}
