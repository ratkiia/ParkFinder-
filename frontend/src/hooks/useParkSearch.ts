import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, fetchParksByCity, fetchParksInBounds, isAbortError } from "../api/client";
import type { Bounds, ParksResponse } from "../api/types";
import { boundsKey } from "../utils/format";

export type SearchQuery = { kind: "city"; city: string } | { kind: "bounds"; bounds: Bounds };

export interface SearchState {
  status: "idle" | "loading" | "success" | "error";
  data: ParksResponse | null;
  error: ApiError | null;
  query: SearchQuery | null;
}

const initialState: SearchState = { status: "idle", data: null, error: null, query: null };

function queryKey(query: SearchQuery): string {
  return query.kind === "city" ? `city:${query.city.trim().toLowerCase()}` : `bounds:${boundsKey(query.bounds)}`;
}

/**
 * Runs park searches with request hygiene:
 * - a new search aborts the previous in-flight request (latest wins);
 * - an identical viewport search is skipped instead of re-sent;
 * - previous results stay visible while loading, so the UI never goes blank.
 */
export function useParkSearch() {
  const [state, setState] = useState<SearchState>(initialState);
  const controllerRef = useRef<AbortController | null>(null);
  const lastKeyRef = useRef<string | null>(null);

  const run = useCallback(async (query: SearchQuery, force: boolean) => {
    const key = queryKey(query);
    if (!force && key === lastKeyRef.current) return;
    lastKeyRef.current = key;

    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setState((s) => ({ ...s, status: "loading", error: null, query }));

    try {
      const data =
        query.kind === "city"
          ? await fetchParksByCity(query.city, controller.signal)
          : await fetchParksInBounds(query.bounds, controller.signal);
      if (controller.signal.aborted) return;
      setState({ status: "success", data, error: null, query });
    } catch (error) {
      if (controller.signal.aborted || isAbortError(error)) return;
      lastKeyRef.current = null; // allow the same search to be retried
      const apiError =
        error instanceof ApiError ? error : new ApiError(0, "unknown", "Something went wrong. Please try again.");
      // Keep the last list while panning; a failed *city* search must not show another city's parks.
      setState((s) => ({ ...s, status: "error", error: apiError, data: query.kind === "city" ? null : s.data }));
    }
  }, []);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const searchCity = useCallback((city: string) => run({ kind: "city", city }, true), [run]);
  const searchBounds = useCallback((bounds: Bounds) => run({ kind: "bounds", bounds }, false), [run]);
  const retry = useCallback(() => {
    if (state.query) void run(state.query, true);
  }, [run, state.query]);

  return { ...state, searchCity, searchBounds, retry };
}
