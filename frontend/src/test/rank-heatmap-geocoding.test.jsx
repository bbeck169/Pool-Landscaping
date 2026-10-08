/**
 * RANK-HEATMAP-ADDRESS-AUTOCOMPLETE · Feb-2026 — the Rank Heatmap
 * page previously rendered two bare ``type="number"`` inputs for
 * the grid center (lat + lng).  Users had to look up / paste
 * coordinates by hand, which is error-prone + friction-heavy
 * especially for admins trying to validate a new service area.
 *
 * The web page now routes through the shared
 * ``<AddressAutocomplete>`` component (same one in use on the CAD
 * editor, Geofences, Route Replay, etc.) — selecting an address
 * suggestion auto-populates the lat / lng into read-only fields.
 * A tiny "Enter coords manually" toggle keeps the manual-entry
 * fallback working for the API-key-unavailable case + for power
 * users who want to type the raw numbers.
 *
 * This test locks the end-to-end contract:
 *   1. The address input renders with the standard testid
 *      hierarchy (``rank-heatmap-address-input``).
 *   2. On a selection the lat + lng fields auto-populate with the
 *      resolved coordinates.
 *   3. The lat + lng fields are ``readOnly`` by default (post-
 *      selection) so a user can't type over the resolved value.
 *   4. The "Enter coords manually" toggle flips them back to
 *      editable (fallback path for key-unavailable + power users).
 *   5. Clearing the address field clears the resolved coords so a
 *      stale selection can't survive into Generate.
 *   6. Generate uses the resolved coords (fires POST with the
 *      auto-populated values).
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach, afterEach,
} from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


const { getSpy, postSpy } = vi.hoisted(() => ({
  getSpy:  vi.fn(),
  postSpy: vi.fn(),
}));

vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: {
    get:  (...a) => getSpy(...a),
    post: (...a) => postSpy(...a),
  },
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(),
  }),
}));


// Stub the shared AddressAutocomplete with a thin surrogate that
// exposes the same public API — ``onChange(string)`` fires on raw
// typing + clear, ``onSelect(parsed)`` fires when the user picks a
// suggestion.  Keeps the test focused on the Rank Heatmap page's
// integration (lat / lng wiring + readOnly state) without pulling
// in the Google Places / runtime-key resolution flow.
vi.mock("@/components/AddressAutocomplete", () => ({
  default: ({ value, onChange, onSelect, testid = "address-autocomplete" }) => (
    <div data-testid={testid}>
      <input
        data-testid={`${testid}-input`}
        value={value || ""}
        onChange={(e) => onChange?.(e.target.value)}
      />
      <button
        data-testid={`${testid}-fire-phoenix`}
        onClick={() => onSelect?.({
          address:   "100 Pool Rd, Phoenix, AZ 85001",
          formatted: "100 Pool Rd, Phoenix, AZ 85001",
          lat: 33.4484,
          lng: -112.0740,
          place_id: "pop-phoenix",
        })}
      >Phoenix</button>
      <button
        data-testid={`${testid}-fire-miami`}
        onClick={() => onSelect?.({
          address:   "200 Lido Blvd, Miami, FL 33101",
          formatted: "200 Lido Blvd, Miami, FL 33101",
          lat: 25.7617,
          lng: -80.1918,
          place_id: "pop-miami",
        })}
      >Miami</button>
    </div>
  ),
}));


import RankHeatmap from "@/pages/seo/RankHeatmap.jsx";


function _mount() {
  return render(
    <MemoryRouter initialEntries={["/seo/rank-heatmap"]}>
      <RankHeatmap />
    </MemoryRouter>,
  );
}


beforeEach(() => {
  getSpy.mockReset();
  postSpy.mockReset();
  // The page issues GET /seo/rank-heatmaps on mount for the list.
  getSpy.mockImplementation(async (p) => {
    if (p === "/seo/rank-heatmaps") return [];
    return {};
  });
});

afterEach(() => cleanup());


describe("RankHeatmap · address autocomplete integration", () => {
  it("renders the address field with the shared autocomplete + "
     + "the resolved-coordinates label section", async () => {
    _mount();
    expect(await screen.findByTestId("rank-heatmap-address"))
      .toBeInTheDocument();
    expect(screen.getByTestId("rank-heatmap-address-input"))
      .toBeInTheDocument();
    expect(screen.getByText(/Resolved coordinates/i))
      .toBeInTheDocument();
  });

  it("auto-populates lat + lng on autocomplete selection", async () => {
    _mount();
    const lat = screen.getByTestId("rank-heatmap-lat");
    const lng = screen.getByTestId("rank-heatmap-lng");
    // Pre-selection the fields read the page's useState default
    // (``33.6 / -112.2`` — a near-Phoenix neutral starting point).
    // The regression check is that the autocomplete selection
    // OVERWRITES these with the resolved coordinates, not that the
    // defaults are any particular value.
    const latBefore = Number(lat.value);
    const lngBefore = Number(lng.value);

    fireEvent.click(screen.getByTestId("rank-heatmap-address-fire-phoenix"));

    await waitFor(() => {
      expect(Number(lat.value)).toBeCloseTo(33.4484, 4);
      expect(Number(lng.value)).toBeCloseTo(-112.0740, 4);
    });
    // Values post-selection differ from pre-selection — proves
    // the ``onSelect`` callback actually ran.
    expect(Number(lat.value)).not.toBe(latBefore);
    expect(Number(lng.value)).not.toBe(lngBefore);
  });

  it("renders lat + lng as readOnly after an address selection "
     + "(default manual-override OFF)", async () => {
    _mount();
    const lat = screen.getByTestId("rank-heatmap-lat");
    const lng = screen.getByTestId("rank-heatmap-lng");
    // Default state: no address picked yet, but fields are still
    // readOnly (manualCoords=false by default).  The toggle is the
    // only path to editable.
    expect(lat).toHaveProperty("readOnly", true);
    expect(lng).toHaveProperty("readOnly", true);

    fireEvent.click(screen.getByTestId("rank-heatmap-address-fire-phoenix"));
    await waitFor(() => {
      expect(Number(lat.value)).toBeCloseTo(33.4484, 4);
    });
    // Still readOnly after selection — the resolved coords stay
    // locked in so the user can't type over them.
    expect(lat).toHaveProperty("readOnly", true);
    expect(lng).toHaveProperty("readOnly", true);
  });

  it("'Enter coords manually' toggle unlocks the lat + lng inputs "
     + "(key-unavailable + power-user fallback)", async () => {
    _mount();
    const lat = screen.getByTestId("rank-heatmap-lat");
    const lng = screen.getByTestId("rank-heatmap-lng");
    expect(lat).toHaveProperty("readOnly", true);

    fireEvent.click(screen.getByTestId("rank-heatmap-manual-toggle"));
    expect(lat).toHaveProperty("readOnly", false);
    expect(lng).toHaveProperty("readOnly", false);

    // Toggling back flips them to readOnly again.
    fireEvent.click(screen.getByTestId("rank-heatmap-manual-toggle"));
    expect(lat).toHaveProperty("readOnly", true);
    expect(lng).toHaveProperty("readOnly", true);
  });

  it("clearing the address field clears the resolved coords "
     + "(no stale selection into Generate)", async () => {
    _mount();
    const lat = screen.getByTestId("rank-heatmap-lat");
    const lng = screen.getByTestId("rank-heatmap-lng");

    fireEvent.click(screen.getByTestId("rank-heatmap-address-fire-miami"));
    await waitFor(() => {
      expect(Number(lat.value)).toBeCloseTo(25.7617, 4);
    });
    expect(Number(lng.value)).toBeCloseTo(-80.1918, 4);

    // User backspaces the address text to empty.
    const addrInput = screen.getByTestId("rank-heatmap-address-input");
    fireEvent.change(addrInput, { target: { value: "" } });
    await waitFor(() => {
      expect(Number(lat.value)).toBe(0);
      expect(Number(lng.value)).toBe(0);
    });
  });

  it("Generate button posts the auto-populated coords (not the "
     + "pre-selection zeros) when the user picks a suggestion", async () => {
    postSpy.mockResolvedValue({ heatmap_id: "hm-1" });
    getSpy.mockImplementation(async (p) => {
      if (p === "/seo/rank-heatmaps") return [];
      if (p === "/seo/rank-heatmaps/hm-1") {
        return { id: "hm-1", status: "done", cells: [] };
      }
      return {};
    });

    _mount();

    // Fill the keyword (empty keyword is caught by the client-side
    // guard and would short-circuit before POST).
    const kw = screen.getByTestId("rank-heatmap-kw");
    fireEvent.change(kw, { target: { value: "pool cleaning phoenix" } });

    fireEvent.click(screen.getByTestId("rank-heatmap-address-fire-phoenix"));
    await waitFor(() => {
      expect(Number(screen.getByTestId("rank-heatmap-lat").value))
        .toBeCloseTo(33.4484, 4);
    });

    fireEvent.click(screen.getByTestId("rank-heatmap-run"));

    await waitFor(() => expect(postSpy).toHaveBeenCalled());
    const [path, body] = postSpy.mock.calls[0];
    expect(path).toBe("/seo/rank-heatmaps");
    // Body carries the resolved lat / lng from autocomplete — the
    // regression check is that the pre-selection ``0`` defaults
    // did NOT make it into the server call.
    expect(body.center_lat).toBeCloseTo(33.4484, 4);
    expect(body.center_lng).toBeCloseTo(-112.0740, 4);
    expect(body.keyword).toBe("pool cleaning phoenix");
  });
});
