/** Mirrors the backend Pydantic models (backend/app/models.py). */

export interface Location {
  lat: number;
  lng: number;
  address: string | null;
}

export interface Park {
  id: string;
  name: string;
  description: string | null;
  location: Location;
  amenities: string[];
  hours: string | null;
  images: string[];
  acreage: number | null;
  rating: number | null;
  website: string | null;
  source: "openstreetmap" | "sample";
}

export interface Bounds {
  south: number;
  west: number;
  north: number;
  east: number;
}

export interface ResolvedArea {
  label: string;
  bbox: Bounds;
  center: { lat: number; lng: number };
}

export interface ParksResponse {
  parks: Park[];
  count: number;
  area: ResolvedArea | null;
  sources: Array<Park["source"]>;
  degraded: boolean;
  warnings: string[];
  attribution: string;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    request_id?: string | null;
    details?: Array<{ field: string; message: string }>;
  };
}
