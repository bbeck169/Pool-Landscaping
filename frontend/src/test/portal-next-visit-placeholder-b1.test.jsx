/**
 * Feb-2026 · Portal Next-Visit tiles β1 — "No visit scheduled"
 * placeholder rendering.
 *
 * BE commit ``44024703f`` now emits ``next_visit_at: null`` rows
 * for subscribed services with no future job. This suite pins the
 * four cases locked in the operator dispatch for Commit B:
 *
 *   1. Tile with a real datetime renders date + day-of-week
 *      (regression lock on shipped behaviour)
 *   2. Tile with ``next_visit_at: null`` renders "No visit
 *      scheduled" copy
 *   3. Mixed response (one real + one null) renders both tiles
 *      with the correct per-tile state
 *   4. Empty response (``[]``) still hides the row (preserve
 *      shipped no-subscriptions behaviour)
 */
import React from "react";
import { MemoryRouter } from "react-router-dom";
import {
  describe, it, expect, vi, beforeEach,
} from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const { mockGet } = vi.hoisted(() => ({ mockGet: vi.fn() }));
vi.mock("@/api", () => ({
  TOKEN_KEY: "token",
  api: {
    get: (...a) => mockGet(...a),
    post: vi.fn(), patch: vi.fn(), delete: vi.fn(),
  },
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { role: "customer", customer_id: "c-1",
            tenant_id: "t-1", email: "test@example.com" },
  }),
}));

vi.mock("@/hooks/use-toast", () => ({ toast: vi.fn() }));

// PortalHome fans out to half a dozen endpoints on mount; this
// test only cares about ``/portal/dashboard/next-visits``. Everything
// else resolves to a benign empty shape so the component can render
// without crashing.
function _wireApi(nextVisits) {
  mockGet.mockImplementation((path) => {
    if (path.startsWith("/portal/dashboard/next-visits")) {
      return Promise.resolve({ next_visits: nextVisits });
    }
    if (path.includes("summary") || path.includes("balance")) {
      return Promise.resolve({});
    }
    return Promise.resolve({ items: [], counts: {} });
  });
}


import PortalHome from "@/pages/portal/PortalHome";


function _render() {
  return render(
    <MemoryRouter initialEntries={["/portal/home"]}>
      <PortalHome />
    </MemoryRouter>,
  );
}


beforeEach(() => {
  mockGet.mockReset();
});


describe("Portal NextVisitTile β1 — placeholder rendering", () => {
  it("1. real datetime renders day-of-week + date (shipped lock)", async () => {
    _wireApi([{
      service_type: "pool",
      next_visit_at: "2026-03-12T14:00:00Z",
      tech_name: "Jamie Rivers",
      visit_id: "job-1",
    }]);
    _render();
    const tile = await screen.findByTestId("next-visit-tile-pool");
    expect(tile.getAttribute("data-placeholder")).toBe("false");
    const dt = await screen.findByTestId(
      "next-visit-tile-datetime-pool",
    );
    // The formatter yields "<Weekday>, <Mon> <d> at <h>:<mm> <AM/PM>".
    // Weekday-only lock keeps the test TZ-agnostic.
    expect(dt.textContent).toMatch(/[A-Za-z]{3,9}/);
    expect(dt.textContent).not.toMatch(/No visit scheduled/i);
    expect(
      screen.getByTestId("next-visit-tile-tech-pool").textContent,
    ).toContain("Jamie");
  });

  it("2. next_visit_at=null renders 'No visit scheduled' copy", async () => {
    _wireApi([{
      service_type: "pool",
      next_visit_at: null,
      tech_name: null,
      visit_id: null,
    }]);
    _render();
    const tile = await screen.findByTestId("next-visit-tile-pool");
    expect(tile.getAttribute("data-placeholder")).toBe("true");
    const dt = screen.getByTestId("next-visit-tile-datetime-pool");
    expect(dt.textContent.trim()).toBe("No visit scheduled");
    // Tech line suppressed on placeholders.
    expect(
      screen.queryByTestId("next-visit-tile-tech-pool"),
    ).toBeNull();
    // Row still renders (not hidden); chevron still visible.
    expect(
      screen.getByTestId("next-visits-tile-row"),
    ).toBeTruthy();
    expect(
      screen.getByTestId("next-visit-tile-link-pool"),
    ).toBeTruthy();
  });

  it("3. mixed real + null renders both tiles per state", async () => {
    _wireApi([
      {
        service_type: "pool",
        next_visit_at: "2026-03-12T14:00:00Z",
        tech_name: "Jamie Rivers", visit_id: "job-1",
      },
      {
        service_type: "landscape",
        next_visit_at: null, tech_name: null, visit_id: null,
      },
    ]);
    _render();
    const pool = await screen.findByTestId("next-visit-tile-pool");
    const landscape = await screen.findByTestId(
      "next-visit-tile-landscape",
    );
    expect(pool.getAttribute("data-placeholder")).toBe("false");
    expect(landscape.getAttribute("data-placeholder")).toBe("true");
    expect(
      screen.getByTestId("next-visit-tile-datetime-landscape").textContent,
    ).toContain("No visit scheduled");
    expect(
      screen.getByTestId("next-visit-tile-datetime-pool").textContent,
    ).not.toContain("No visit scheduled");
  });

  it("4. empty response still hides the row (shipped lock)", async () => {
    _wireApi([]);
    _render();
    // The tile-row testid never appears; skeleton clears when the
    // fetch resolves with an empty array.
    await waitFor(() => {
      expect(
        screen.queryByTestId("next-visits-skeleton"),
      ).toBeNull();
    });
    expect(
      screen.queryByTestId("next-visits-tile-row"),
    ).toBeNull();
  });
});
