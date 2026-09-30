import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Bounds, Park } from "./api/types";
import App from "./App";
import { errorResponse, jsonResponse, makePark, makeResponse } from "./test/fixtures";

// Leaflet needs a real browser; replace the map with a stub exposing the same callbacks.
vi.mock("./components/ParkMap", () => ({
  default: ({
    parks,
    selectedId,
    onSelect,
    onBoundsChange,
  }: {
    parks: Park[];
    selectedId: string | null;
    onSelect: (p: Park) => void;
    onBoundsChange: (b: Bounds) => void;
  }) => (
    <div data-testid="map">
      <span>{`markers:${parks.length}`}</span>
      <span>{`selected:${selectedId ?? "none"}`}</span>
      {parks.map((p) => (
        <button key={p.id} type="button" onClick={() => onSelect(p)}>{`marker ${p.name}`}</button>
      ))}
      <button type="button" onClick={() => onBoundsChange({ south: 30.2, west: -97.8, north: 30.3, east: -97.7 })}>
        pan small
      </button>
      <button type="button" onClick={() => onBoundsChange({ south: 25, west: -105, north: 35, east: -90 })}>
        pan huge
      </button>
    </div>
  ),
}));

const PARKS = [
  makePark({ id: "zilker", name: "Zilker Park" }),
  makePark({ id: "pease", name: "Pease Park", hours: null }),
];

async function searchFor(city: string) {
  await userEvent.type(screen.getByLabelText("US city"), city);
  await userEvent.click(screen.getByRole("button", { name: "Find parks" }));
}

describe("App", () => {
  it("shows the idle prompt", async () => {
    render(<App />);
    expect(screen.getByRole("status")).toHaveTextContent("Enter a US city");
    expect(await screen.findByTestId("map")).toBeInTheDocument();
  });

  it("searches a city and lists parks without using the map", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(makeResponse(PARKS))));
    render(<App />);
    await searchFor("Austin, TX");
    expect(await screen.findByText("2 parks found in Austin, Texas, United States.")).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Parks" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(await screen.findByText("markers:2")).toBeInTheDocument();
  });

  it("opens details from the keyboard and returns focus to the list", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(makeResponse(PARKS))));
    render(<App />);
    await searchFor("Austin");
    const list = await screen.findByRole("list", { name: "Parks" });
    const item = within(list).getByRole("button", { name: /Pease Park/ });
    item.focus();
    await userEvent.keyboard("{Enter}");

    expect(screen.getByRole("heading", { name: "Pease Park" })).toHaveFocus();
    expect(screen.getByText("Hours not available")).toBeInTheDocument();
    expect(screen.getByText("selected:pease")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Back to results/ }));
    expect(within(screen.getByRole("list", { name: "Parks" })).getByRole("button", { name: /Pease Park/ })).toHaveFocus();
  });

  it("opens details when a map marker is selected", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(makeResponse(PARKS))));
    render(<App />);
    await searchFor("Austin");
    await userEvent.click(await screen.findByRole("button", { name: "marker Zilker Park" }));
    expect(screen.getByRole("heading", { name: "Zilker Park" })).toBeInTheDocument();
  });

  it("shows an error with retry on 503, then recovers", async () => {
    const fetchFn = vi
      .fn()
      .mockResolvedValueOnce(errorResponse(503, "service_unavailable", "Park data is temporarily unavailable."))
      .mockResolvedValueOnce(jsonResponse(makeResponse(PARKS)));
    vi.stubGlobal("fetch", fetchFn);
    render(<App />);
    await searchFor("Austin");
    expect(await screen.findByRole("alert")).toHaveTextContent("Park data is temporarily unavailable.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText(/2 parks found/)).toBeInTheDocument();
  });

  it("shows a friendly message on 429", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => errorResponse(429, "rate_limited", "x", { "Retry-After": "30" })));
    render(<App />);
    await searchFor("Austin");
    expect(await screen.findByRole("alert")).toHaveTextContent("Please wait 30 seconds");
  });

  it("shows a 404 without a retry button", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => errorResponse(404, "city_not_found", "No US city matching 'Atlantis' was found.")));
    render(<App />);
    await searchFor("Atlantis");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("No US city matching 'Atlantis' was found.");
    expect(within(alert).queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows degraded-mode warnings", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(makeResponse(PARKS, {
      degraded: true,
      sources: ["sample"],
      warnings: ["Live park data is temporarily unavailable; showing sample data only."],
    }))));
    render(<App />);
    await searchFor("Austin");
    expect(await screen.findByText(/showing sample data only/)).toBeInTheDocument();
  });

  it("says so when no parks are found", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(makeResponse([]))));
    render(<App />);
    await searchFor("Austin");
    expect(await screen.findByText("No parks found in Austin, Texas, United States.")).toBeInTheDocument();
  });

  it("loads parks when the user pans, and asks to zoom in when the view is too large", async () => {
    const fetchFn = vi.fn(async (_url: string) => jsonResponse(makeResponse(PARKS, { area: null })));
    vi.stubGlobal("fetch", fetchFn);
    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: "pan huge" }));
    expect(screen.getByText(/Zoom in on the map/)).toBeInTheDocument();
    expect(fetchFn).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: "pan small" }));
    await waitFor(() => expect(fetchFn).toHaveBeenCalledTimes(1));
    expect(String(fetchFn.mock.calls[0][0])).toContain("/api/v1/parks/in-bounds?");
    expect(screen.queryByText(/Zoom in on the map/)).not.toBeInTheDocument();
  });

  it("does not follow the map when the option is turned off", async () => {
    const fetchFn = vi.fn(async () => jsonResponse(makeResponse([])));
    vi.stubGlobal("fetch", fetchFn);
    render(<App />);
    await userEvent.click(screen.getByLabelText("Update results when the map moves"));
    await userEvent.click(await screen.findByRole("button", { name: "pan small" }));
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("filters the list by name", async () => {
    const many = Array.from({ length: 7 }, (_, i) => makePark({ id: `p${i}`, name: i === 3 ? "Special Park" : `Park ${i}` }));
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(makeResponse(many))));
    render(<App />);
    await searchFor("Austin");
    await userEvent.type(await screen.findByLabelText("Filter by name"), "special");
    expect(within(screen.getByRole("list", { name: "Parks" })).getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText("Showing 1 of 7")).toBeInTheDocument();
  });

  it("provides a skip link to the results", () => {
    render(<App />);
    expect(screen.getByRole("link", { name: "Skip to park results" })).toHaveAttribute("href", "#results");
  });
});
