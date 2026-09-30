import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";

import type { Bounds, Park } from "./api/types";
import { ParkDetails } from "./components/ParkDetails";
import { ParkList } from "./components/ParkList";
import { SearchBar } from "./components/SearchBar";
import { StatusBanner } from "./components/StatusBanner";
import { useParkSearch } from "./hooks/useParkSearch";
import { boundsSpan } from "./utils/format";

// Leaflet is the heaviest dependency; load it separately so the list is usable immediately.
const ParkMap = lazy(() => import("./components/ParkMap"));

/** Must match the backend's max_bbox_span_deg; larger viewports are not requested. */
export const MAX_VIEWPORT_SPAN_DEG = 1.0;

type MobileView = "list" | "map";

export default function App() {
  const search = useParkSearch();
  const [selected, setSelected] = useState<Park | null>(null);
  const [restoreFocusId, setRestoreFocusId] = useState<string | null>(null);
  const [fitBounds, setFitBounds] = useState<Bounds | null>(null);
  const [followMap, setFollowMap] = useState(true);
  const [mapHint, setMapHint] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [mobileView, setMobileView] = useState<MobileView>("list");

  const parks = useMemo(() => search.data?.parks ?? [], [search.data]);
  const visibleParks = useMemo(() => {
    const term = filter.trim().toLowerCase();
    return term ? parks.filter((p) => p.name.toLowerCase().includes(term)) : parks;
  }, [parks, filter]);

  // Fit the map to a city only when a *city* search succeeds (not after viewport searches).
  useEffect(() => {
    if (search.status === "success" && search.query?.kind === "city" && search.data?.area) {
      setFitBounds(search.data.area.bbox);
    }
  }, [search.status, search.query, search.data]);

  const handleCitySearch = useCallback(
    (city: string) => {
      setSelected(null);
      setRestoreFocusId(null);
      setMapHint(null);
      setFilter("");
      void search.searchCity(city);
    },
    [search],
  );

  const handleBoundsChange = useCallback(
    (bounds: Bounds) => {
      if (!followMap) return;
      if (boundsSpan(bounds) > MAX_VIEWPORT_SPAN_DEG) {
        setMapHint("Zoom in on the map to load parks for that area.");
        return;
      }
      setMapHint(null);
      void search.searchBounds(bounds);
    },
    [followMap, search],
  );

  const handleSelect = useCallback((park: Park) => {
    setSelected(park);
    setMobileView("list"); // details live in the list panel
  }, []);

  const handleBack = useCallback(() => {
    setRestoreFocusId(selected?.id ?? null);
    setSelected(null);
  }, [selected]);

  const summary = useMemo(() => {
    if (search.status === "idle") return "Enter a US city to find its parks.";
    if (!search.data || search.status === "error") return null;
    const { count, area } = search.data;
    const where = area ? ` in ${area.label}` : "";
    if (count === 0) return `No parks found${where}.`;
    return `${count} park${count === 1 ? "" : "s"} found${where}.`;
  }, [search.status, search.data]);

  const loading = search.status === "loading";

  return (
    <div className="flex h-dvh flex-col">
      <a
        href="#results"
        className="focus-ring sr-only z-[2000] rounded bg-white px-3 py-2 font-semibold focus:not-sr-only focus:absolute focus:left-2 focus:top-2"
      >
        Skip to park results
      </a>

      <header className="flex flex-col gap-3 border-b-2 border-slate-200 bg-white px-4 py-3 md:flex-row md:items-end md:justify-between">
        <h1 className="text-2xl font-bold text-emerald-900">
          <span aria-hidden="true">🌳 </span>ParkFinder
        </h1>
        <SearchBar onSearch={handleCitySearch} busy={loading && search.query?.kind === "city"} />
      </header>

      <div className="flex gap-2 border-b border-slate-200 bg-white px-4 py-2 md:hidden" role="group" aria-label="View">
        {(["list", "map"] as const).map((view) => (
          <button
            key={view}
            type="button"
            aria-pressed={mobileView === view}
            onClick={() => setMobileView(view)}
            className="focus-ring flex-1 rounded-md border-2 border-slate-400 px-3 py-1 font-semibold aria-pressed:border-slate-900 aria-pressed:bg-slate-900 aria-pressed:text-white"
          >
            {view === "list" ? "List" : "Map"}
          </button>
        ))}
      </div>

      <main className="flex min-h-0 flex-1">
        <section
          id="results"
          tabIndex={-1}
          aria-label="Park results"
          className={`${mobileView === "list" ? "flex" : "hidden"} w-full flex-col overflow-y-auto bg-slate-50 md:flex md:w-[26rem] md:border-r-2 md:border-slate-200`}
        >
          <StatusBanner
            loading={loading}
            error={search.error}
            warnings={search.data?.warnings ?? []}
            summary={summary}
            hint={mapHint}
            onRetry={search.retry}
          />

          {selected ? (
            <ParkDetails park={selected} onBack={handleBack} />
          ) : (
            <>
              {parks.length > 5 && (
                <div className="px-3 pt-3">
                  <label htmlFor="park-filter" className="text-sm font-semibold">
                    Filter by name
                  </label>
                  <input
                    id="park-filter"
                    type="search"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    className="focus-ring mt-1 w-full rounded-md border-2 border-slate-400 bg-white px-3 py-1.5"
                  />
                  {filter && (
                    <p className="mt-1 text-xs text-slate-600" aria-live="polite">
                      Showing {visibleParks.length} of {parks.length}
                    </p>
                  )}
                </div>
              )}
              <ParkList
                parks={visibleParks}
                selectedId={null}
                onSelect={handleSelect}
                focusId={restoreFocusId}
                busy={loading}
              />
            </>
          )}
        </section>

        <section
          aria-label="Park map"
          className={`${mobileView === "map" ? "flex" : "hidden"} relative min-h-0 flex-1 flex-col md:flex`}
        >
          <div className="flex items-center gap-2 border-b border-slate-200 bg-white px-3 py-2 text-sm">
            <input
              id="follow-map"
              type="checkbox"
              checked={followMap}
              onChange={(e) => setFollowMap(e.target.checked)}
              className="focus-ring h-4 w-4 accent-emerald-800"
            />
            <label htmlFor="follow-map">Update results when the map moves</label>
          </div>
          <div className="relative min-h-0 flex-1" role="region" aria-label="Interactive map. Arrow keys pan, plus and minus zoom.">
            <Suspense fallback={<p className="p-4 text-sm">Loading map…</p>}>
              <ParkMap
                parks={parks}
                selectedId={selected?.id ?? null}
                fitBounds={fitBounds}
                onSelect={handleSelect}
                onBoundsChange={handleBoundsChange}
              />
            </Suspense>
          </div>
        </section>
      </main>

      <footer className="border-t border-slate-200 bg-white px-4 py-1 text-xs text-slate-600">
        {search.data?.attribution ?? "Park data © OpenStreetMap contributors (ODbL)"}
      </footer>
    </div>
  );
}
