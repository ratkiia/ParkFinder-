/**
 * Thin, typed wrapper around the ParkFinder backend.
 *
 * - Every call accepts an AbortSignal so outdated requests can be cancelled.
 * - Requests time out on the client as well, so the UI never waits forever.
 * - Failures surface as ApiError with a user-friendly message.
 * - Every call sends an X-Request-ID and is recorded in the client API log (see apiLog.ts).
 */
import { logApiCall, newRequestId, type ApiLogEntry } from "./apiLog";
import type { ApiErrorBody, Bounds, Park, ParksResponse } from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const DEFAULT_TIMEOUT_MS = 30_000;
export const REQUEST_ID_HEADER = "X-Request-ID";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfter: number | null;
  /** Reference shown to users; matches the backend log entries for this call. */
  readonly requestId: string | null;

  constructor(status: number, code: string, message: string, retryAfter: number | null = null, requestId: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
    this.requestId = requestId;
  }
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException ? error.name === "AbortError" : (error as Error)?.name === "AbortError";
}

function friendlyMessage(status: number, serverMessage: string | undefined, retryAfter: number | null): string {
  switch (status) {
    case 404:
      return serverMessage ?? "Nothing was found for that search.";
    case 422:
      return serverMessage && serverMessage !== "The request parameters are invalid."
        ? serverMessage
        : "Please check your search and try again.";
    case 429:
      return `Too many requests. Please wait${retryAfter ? ` ${retryAfter} seconds` : " a moment"} and try again.`;
    case 502:
    case 503:
    case 504:
      return serverMessage ?? "The park data service is temporarily unavailable. Please try again shortly.";
    default:
      return "Something went wrong on our side. Please try again later.";
  }
}

async function parseError(response: Response, requestId: string): Promise<ApiError> {
  const retryHeader = response.headers.get("Retry-After");
  const retryAfter = retryHeader && /^\d+$/.test(retryHeader) ? Number(retryHeader) : null;
  let body: Partial<ApiErrorBody> | null = null;
  try {
    body = (await response.json()) as Partial<ApiErrorBody>;
  } catch {
    body = null; // non-JSON error page (e.g. a proxy); fall back to a generic message
  }
  const code = body?.error?.code ?? `http_${response.status}`;
  return new ApiError(
    response.status,
    code,
    friendlyMessage(response.status, body?.error?.message, retryAfter),
    retryAfter,
    body?.error?.request_id ?? requestId,
  );
}

/** Link an external abort signal with a timeout. */
function withTimeout(signal: AbortSignal | undefined, timeoutMs: number) {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const onAbort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener("abort", onAbort, { once: true });
  return {
    signal: controller.signal,
    didTimeOut: () => timedOut,
    dispose: () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
    },
  };
}

export async function getJson<T>(
  path: string,
  params: Record<string, string | number> = {},
  options: { signal?: AbortSignal; timeoutMs?: number } = {},
): Promise<T> {
  const query = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString();
  const url = `${API_BASE}${path}${query ? `?${query}` : ""}`;
  const linked = withTimeout(options.signal, options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  // The server echoes a valid id back; otherwise it assigns its own and returns it in the header.
  let requestId = newRequestId();
  const started = performance.now();
  const record = (outcome: ApiLogEntry["outcome"], status: number | null) =>
    logApiCall({
      requestId,
      method: "GET",
      url,
      status,
      outcome,
      durationMs: Math.round(performance.now() - started),
      timestamp: new Date().toISOString(),
    });

  try {
    let response: Response;
    try {
      response = await fetch(url, {
        headers: { Accept: "application/json", [REQUEST_ID_HEADER]: requestId },
        signal: linked.signal,
      });
    } catch (error) {
      if (isAbortError(error)) {
        if (linked.didTimeOut()) {
          record("timeout", null);
          throw new ApiError(0, "timeout", "The request took too long. Please try again.", null, requestId);
        }
        record("aborted", null);
        throw error; // cancelled by the caller: not an error worth showing
      }
      record("network_error", null);
      throw new ApiError(0, "network_error", "Unable to reach the server. Check your connection and try again.", null, requestId);
    }
    requestId = response.headers.get(REQUEST_ID_HEADER) ?? requestId;
    if (!response.ok) {
      record("error", response.status);
      throw await parseError(response, requestId);
    }
    try {
      const data = (await response.json()) as T;
      record("success", response.status);
      return data;
    } catch {
      record("error", response.status);
      throw new ApiError(response.status, "invalid_response", "The server sent an unexpected response.", null, requestId);
    }
  } finally {
    linked.dispose();
  }
}

export function fetchParksByCity(city: string, signal?: AbortSignal): Promise<ParksResponse> {
  return getJson<ParksResponse>("/api/v1/parks/by-city", { city }, { signal });
}

export function fetchParksInBounds(bounds: Bounds, signal?: AbortSignal): Promise<ParksResponse> {
  const round = (n: number) => Number(n.toFixed(5));
  return getJson<ParksResponse>(
    "/api/v1/parks/in-bounds",
    { south: round(bounds.south), west: round(bounds.west), north: round(bounds.north), east: round(bounds.east) },
    { signal },
  );
}

export function fetchPark(id: string, signal?: AbortSignal): Promise<Park> {
  return getJson<Park>(`/api/v1/parks/${encodeURIComponent(id)}`, {}, { signal });
}
