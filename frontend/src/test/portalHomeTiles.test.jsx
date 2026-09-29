/**
 * Feb-2026 · Pool Service PS-D — Smart Portal Tiles vitest suite.
 *
 * Pins the seven behaviour invariants from the brief + one
 * datetime-formatting edge (date-only ISO):
 *   (a) eligible pool row → tile renders with datetime + tech.
 *   (b) mixed eligibility → only qualifying tiles render, in
 *       canonical order (Pool → Landscape → Filter Cleaning).
 *   (c) API 500 → row hidden, no crash.
 *   (d) loading state → skeleton row visible until fetch settles.
 *   (e) tech unassigned → 'Tech to be assigned' fallback.
 *   (f) deep-link href includes ``service_type`` query param.
 *   (g) empty array → tile row not rendered.
 *   (h) date-only ISO (legacy job with only ``scheduled_date``) →
 *       renders the day label without an "at HH:MM" suffix.
 */
import React from "react";
import {
  describe, it, expect, vi, beforeEach,
} from "vitest";
import {
  render, screen, waitFor, cleanup,
} from "@testing-library/react";


// Mock the api module BEFORE importing the page component.
const { apiGet } = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock("@/api", () => ({
  api: {
    get:   (...a) => apiGet(...a),
    post:  vi.fn(),
    patch: vi.fn(),
    del:   vi.fn(),
  },
}));

const _navSpy = vi.fn();
vi.mock("react-router-dom", () => ({
  useNavigate: () => _navSpy,
}));

// The page pulls in a bunch of stuff we don't need for PS-D
// assertions.  Stub the noisy peripherals so the render stays
// hermetic.
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(),
    warning: vi.fn(), info: vi.fn(),
  }),
}));

vi.mock("@/theme", () => {
  // DTP-2 · Feb-2026 — the portal page under test imports
  // ``portalColors`` (aliased as ``colors``) + ``portalGradients``
  // from ``@/theme``. Mirror both under aliases so the module
  // mock stays hermetic without dragging the real theme file
  // into the test bundle.
  const base = {
    brand: "#0B4A6F", brandTertiary: "#0F172A",
    onBrand: "#FFFFFF",
    onSurface: "#111827", muted: "#6B7280",
    border: "#E5E7EB", divider: "#E5E7EB",
    surface: "#FFFFFF", surfaceSecondary: "#F8FAFC",
    success: "#059669", error: "#DC2626",
  };
  const heroGrad = { css: "linear-gradient(#000,#111)" };
  return {
    colors: base,
    portalColors: base,
    gradients: { navyToGreen: heroGrad },
    portalGradients: { navyToBlue: heroGrad },
    money: (n) => `$${Number(n || 0).toFixed(2)}`,
  };
});

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "customer", name: "PS-D User" } }),
}));


// Wire endpoint responses.  We only care about
// /portal/dashboard/next-visits for these fixtures; every other
// call the page makes routes through a permissive stub returning
// an empty object so nothing crashes.
function _wireEndpoints({ nextVisits, delay = 0, error = false }) {
  apiGet.mockImplementation((path) => {
    if (path.startsWith("/portal/dashboard/next-visits")) {
      if (error) {
        return new Promise((_, reject) =>
          setTimeout(() => reject(new Error("500")), delay),
        );
      }
      return new Promise((res) =>
        setTimeout(() => res({ next_visits: nextVisits }), delay),
      );
    }
    if (path.startsWith("/portal/home")) {
      return Promise.resolve({ counts: {}, next_visit: null });
    }
    if (path.startsWith("/customer-portal/summary")) {
      return Promise.resolve({
        balance_due: 0, past_due: 0, credit: 0,
        breakdown: { open_invoice_count: 0, past_due_invoice_count: 0 },
      });
    }
    if (path.startsWith("/customer-portal/credits/balance")) {
      return Promise.resolve({ balance_dollars: 0 });
    }
    if (path.startsWith("/portal/messages/unread-count")) {
      return Promise.resolve({ unread: 0 });
    }
    // Anything else — resolve permissively.
    return Promise.resolve({});
  });
}


// eslint-disable-next-line import/first
import PortalHome from "@/pages/portal/PortalHome";


beforeEach(() => {
  apiGet.mockReset();
  _navSpy.mockReset();
  // Silence the console.warn PS-D emits on the error path so
  // vitest output stays clean.
  vi.spyOn(console, "warn").mockImplementation(() => {});
});


