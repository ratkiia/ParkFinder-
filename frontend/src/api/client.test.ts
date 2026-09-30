import { afterEach, describe, expect, it, vi } from "vitest";

import { errorResponse, jsonResponse, makeResponse } from "../test/fixtures";
import { ApiError, fetchPark, fetchParksByCity, fetchParksInBounds, getJson, isAbortError } from "./client";

function mockFetch(impl: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>) {
  const fn = vi.fn(impl);
  vi.stubGlobal("fetch", fn);
  return fn;
}

async function expectApiError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError);
    return error as ApiError;
  }
  throw new Error("expected promise to reject");
}

afterEach(() => vi.useRealTimers());

describe("api client", () => {
  it("builds the by-city URL with an encoded query", async () => {
    const fetchFn = mockFetch(async () => jsonResponse(makeResponse([])));
    await fetchParksByCity("St. Louis, MO");
    expect(String(fetchFn.mock.calls[0][0])).toBe("/api/v1/parks/by-city?city=St.+Louis%2C+MO");
  });

  it("rounds viewport coordinates", async () => {
    const fetchFn = mockFetch(async () => jsonResponse(makeResponse([])));
    await fetchParksInBounds({ south: 30.123456789, west: -97.1, north: 30.2, east: -97.0 });
    expect(String(fetchFn.mock.calls[0][0])).toContain("south=30.12346");
  });

  it("encodes park ids in the path", async () => {
    const fetchFn = mockFetch(async () => jsonResponse({}));
    await fetchPark("a/b");
    expect(String(fetchFn.mock.calls[0][0])).toBe("/api/v1/parks/a%2Fb");
  });

  it("maps 429 to a friendly message with Retry-After", async () => {
    mockFetch(async () => errorResponse(429, "rate_limited", "Too many requests.", { "Retry-After": "12" }));
    const error = await expectApiError(fetchParksByCity("Austin"));
    expect(error.status).toBe(429);
    expect(error.code).toBe("rate_limited");
    expect(error.retryAfter).toBe(12);
    expect(error.message).toContain("12 seconds");
  });

  it("maps 422 validation errors", async () => {
    mockFetch(async () => errorResponse(422, "validation_error", "The request parameters are invalid."));
    const error = await expectApiError(fetchParksByCity("x"));
    expect(error.status).toBe(422);
    expect(error.message).toBe("Please check your search and try again.");
  });

  it("keeps a specific 422 message from the server", async () => {
    mockFetch(async () => errorResponse(422, "invalid_request", "Requested area is too large."));
    const error = await expectApiError(fetchParksByCity("x"));
    expect(error.message).toBe("Requested area is too large.");
  });

  it("hides internal details on 500", async () => {
    mockFetch(async () => errorResponse(500, "internal_error", "Traceback: secret"));
    const error = await expectApiError(fetchParksByCity("Austin"));
    expect(error.status).toBe(500);
    expect(error.message).not.toContain("secret");
  });

  it("uses the server message on 503", async () => {
    mockFetch(async () => errorResponse(503, "service_unavailable", "Park data is temporarily unavailable."));
    const error = await expectApiError(fetchParksByCity("Austin"));
    expect(error.message).toBe("Park data is temporarily unavailable.");
  });

  it("handles non-JSON error bodies", async () => {
    mockFetch(async () => new Response("<html>Bad Gateway</html>", { status: 502 }));
    const error = await expectApiError(fetchParksByCity("Austin"));
    expect(error.code).toBe("http_502");
    expect(error.message).toMatch(/temporarily unavailable/);
  });

  it("handles invalid JSON in a successful response", async () => {
    mockFetch(async () => new Response("not json", { status: 200 }));
    const error = await expectApiError(fetchParksByCity("Austin"));
    expect(error.code).toBe("invalid_response");
  });

  it("maps network failures", async () => {
    mockFetch(async () => {
      throw new TypeError("Failed to fetch");
    });
    const error = await expectApiError(fetchParksByCity("Austin"));
    expect(error.code).toBe("network_error");
  });

  it("rethrows caller aborts as AbortError (not an ApiError)", async () => {
    mockFetch(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
        }),
    );
    const controller = new AbortController();
    const promise = fetchParksByCity("Austin", controller.signal);
    controller.abort();
    await expect(promise).rejects.toSatisfy(isAbortError);
  });

  it("times out slow requests", async () => {
    vi.useFakeTimers();
    mockFetch(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
        }),
    );
    const promise = getJson("/slow", {}, { timeoutMs: 1000 });
    const assertion = expect(promise).rejects.toMatchObject({ code: "timeout" });
    await vi.advanceTimersByTimeAsync(1001);
    await assertion;
  });
});
