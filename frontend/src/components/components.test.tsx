import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { barePark, makePark } from "../test/fixtures";
import { ParkDetails } from "./ParkDetails";
import { ParkList } from "./ParkList";
import { SearchBar } from "./SearchBar";
import { StatusBanner } from "./StatusBanner";

const PARKS = [
  makePark({ id: "a", name: "Alpha Park" }),
  makePark({ id: "b", name: "Beta Park" }),
  makePark({ id: "c", name: "Gamma Park", location: { lat: 1, lng: 1, address: null } }),
];

describe("SearchBar", () => {
  it("submits a trimmed, valid city", async () => {
    const onSearch = vi.fn();
    render(<SearchBar onSearch={onSearch} />);
    await userEvent.type(screen.getByLabelText("US city"), "  Austin, TX  {Enter}");
    expect(onSearch).toHaveBeenCalledWith("Austin, TX");
  });

  it("shows an accessible error and does not submit invalid input", async () => {
    const onSearch = vi.fn();
    render(<SearchBar onSearch={onSearch} />);
    await userEvent.click(screen.getByRole("button", { name: "Find parks" }));
    expect(onSearch).not.toHaveBeenCalled();
    const input = screen.getByLabelText("US city");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent(/Enter a US city/);
    expect(input.getAttribute("aria-describedby")).toContain(screen.getByRole("alert").id);
  });

  it("rejects unsafe characters", async () => {
    const onSearch = vi.fn();
    render(<SearchBar onSearch={onSearch} />);
    await userEvent.type(screen.getByLabelText("US city"), "<script>{Enter}");
    expect(onSearch).not.toHaveBeenCalled();
  });

  it("indicates busy state", () => {
    render(<SearchBar onSearch={vi.fn()} busy />);
    expect(screen.getByRole("button", { name: "Searching…" })).toBeDisabled();
  });
});

describe("ParkList", () => {
  it("renders parks with a fallback for missing addresses", () => {
    render(<ParkList parks={PARKS} selectedId={null} onSelect={vi.fn()} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText("Address not available")).toBeInTheDocument();
  });

  it("uses a roving tabindex and arrow/Home/End keys", async () => {
    render(<ParkList parks={PARKS} selectedId={null} onSelect={vi.fn()} />);
    const [a, b, c] = screen.getAllByRole("button");
    expect(a).toHaveAttribute("tabindex", "0");
    expect(b).toHaveAttribute("tabindex", "-1");

    await userEvent.tab();
    expect(a).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(b).toHaveFocus();
    await userEvent.keyboard("{End}");
    expect(c).toHaveFocus();
    await userEvent.keyboard("{ArrowDown}");
    expect(c).toHaveFocus(); // stays on the last item
    await userEvent.keyboard("{Home}");
    expect(a).toHaveFocus();
    await userEvent.keyboard("{ArrowUp}");
    expect(a).toHaveFocus();
  });

  it("selects with Enter and Space", async () => {
    const onSelect = vi.fn();
    render(<ParkList parks={PARKS} selectedId={null} onSelect={onSelect} />);
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard("{ArrowDown} ");
    expect(onSelect.mock.calls.map(([p]) => p.id)).toEqual(["a", "b"]);
  });

  it("marks the selected park with text, not just colour", () => {
    render(<ParkList parks={PARKS} selectedId="b" onSelect={vi.fn()} />);
    const selected = screen.getByRole("button", { name: /Beta Park/ });
    expect(selected).toHaveAttribute("aria-current", "true");
    expect(selected).toHaveTextContent("Selected");
  });

  it("restores focus to a requested park", () => {
    render(<ParkList parks={PARKS} selectedId={null} onSelect={vi.fn()} focusId="c" />);
    expect(screen.getByRole("button", { name: /Gamma Park/ })).toHaveFocus();
  });

  it("renders nothing for an empty list", () => {
    const { container } = render(<ParkList parks={[]} selectedId={null} onSelect={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("ParkDetails", () => {
  it("shows all available information and focuses the heading", () => {
    render(<ParkDetails park={makePark({ website: "https://example.org" })} onBack={vi.fn()} />);
    const heading = screen.getByRole("heading", { name: "Prospect Park" });
    expect(heading).toHaveFocus();
    expect(screen.getByText("Brooklyn, NY 11225")).toBeInTheDocument();
    expect(screen.getByText("6:00 AM - 1:00 AM")).toBeInTheDocument();
    expect(screen.getByText("Dog run")).toBeInTheDocument();
    expect(screen.getByText("526 acres")).toBeInTheDocument();
    expect(screen.getByText("4.7 out of 5")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Photo 1 of Prospect Park" })).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /example.org/ });
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("labels missing information instead of inventing it", () => {
    render(<ParkDetails park={barePark()} onBack={vi.fn()} />);
    expect(screen.getByText("Address not available")).toBeInTheDocument();
    expect(screen.getByText("Description not available")).toBeInTheDocument();
    expect(screen.getByText("Hours not available")).toBeInTheDocument();
    expect(screen.getByText("Amenity information not available")).toBeInTheDocument();
    expect(screen.getByText("No images available.")).toBeInTheDocument();
    expect(screen.queryByText(/acres/)).not.toBeInTheDocument();
    expect(screen.queryByText(/out of 5/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("replaces a broken image with a message", () => {
    render(<ParkDetails park={makePark()} onBack={vi.fn()} />);
    fireEvent.error(screen.getByRole("img"));
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("Image could not be loaded.")).toBeInTheDocument();
  });

  it("calls onBack", async () => {
    const onBack = vi.fn();
    render(<ParkDetails park={makePark()} onBack={onBack} />);
    await userEvent.click(screen.getByRole("button", { name: /Back to results/ }));
    expect(onBack).toHaveBeenCalled();
  });
});

describe("StatusBanner", () => {
  const base = { loading: false, error: null, warnings: [], summary: null, hint: null, onRetry: vi.fn() };

  it("announces loading in a live region", () => {
    render(<StatusBanner {...base} loading />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading parks…");
  });

  it("shows the summary", () => {
    render(<StatusBanner {...base} summary="3 parks found." />);
    expect(screen.getByRole("status")).toHaveTextContent("3 parks found.");
  });

  it("shows warnings with a text label", () => {
    render(<StatusBanner {...base} warnings={["Showing sample data only."]} />);
    expect(screen.getByText(/Showing sample data only/)).toBeInTheDocument();
    expect(screen.getByText("Notice:")).toBeInTheDocument();
  });

  it("shows retryable errors with a Try again button", async () => {
    const onRetry = vi.fn();
    render(<StatusBanner {...base} onRetry={onRetry} error={new ApiError(503, "service_unavailable", "Down.")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Down.");
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(onRetry).toHaveBeenCalled();
  });

  it.each([404, 422])("does not offer retry for %i", (status) => {
    render(<StatusBanner {...base} error={new ApiError(status, "x", "Nope.")} />);
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });
});