// ═══════════════════════════════════════════════════════════════════
// (a) Eligible pool row → tile renders with datetime + tech.
// ═══════════════════════════════════════════════════════════════════
describe("PS-D · Smart Portal Tiles · eligible row renders", () => {
  it("shows the pool tile with datetime + tech name", async () => {
    _wireEndpoints({ nextVisits: [{
      service_type: "pool",
      next_visit_at: "2026-03-12T14:00:00Z",
      tech_name: "Mike Rodriguez",
      visit_id: "v-1",
    }] });
    render(<PortalHome />);

    const tile = await screen.findByTestId("next-visit-tile-pool");
    expect(tile).toBeInTheDocument();
    const dt = screen.getByTestId(
      "next-visit-tile-datetime-pool",
    );
    // The formatter renders "<Weekday>, <Mon> <D> at <H>:MM <AM|PM>".
    // We assert the day+month token so the test isn't tz-brittle.
    expect(dt.textContent).toMatch(/Mar/);
    expect(dt.textContent).toMatch(/\d{1,2}:\d{2}/);
    expect(screen.getByTestId("next-visit-tile-tech-pool")
      .textContent).toBe("Mike Rodriguez");
  });
});


// ═══════════════════════════════════════════════════════════════════
// (b) Mixed eligibility — only qualifying tiles render, in
// canonical order Pool → Landscape → Filter Cleaning.
// ═══════════════════════════════════════════════════════════════════
describe("PS-D · Smart Portal Tiles · mixed eligibility", () => {
  it("renders only qualifying tiles preserving backend order", async () => {
    _wireEndpoints({ nextVisits: [
      { service_type: "pool",
        next_visit_at: "2026-03-12T14:00:00Z",
        tech_name: "Mike", visit_id: "v-1" },
      { service_type: "filter_cleaning",
        next_visit_at: "2026-03-20T09:00:00Z",
        tech_name: "Carlos", visit_id: "v-3" },
    ] });
    render(<PortalHome />);

    await screen.findByTestId("next-visit-tile-pool");
    expect(screen.getByTestId("next-visit-tile-filter_cleaning"))
      .toBeInTheDocument();
    // Landscape tile absent (backend excluded it).
    expect(screen.queryByTestId("next-visit-tile-landscape"))
      .toBeNull();

    // Canonical order — pool tile precedes filter tile in DOM.
    const row = screen.getByTestId("next-visits-tile-row");
    const tiles = row.querySelectorAll(
      ":scope > [data-testid^=next-visit-tile-]",
    );
    expect(tiles[0].getAttribute("data-testid"))
      .toBe("next-visit-tile-pool");
    expect(tiles[1].getAttribute("data-testid"))
      .toBe("next-visit-tile-filter_cleaning");
  });
});


// ═══════════════════════════════════════════════════════════════════
// (c) API 500 → row hidden, no crash.
// ═══════════════════════════════════════════════════════════════════
describe("PS-D · Smart Portal Tiles · API 500 hides row", () => {
  it("hides the tile row when the endpoint rejects", async () => {
    _wireEndpoints({ nextVisits: [], error: true });
    render(<PortalHome />);
    // Wait past the initial skeleton settle.
    await waitFor(() => {
      expect(screen.queryByTestId("next-visits-skeleton")).toBeNull();
    });
    expect(screen.queryByTestId("next-visits-tile-row")).toBeNull();
    expect(screen.queryByTestId("next-visit-tile-pool")).toBeNull();
    // Sanity — the greater page did NOT crash (some other portal
    // marker exists in the DOM).
    expect(screen.getByTestId("portal-home")).toBeInTheDocument();
  });
});


// ═══════════════════════════════════════════════════════════════════
// (d) Loading state — skeleton visible until settle.
// ═══════════════════════════════════════════════════════════════════
describe("PS-D · Smart Portal Tiles · loading state", () => {
  it("renders the skeleton row while /next-visits is inflight", async () => {
    // Delay the resolve so we can observe the skeleton frame.
    _wireEndpoints({
      nextVisits: [{
        service_type: "pool",
        next_visit_at: "2026-03-12T14:00:00Z",
        tech_name: null, visit_id: "v-1",
      }],
      delay: 60,
    });
    render(<PortalHome />);

    expect(await screen.findByTestId("next-visits-skeleton"))
      .toBeInTheDocument();

    // After settle, skeleton gone + tile present.
    await screen.findByTestId("next-visit-tile-pool");
    expect(screen.queryByTestId("next-visits-skeleton")).toBeNull();
  });
});


