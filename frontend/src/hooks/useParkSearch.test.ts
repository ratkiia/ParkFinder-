import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { errorResponse, jsonResponse, makePark, makeResponse } from "../test/fixtures";
import { useParkSearch } from "./useParkSearch";

const BOUNDS = { south: 30.2, west: -97.8, north: 30.3, east: -97.7 };

describe("useParkSearch", () => {
  it("loads parks for a city", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(makeResponse([makePark()]))));
    const { result } = renderHook(() => useParkSearch());
    expect(result.current.status).toBe("idle");

    act(() => void result.current.searchCity("Brooklyn"));
    expect(result.current.status).toBe("loading");
    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(result.current.data?.parks[0].name).toBe("Prospect Park");
  });

  it("aborts the previous request when a new search starts (latest wins)", async () => {
    const signals: AbortSignal[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit) => {
        signals.push(init.signal as AbortSignal);
        const city = new URL(`http://x${_url}`).searchParams.get("city");
        return new Promise<Response>((resolve, reject) => {
          init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
          setTimeout(() => resolve(jsonResponse(makeResponse([makePark({ name: `${city} Park` })]))), 20);
        });
      }),
    );
    const { result } = renderHook(() => useParkSearch());
    act(() => {
      void result.current.searchCity("Austin");
      void result.current.searchCity("Denver");
    });
    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(signals[0].aborted).toBe(true);
    expect(result.current.data?.parks[0].name).toBe("Denver Park");
    expect(result.current.error).toBeNull();
  });

  it("skips duplicate viewport requests", async () => {
    const fetchFn = vi.fn(async () => jsonResponse(makeResponse([])));
    vi.stubGlobal("fetch", fetchFn);
    const { result } = renderHook(() => useParkSearch());
    act(() => void result.current.searchBounds(BOUNDS));
    await waitFor(() => expect(result.current.status).toBe("success"));
    act(() => void result.current.searchBounds({ ...BOUNDS, south: 30.20001 }));
    expect(fetchFn).toHaveBeenCalledTimes(1);
  });

  it("exposes errors and allows retry", async () => {
    const fetchFn = vi
      .fn()
      .mockResolvedValueOnce(errorResponse(503, "service_unavailable", "Down"))
      .mockResolvedValueOnce(jsonResponse(makeResponse([makePark()])));
    vi.stubGlobal("fetch", fetchFn);
    const { result } = renderHook(() => useParkSearch());

    act(() => void result.current.searchCity("Austin"));
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.status).toBe(503);
    expect(result.current.data).toBeNull();

    act(() => result.current.retry());
    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(fetchFn).toHaveBeenCalledTimes(2);
  });

  it("keeps previous results when a viewport search fails", async () => {
    const fetchFn = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(makeResponse([makePark()])))
      .mockResolvedValueOnce(errorResponse(429, "rate_limited", "Slow down", { "Retry-After": "5" }));
    vi.stubGlobal("fetch", fetchFn);
    const { result } = renderHook(() => useParkSearch());

    act(() => void result.current.searchCity("Brooklyn"));
    await waitFor(() => expect(result.current.status).toBe("success"));
    act(() => void result.current.searchBounds(BOUNDS));
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error?.status).toBe(429);
    expect(result.current.data?.parks).toHaveLength(1);
  });
});
