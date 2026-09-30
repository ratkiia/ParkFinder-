import { describe, expect, it } from "vitest";

import { boundsKey, boundsSpan, formatAcreage, formatAmenity, formatSource } from "./format";
import { validateCity } from "./validation";

describe("format", () => {
  it.each([
    ["dog-run", "Dog run"],
    ["drinking_water", "Drinking water"],
    ["restrooms", "Restrooms"],
    ["", ""],
  ])("formatAmenity(%s) = %s", (input, expected) => {
    expect(formatAmenity(input)).toBe(expected);
  });

  it("formats acreage and source", () => {
    expect(formatAcreage(1017)).toBe("1,017 acres");
    expect(formatAcreage(24.55)).toBe("24.6 acres");
    expect(formatSource("openstreetmap")).toBe("OpenStreetMap");
    expect(formatSource("sample")).toBe("Sample dataset");
  });

  it("boundsKey ignores sub-100m jitter", () => {
    const a = boundsKey({ south: 30.10001, west: -97.9, north: 30.5, east: -97.6 });
    const b = boundsKey({ south: 30.10004, west: -97.9, north: 30.5, east: -97.6 });
    expect(a).toBe(b);
  });

  it("boundsSpan returns the larger side", () => {
    expect(boundsSpan({ south: 30, west: -98, north: 30.5, east: -96 })).toBe(2);
  });
});

describe("validateCity", () => {
  it.each(["Austin", "Austin, TX", "St. Louis", "Coeur d'Alene", "Winston-Salem", "Cañon City"])("accepts %s", (city) => {
    expect(validateCity(city)).toBeNull();
  });

  it.each([
    ["", /Enter a US city/],
    ["   ", /Enter a US city/],
    ["A", /at least 2/],
    ["x".repeat(101), /100 characters/],
    ["<script>", /letters/],
    ["12345", /letters/],
    ["Austin; DROP", /letters/],
  ])("rejects %j", (city, message) => {
    expect(validateCity(city)).toMatch(message);
  });
});
