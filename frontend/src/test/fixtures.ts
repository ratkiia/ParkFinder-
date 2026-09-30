import type { Park, ParksResponse } from "../api/types";

export function makePark(overrides: Partial<Park> = {}): Park {
  return {
    id: "prospect-park",
    name: "Prospect Park",
    description: "A 526-acre park in the heart of Brooklyn...",
    location: { lat: 40.6602, lng: -73.969, address: "Brooklyn, NY 11225" },
    amenities: ["playground", "dog-run"],
    hours: "6:00 AM - 1:00 AM",
    images: ["https://example.com/prospect-1.jpg"],
    acreage: 526,
    rating: 4.7,
    website: null,
    source: "sample",
    ...overrides,
  };
}

/** A park with every optional field missing. */
export function barePark(overrides: Partial<Park> = {}): Park {
  return makePark({
    id: "osm-way-1",
    name: "Bare Park",
    description: null,
    location: { lat: 30.2, lng: -97.7, address: null },
    amenities: [],
    hours: null,
    images: [],
    acreage: null,
    rating: null,
    source: "openstreetmap",
    ...overrides,
  });
}

export function makeResponse(parks: Park[], overrides: Partial<ParksResponse> = {}): ParksResponse {
  return {
    parks,
    count: parks.length,
    area: {
      label: "Austin, Texas, United States",
      bbox: { south: 30.1, west: -97.9, north: 30.5, east: -97.6 },
      center: { lat: 30.3, lng: -97.75 },
    },
    sources: ["openstreetmap"],
    degraded: false,
    warnings: [],
    attribution: "Park data © OpenStreetMap contributors (ODbL)",
    ...overrides,
  };
}

export function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

export function errorResponse(status: number, code: string, message: string, headers: Record<string, string> = {}) {
  return jsonResponse({ error: { code, message } }, status, headers);
}
