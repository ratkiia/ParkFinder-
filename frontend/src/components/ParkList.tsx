import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import type { Park } from "../api/types";

interface ParkListProps {
  parks: Park[];
  selectedId: string | null;
  onSelect: (park: Park) => void;
  /** Park to move keyboard focus to when the list mounts (e.g. after closing details). */
  focusId?: string | null;
  busy?: boolean;
}

/**
 * Keyboard pattern: Tab enters/leaves the list at one item (roving tabindex);
 * Arrow Up/Down, Home and End move between parks; Enter or Space opens a park.
 */
export function ParkList({ parks, selectedId, onSelect, focusId = null, busy = false }: ParkListProps) {
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const selectedIndex = parks.findIndex((p) => p.id === selectedId);
  const [activeIndex, setActiveIndex] = useState(Math.max(0, selectedIndex));

  // Keep the roving index valid when results change.
  const safeActive = activeIndex < parks.length ? activeIndex : 0;

  useEffect(() => {
    if (!focusId) return;
    const index = parks.findIndex((p) => p.id === focusId);
    if (index >= 0) {
      setActiveIndex(index);
      itemRefs.current[index]?.focus();
    }
    // Only on mount / when a new focus target is requested, not on every results update.
  }, [focusId]);

  function moveFocus(index: number) {
    setActiveIndex(index);
    itemRefs.current[index]?.focus();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const last = parks.length - 1;
    const next =
      event.key === "ArrowDown" ? Math.min(index + 1, last)
      : event.key === "ArrowUp" ? Math.max(index - 1, 0)
      : event.key === "Home" ? 0
      : event.key === "End" ? last
      : null;
    if (next !== null) {
      event.preventDefault();
      moveFocus(next);
    }
  }

  if (parks.length === 0) return null;

  return (
    <ul aria-label="Parks" aria-busy={busy || undefined} className="flex flex-col gap-2 p-3">
      {parks.map((park, index) => {
        const selected = park.id === selectedId;
        return (
          <li key={park.id}>
            <button
              ref={(el) => {
                itemRefs.current[index] = el;
              }}
              type="button"
              tabIndex={index === safeActive ? 0 : -1}
              aria-current={selected ? "true" : undefined}
              onClick={() => onSelect(park)}
              onFocus={() => setActiveIndex(index)}
              onKeyDown={(e) => handleKeyDown(e, index)}
              className={`focus-ring flex w-full flex-col items-start gap-0.5 rounded-md border-2 bg-white px-3 py-2 text-left hover:bg-emerald-50 ${
                selected ? "border-slate-900 border-l-8" : "border-slate-200"
              }`}
            >
              <span className="flex w-full items-start justify-between gap-2">
                <span className="font-semibold">{park.name}</span>
                {selected && (
                  <span className="shrink-0 rounded bg-slate-900 px-1.5 py-0.5 text-xs font-bold text-white">
                    <span aria-hidden="true">✓ </span>Selected
                  </span>
                )}
              </span>
              <span className="text-sm text-slate-700">{park.location.address ?? "Address not available"}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
