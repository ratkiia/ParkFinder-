import L from "leaflet";
import "leaflet.markercluster";
import { useEffect, useRef, type MutableRefObject } from "react";
import { MapContainer, TileLayer, useMap, useMapEvents } from "react-leaflet";

import type { Bounds, Park } from "../api/types";

const US_CENTER: L.LatLngTuple = [39.8, -98.6];
const MOVE_DEBOUNCE_MS = 600;
/** Map moves within this window after a programmatic fit/pan are not treated as user pans. */
const PROGRAMMATIC_GRACE_MS = 1200;

interface ParkMapProps {
  parks: Park[];
  selectedId: string | null;
  /** When this changes the map fits to it (e.g. after a city search). */
  fitBounds: Bounds | null;
  onSelect: (park: Park) => void;
  /** Called (debounced) after the *user* pans or zooms. */
  onBoundsChange: (bounds: Bounds) => void;
}

function pinIcon(selected: boolean): L.DivIcon {
  // Selection is shown by size, a star glyph and a thick outline, not by colour alone.
  const size = selected ? 36 : 24;
  return L.divIcon({
    className: "park-pin",
    html: `<span class="park-pin__dot${selected ? " park-pin__dot--selected" : ""}" aria-hidden="true">${selected ? "★" : ""}</span>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function toBounds(b: L.LatLngBounds): Bounds {
  return { south: b.getSouth(), west: b.getWest(), north: b.getNorth(), east: b.getEast() };
}

type ProgrammaticRef = MutableRefObject<number>;

function ClusteredMarkers({
  parks,
  selectedId,
  onSelect,
  programmaticUntil,
}: Pick<ParkMapProps, "parks" | "selectedId" | "onSelect"> & { programmaticUntil: ProgrammaticRef }) {
  const map = useMap();
  const groupRef = useRef<L.MarkerClusterGroup | null>(null);
  const markersRef = useRef(new Map<string, L.Marker>());
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    const group = L.markerClusterGroup({ showCoverageOnHover: false, maxClusterRadius: 50, chunkedLoading: true });
    map.addLayer(group);
    groupRef.current = group;
    return () => {
      map.removeLayer(group);
      groupRef.current = null;
    };
  }, [map]);

  // Rebuild markers when the result set changes.
  useEffect(() => {
    const group = groupRef.current;
    if (!group) return;
    group.clearLayers();
    markersRef.current.clear();
    const markers = parks.map((park) => {
      const marker = L.marker([park.location.lat, park.location.lng], {
        icon: pinIcon(false),
        title: park.name,
        alt: park.name,
        keyboard: true,
        riseOnHover: true,
      });
      marker.on("click", () => onSelectRef.current(park));
      markersRef.current.set(park.id, marker);
      return marker;
    });
    group.addLayers(markers);
  }, [parks]);

  // Highlight the selected marker.
  useEffect(() => {
    markersRef.current.forEach((marker, id) => {
      const selected = id === selectedId;
      marker.setIcon(pinIcon(selected));
      marker.setZIndexOffset(selected ? 1000 : 0);
    });
    // If the selected park is hidden inside a cluster, zoom until its own marker is visible.
    const marker = selectedId ? markersRef.current.get(selectedId) : undefined;
    const group = groupRef.current;
    if (marker && group && group.getVisibleParent(marker) !== marker) {
      programmaticUntil.current = Date.now() + PROGRAMMATIC_GRACE_MS;
      group.zoomToShowLayer(marker);
    }
  }, [selectedId, parks, programmaticUntil]);

  return null;
}

function MapController({
  parks,
  selectedId,
  fitBounds,
  onBoundsChange,
  programmaticUntil,
}: Omit<ParkMapProps, "onSelect"> & { programmaticUntil: ProgrammaticRef }) {
  const map = useMap();
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const onBoundsChangeRef = useRef(onBoundsChange);
  onBoundsChangeRef.current = onBoundsChange;

  // Hidden-then-shown containers (mobile tabs) need Leaflet to re-measure.
  useEffect(() => {
    const container = map.getContainer();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(container);
    return () => observer.disconnect();
  }, [map]);

  useEffect(() => {
    if (!fitBounds) return;
    programmaticUntil.current = Date.now() + PROGRAMMATIC_GRACE_MS;
    map.fitBounds(
      [
        [fitBounds.south, fitBounds.west],
        [fitBounds.north, fitBounds.east],
      ],
      { padding: [16, 16] },
    );
  }, [map, fitBounds]);

  useEffect(() => {
    const park = parks.find((p) => p.id === selectedId);
    if (!park) return;
    const position = L.latLng(park.location.lat, park.location.lng);
    if (!map.getBounds().contains(position)) {
      programmaticUntil.current = Date.now() + PROGRAMMATIC_GRACE_MS;
      map.panTo(position);
    }
  }, [map, parks, selectedId]);

  useMapEvents({
    moveend() {
      if (Date.now() < programmaticUntil.current) return;
      clearTimeout(debounceTimer.current);
      // Debounce: rapid pans produce one request once the user stops moving.
      debounceTimer.current = setTimeout(() => onBoundsChangeRef.current(toBounds(map.getBounds())), MOVE_DEBOUNCE_MS);
    },
  });

  useEffect(() => () => clearTimeout(debounceTimer.current), []);

  return null;
}

export function ParkMap(props: ParkMapProps) {
  // Shared by both children so programmatic moves (fit, pan, cluster zoom) never trigger a viewport search.
  const programmaticUntil = useRef(0);
  return (
    <MapContainer
      center={US_CENTER}
      zoom={4}
      className="h-full w-full"
      keyboard
      worldCopyJump={false}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        maxZoom={19}
      />
      <ClusteredMarkers
        parks={props.parks}
        selectedId={props.selectedId}
        onSelect={props.onSelect}
        programmaticUntil={programmaticUntil}
      />
      <MapController
        parks={props.parks}
        selectedId={props.selectedId}
        fitBounds={props.fitBounds}
        onBoundsChange={props.onBoundsChange}
        programmaticUntil={programmaticUntil}
      />
    </MapContainer>
  );
}

export default ParkMap;
