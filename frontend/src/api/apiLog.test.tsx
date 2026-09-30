import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StatusBanner } from "../components/StatusBanner";
import { errorResponse, jsonResponse, makeResponse } from "../test/fixtures";
import { clearApiLog, getApiLog, newRequestId } from "./apiLog";
import { ApiError, fetchParksByCity, getJson, REQUEST_ID_HEADER } from "./client";

beforeEach(() => clearApiLog());

function headerSent(fetchFn: ReturnType<typeof vi.fn>, call = 0): string | undefined {
  const init = fetchFn.mock.calls[call][1] as RequestInit;
  return (init.headers as Record<string, string>)[REQUEST_ID_HEADER];
}

describe("request ids", () => {
  it("generates ids the backend accepts", () => {
    const id = newRequestId();
    expect(id).toMatch(/^[A-Za-z0-9._-]{8,64}$/);
    expect(newRequestId()).not.toBe(id);
  });

  it("sends a unique X-Request-ID per call", async () => {
    const fetchFn = vi.fn(async () => jsonResponse(makeResponse([])));
    vi.stubGlobal("fetch", fetchFn);
    await fetchParksByCity("Austin");
    await fetchParksByCity("Austin");
    expect(headerSent(fetchFn, 0)).toMatch(/^web-/);
    expect(headerSent(fetchFn, 0)).not.toBe(headerSent(fetchFn, 1));
  });

  it("attaches the server's request id to errors", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      jsonResponse({ error: { code: "internal_error", message: "x", request_id: "server-id-123" } }, 500)));
    const error = (await fetchParksByCity("Austin").catch((e) => e)) as ApiError;
    expect(error.requestId).toBe("server-id-123");
  });

  it("falls back to the response header, then to the sent id", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response("<html>502</html>", { status: 502, headers: { [REQUEST_ID_HEADER]: "header-id-456" } })));
    expect(((await fetchParksByCity("A b").catch((e) => e)) as ApiError).requestId).toBe("header-id-456");

    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("offline");
    }));
    const offline = (await fetchParksByCity("A b").catch((e) => e)) as ApiError;
    expect(offline.requestId).toMatch(/^web-/);
  });
});

describe("client API log", () => {
  it("records successful and failed calls with status, duration and id", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(jsonResponse(makeResponse([]), 200, { [REQUEST_ID_HEADER]: "srv-ok-0001" }))
      .mockResolvedValueOnce(errorResponse(429, "rate_limited", "slow")));
    await fetchParksByCity("Austin");
    await fetchParksByCity("Austin").catch(() => undefined);

    const [ok, limited] = getApiLog();
    expect(ok).toMatchObject({ method: "GET", status: 200, outcome: "success", requestId: "srv-ok-0001" });
    expect(ok.url).toContain("/api/v1/parks/by-city?city=Austin");
    expect(ok.durationMs).toBeGreaterThanOrEqual(0);
    expect(limited).toMatchObject({ status: 429, outcome: "error" });
  });

  it("records aborted, timed-out and network-failed calls", async () => {
    vi.useFakeTimers();
    const hang = (_: string, init: RequestInit) =>
      new Promise<Response>((_resolve, reject) =>
        init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError"))));
    vi.stubGlobal("fetch", vi.fn(hang));

    const controller = new AbortController();
    const aborted = getJson("/a", {}, { signal: controller.signal }).catch(() => undefined);
    controller.abort();
    await aborted;

    const slow = getJson("/b", {}, { timeoutMs: 100 }).catch(() => undefined);
    await vi.advanceTimersByTimeAsync(101);
    await slow;
    vi.useRealTimers();

    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("offline");
    }));
    await getJson("/c").catch(() => undefined);

    expect(getApiLog().map((e) => e.outcome)).toEqual(["aborted", "timeout", "network_error"]);
  });

  it("keeps only the most recent 50 entries", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({})));
    for (let i = 0; i < 55; i += 1) await getJson(`/n/${i}`);
    const log = getApiLog();
    expect(log).toHaveLength(50);
    expect(log[0].url).toBe("/n/5");
  });

  it("is exposed on window for DevTools", () => {
    expect((window as unknown as { __parkfinderApiLog: unknown }).__parkfinderApiLog).toEqual([]);
  });
});

describe("StatusBanner reference id", () => {
  it("shows the reference id so users can report problems", () => {
    render(
      <StatusBanner
        loading={false}
        warnings={[]}
        summary={null}
        hint={null}
        onRetry={vi.fn()}
        error={new ApiError(500, "internal_error", "Something went wrong.", null, "ref-abc-123")}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Reference ID: ref-abc-123");
  });
});