// ═══════════════════════════════════════════════════════════════════
// (e) Tech unassigned → fallback copy.
// ═══════════════════════════════════════════════════════════════════
describe("PS-D · Smart Portal Tiles · unassigned tech", () => {
  it("renders 'Tech to be assigned' when tech_name is null", async () => {
    _wireEndpoints({ nextVisits: [{
      service_type: "landscape",
      next_visit_at: "2026-03-14T13:00:00Z",
      tech_name: null,
      visit_id: "v-2",
    }] });
    render(<PortalHome />);
    await screen.findByTestId("next-visit-tile-landscape");
    expect(screen.getByTestId("next-visit-tile-tech-landscape")
      .textContent).toBe("Tech to be assigned");
  });
});


// ═══════════════════════════════════════════════════════════════════
// (f) Deep-link — clicking the tile fires navigate with the
// canonical service_type query param.
// ═══════════════════════════════════════════════════════════════════
describe("PS-D · Smart Portal Tiles · deep-link", () => {
  it("navigates to /portal/schedule?service_type=<key>", async () => {
    _wireEndpoints({ nextVisits: [{
      service_type: "filter_cleaning",
      next_visit_at: "2026-04-01T09:00:00Z",
      tech_name: null, visit_id: "v-3",
    }] });
    render(<PortalHome />);
    const tile = await screen.findByTestId(
      "next-visit-tile-filter_cleaning",
    );
    tile.click();
    expect(_navSpy).toHaveBeenCalledWith(
      "/portal/schedule?service_type=filter_cleaning",
    );
  });
});


// ═══════════════════════════════════════════════════════════════════
// (g) Empty array → row not rendered.
// ═══════════════════════════════════════════════════════════════════
describe("PS-D · Smart Portal Tiles · empty response", () => {
  it("does NOT render the tile row when next_visits=[]", async () => {
    _wireEndpoints({ nextVisits: [] });
    render(<PortalHome />);
    // Skeleton settles first, then nothing else renders.
    await waitFor(() => {
      expect(screen.queryByTestId("next-visits-skeleton")).toBeNull();
    });
    expect(screen.queryByTestId("next-visits-tile-row")).toBeNull();
    expect(screen.queryByTestId("next-visit-tile-pool")).toBeNull();
    expect(screen.queryByTestId("next-visit-tile-landscape")).toBeNull();
    expect(screen.queryByTestId("next-visit-tile-filter_cleaning"))
      .toBeNull();
  });
});


// ═══════════════════════════════════════════════════════════════════
// (h) Date-only ISO → renders the day label without an at-time
// suffix (legacy job with only scheduled_date populated).
// ═══════════════════════════════════════════════════════════════════
describe("PS-D · Smart Portal Tiles · date-only ISO fallback", () => {
  it("renders day label without at-time when tz-less date is passed", async () => {
    _wireEndpoints({ nextVisits: [{
      service_type: "pool",
      next_visit_at: "2026-04-15",
      tech_name: "Mike", visit_id: "v-9",
    }] });
    render(<PortalHome />);
    const dt = await screen.findByTestId(
      "next-visit-tile-datetime-pool",
    );
    expect(dt.textContent).toMatch(/Apr/);
    // Day-only path suppresses the "at HH:MM" suffix by design.
    expect(dt.textContent).not.toMatch(/ at /);
  });
});


// ═══════════════════════════════════════════════════════════════════
// (i) Cleanup handoff — re-mount between tests must not leak
// stale state (defensive; catches a common vitest gotcha).
// ═══════════════════════════════════════════════════════════════════
describe("PS-D · Smart Portal Tiles · re-mount cleanup", () => {
  it("second render freshly resolves the endpoint", async () => {
    _wireEndpoints({ nextVisits: [] });
    const first = render(<PortalHome />);
    await waitFor(() => {
      expect(screen.queryByTestId("next-visits-skeleton")).toBeNull();
    });
    first.unmount();
    cleanup();

    _wireEndpoints({ nextVisits: [{
      service_type: "pool",
      next_visit_at: "2026-04-20T10:00:00Z",
      tech_name: "Jim", visit_id: "v-x",
    }] });
    render(<PortalHome />);
    await screen.findByTestId("next-visit-tile-pool");
  });
});
