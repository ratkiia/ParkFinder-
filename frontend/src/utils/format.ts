import type { Bounds } from "../api/types";

/** "dog-run" -> "Dog run" */
export function formatAmenity(value: string): string {
  const words = value.replace(/[-_]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : value;
}

export function formatAcreage(acres: number): string {
  return `${acres.toLocaleString("en-US", { maximumFractionDigits: 1 })} acres`;
}

export function formatSource(source: "openstreetmap" | "sample"): string {
  return source === "openstreetmap" ? "OpenStreetMap" : "Sample dataset";
}

/** Stable key used to skip duplicate viewport requests (≈100 m precision). */
export function boundsKey(bounds: Bounds): string {
  return [bounds.south, bounds.west, bounds.north, bounds.east].map((n) => n.toFixed(3)).join(",");
}

export function boundsSpan(bounds: Bounds): number {
  return Math.max(bounds.north - bounds.south, bounds.east - bounds.west);
}
