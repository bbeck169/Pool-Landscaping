/**
 * Feb-2026 · C3 · ``ChemicalApplicationsList`` admin list page.
 *
 * Covers:
 *   1. Title + filter bar render (navy hero).
 *   2. Fetches ``/chemical-applications`` + ``/customers`` + ``/technicians``
 *      on mount.
 *   3. Renders one row per application, correct value bindings.
 *   4. REI badge: red when unlock is future, green when past,
 *      neutral when null.
 *   5. Customer filter → API called with ``customer_id`` param.
 *   6. Date range filter → API called with ``date_from`` +
 *      ``date_to`` params.
 *   7. Pest filter → debounces then calls API with
 *      ``target_pest`` param (fake timers scoped to this test only).
 *   8. Load more → appends rows via cursor pagination.
 *   9. Empty state renders when API returns ``[]``.
 *   10. Error state renders + Retry re-fetches.
 *   11. Nav-entry role gate (asserted against ``adminNav.js``).
 *
 * Timers policy: real timers by default so React's
 * ``waitFor`` / async scheduling isn't frozen; fake timers are
 * scoped to the debounce test only.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor, within,
} from "@testing-library/react";


const { apiGetSpy, toastErrorSpy } = vi.hoisted(() => ({
  apiGetSpy: vi.fn(),
  toastErrorSpy: vi.fn(),
}));


vi.mock("@/api", () => ({
  api: {
    get: (...args) => apiGetSpy(...args),
    post: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: (...args) => toastErrorSpy(...args),
  },
}));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#FFFFFF",
    surfaceSecondary: "#F4F4F5",
    surfaceTertiary: "#E4E4E7",
    border: "#E4E4E7",
    muted: "#71717A",
    brand: "#0284C7",
    brandTertiary: "#E0F2FE",
    onSurface: "#09090B",
    onSurfaceSecondary: "#52525B",
    inputBorder: "#3B82F6",
    searchIcon: "#0284C7",
    nav: {
      bg: "#1B1F5C",
      bgHover: "#2A2F7A",
      fg: "#FFFFFF",
      fgMuted: "rgba(255,255,255,0.72)",
      border: "rgba(255,255,255,0.10)",
    },
    gradient: { css: "linear-gradient(90deg,#1B1F5C,#0284C7)" },
  },
}));

// The real ``CustomerCombobox`` uses a shadcn Popover which pulls in
// a browser Portal API. Replace with a native ``<select>`` so tests
// can drive the combobox with ``fireEvent.change``.
vi.mock("@/components/customers/CustomerCombobox", () => {
  const Stub = ({ value, onChange, customers, testid, placeholder }) => (
    <select value={value || ""}
            onChange={(e) => onChange(e.target.value)}
            data-testid={testid || "customer-combobox"}>
      <option value="">{placeholder || "All customers"}</option>
      {(customers || []).map((c) => (
        <option key={c.id} value={c.id}>{c.name}</option>
      ))}
    </select>
  );
  return { __esModule: true, default: Stub, CustomerCombobox: Stub };
});


import ChemicalApplicationsList from "../pages/chemical/ChemicalApplicationsList";


// ═══════════════════════════════════════════════════════════════════
// Fixtures
// ═══════════════════════════════════════════════════════════════════
const CUSTOMERS = [
  { id: "cust-1", name: "Alpha HOA" },
  { id: "cust-2", name: "Beta Estates" },
];
const TECHS = [
  { id: "tech-1", name: "Mike Rodriguez", email: "mike@aquaterra.com" },
];


/** Return an ISO timestamp ``deltaMs`` from now — real-time based
 *  so REI badges resolve correctly under real timers. */
function _isoNowPlus(deltaMs) {
  return new Date(Date.now() + deltaMs).toISOString();
}


function _row(overrides = {}) {
  return {
    id: overrides.id || "app-1",
    application_date: "2026-02-19",
    start_time: "09:00:00",
    stop_time: "09:45:00",
    customer_id: "cust-1",
    technician_name: "Mike Rodriguez",
    chemical_name: "Roundup Pro",
    target_pest: "Poa annua",
    area_treated_sqft: 5000,
    amount_sprayed_gal: 2.5,
    rei_hours: 24,
    // Default: 21h in the future → locked.
    rei_unlock_at: _isoNowPlus(21 * 60 * 60 * 1000),
    ...overrides,
  };
}


function _installApiMocks({
  chemAppsFirst = { items: [_row()], next_cursor: null },
  chemAppsSecond = null,
} = {}) {
  apiGetSpy.mockReset();
  apiGetSpy.mockImplementation((path) => {
    if (path === "/customers") return Promise.resolve(CUSTOMERS);
    if (path === "/technicians") return Promise.resolve(TECHS);
    if (typeof path === "string" && path.startsWith("/chemical-applications")) {
      if (chemAppsSecond && path.includes("cursor=")) {
        return Promise.resolve(chemAppsSecond);
      }
      return Promise.resolve(chemAppsFirst);
    }
    return Promise.resolve({});
  });
}


beforeEach(() => {
  _installApiMocks();
});

afterEach(() => {
  cleanup();
  // Belt-and-suspenders: any test that enabled fake timers restores here.
  vi.useRealTimers();
});


// ═══════════════════════════════════════════════════════════════════
// 1. Title + filter bar renders
// ═══════════════════════════════════════════════════════════════════
describe("ChemicalApplicationsList — page chrome", () => {
  it("renders title, refresh button, and filter bar", async () => {
    render(<ChemicalApplicationsList />);
    expect(screen.getByTestId("chemical-applications-page")).toBeTruthy();
    expect(screen.getByTestId("chemical-applications-title").textContent)
      .toContain("Chemical Applications");
    expect(screen.getByTestId("chemical-applications-refresh-btn")).toBeTruthy();
    expect(screen.getByTestId("chemical-applications-filters")).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByTestId("chemical-applications-rows")).toBeTruthy();
    });
  });
});


// ═══════════════════════════════════════════════════════════════════
// 2 + 3. Mount fetches, row rendering
// ═══════════════════════════════════════════════════════════════════
describe("ChemicalApplicationsList — data fetch + row rendering", () => {
  it("fetches customers + technicians + chemical-applications on mount", async () => {
    render(<ChemicalApplicationsList />);
    await waitFor(() => {
      expect(apiGetSpy).toHaveBeenCalledWith("/customers");
      expect(apiGetSpy).toHaveBeenCalledWith("/technicians");
    });
    await waitFor(() => {
      const chemCalls = apiGetSpy.mock.calls.filter(
        ([p]) => typeof p === "string" && p.startsWith("/chemical-applications"),
      );
      expect(chemCalls.length).toBeGreaterThan(0);
    });
  });

  it("renders a row per application with correct value bindings", async () => {
    render(<ChemicalApplicationsList />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-row-app-1")).toBeTruthy();
    });
    const row = screen.getByTestId("chem-app-row-app-1");
    expect(within(row).getByTestId("chem-app-row-app-1-date").textContent)
      .toBe("2026-02-19");
    expect(within(row).getByTestId("chem-app-row-app-1-customer").textContent)
      .toBe("Alpha HOA");
    expect(within(row).getByTestId("chem-app-row-app-1-pest").textContent)
      .toBe("Poa annua");
  });
});


// ═══════════════════════════════════════════════════════════════════
// 4. REI badge red/green/neutral
// ═══════════════════════════════════════════════════════════════════
describe("ChemicalApplicationsList — REI badge", () => {
  it("renders red locked badge when rei_unlock_at is in the future", async () => {
    render(<ChemicalApplicationsList />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-row-app-1-rei-locked")).toBeTruthy();
    });
    const badge = screen.getByTestId("chem-app-row-app-1-rei-locked");
    expect(badge.textContent).toContain("REI Locked");
  });

  it("renders green unlocked badge when rei_unlock_at has passed", async () => {
    _installApiMocks({
      chemAppsFirst: {
        items: [_row({ id: "app-2",
                       rei_unlock_at: _isoNowPlus(-60 * 60 * 1000) })],   // -1h
        next_cursor: null,
      },
    });
    render(<ChemicalApplicationsList />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-row-app-2-rei-unlocked")).toBeTruthy();
    });
    expect(screen.getByTestId("chem-app-row-app-2-rei-unlocked").textContent)
      .toContain("Reentry OK");
  });

  it("renders neutral badge when rei_unlock_at is null", async () => {
    _installApiMocks({
      chemAppsFirst: {
        items: [_row({ id: "app-3", rei_unlock_at: null })],
        next_cursor: null,
      },
    });
    render(<ChemicalApplicationsList />);
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-row-app-3-rei-unknown")).toBeTruthy();
    });
  });
});


// ═══════════════════════════════════════════════════════════════════
// 5. Customer + date filters → API params
// ═══════════════════════════════════════════════════════════════════
describe("ChemicalApplicationsList — filters", () => {
  it("passes customer_id to API when customer is selected", async () => {
    render(<ChemicalApplicationsList />);
    await waitFor(() => {
      expect(screen.getByTestId("chemical-applications-filter-customer")).toBeTruthy();
    });
    // Wait for initial data load so we don't race the first fetch.
    await waitFor(() => {
      expect(screen.getByTestId("chemical-applications-rows")).toBeTruthy();
    });
    apiGetSpy.mockClear();
    _installApiMocks();
    fireEvent.change(
      screen.getByTestId("chemical-applications-filter-customer"),
      { target: { value: "cust-2" } },
    );
    await waitFor(() => {
      const chemCall = apiGetSpy.mock.calls.find(
        ([p]) => typeof p === "string" && p.includes("customer_id=cust-2"),
      );
      expect(chemCall).toBeTruthy();
    });
  });

  it("passes date_from + date_to to API when date range set", async () => {
    render(<ChemicalApplicationsList />);
    await waitFor(() => {
      expect(screen.getByTestId("chemical-applications-filter-date-from")).toBeTruthy();
    });
    await waitFor(() => {
      expect(screen.getByTestId("chemical-applications-rows")).toBeTruthy();
    });
    apiGetSpy.mockClear();
    _installApiMocks();
    // Two changes — both should end up in the same final URL (React
    // batches state updates within the same tick; our filterParams
    // useMemo picks up the latest values).
    fireEvent.change(
      screen.getByTestId("chemical-applications-filter-date-from"),
      { target: { value: "2026-02-01" } },
    );
    fireEvent.change(
      screen.getByTestId("chemical-applications-filter-date-to"),
      { target: { value: "2026-02-28" } },
    );
    await waitFor(() => {
      const call = apiGetSpy.mock.calls.find(
        ([p]) => typeof p === "string"
          && p.includes("date_from=2026-02-01")
          && p.includes("date_to=2026-02-28"),
      );
      expect(call).toBeTruthy();
    });
  });

  it("debounces pest search — API not called mid-typing, called after 300 ms", async () => {
    // Enable fake timers ONLY for this test so we can drive the
    // 300 ms debounce deterministically without impacting the async
    // scheduling in the other tests.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      render(<ChemicalApplicationsList />);
      await waitFor(() => {
        expect(screen.getByTestId("chemical-applications-filter-pest")).toBeTruthy();
      });
      await waitFor(() => {
        expect(screen.getByTestId("chemical-applications-rows")).toBeTruthy();
      });
      apiGetSpy.mockClear();
      _installApiMocks();

      // NavyFilterBar.Search input is inside the sub-primitive — the
      // outer test-id target may itself be the input, or may wrap one.
      const searchWrap = screen.getByTestId("chemical-applications-filter-pest");
      const input = searchWrap.tagName === "INPUT"
        ? searchWrap
        : searchWrap.querySelector("input");
      expect(input).toBeTruthy();

      fireEvent.change(input, { target: { value: "P" } });
      fireEvent.change(input, { target: { value: "Po" } });
      fireEvent.change(input, { target: { value: "Poa" } });

      // Advance BEFORE the debounce fires — no chem-app call yet.
      await vi.advanceTimersByTimeAsync(150);
      let hits = apiGetSpy.mock.calls.filter(
        ([p]) => typeof p === "string" && p.includes("target_pest=Poa"),
      );
      expect(hits.length).toBe(0);

      // Advance past the debounce — one call fires with the final value.
      await vi.advanceTimersByTimeAsync(200);
      await waitFor(() => {
        hits = apiGetSpy.mock.calls.filter(
          ([p]) => typeof p === "string" && p.includes("target_pest=Poa"),
        );
        expect(hits.length).toBeGreaterThan(0);
      });
    } finally {
      vi.useRealTimers();
    }
  });
});


// ═══════════════════════════════════════════════════════════════════
// 8. Cursor pagination — Load more appends rows
// ═══════════════════════════════════════════════════════════════════
describe("ChemicalApplicationsList — cursor pagination", () => {
  it('shows "Load more" only when next_cursor is present, and appends on click', async () => {
    _installApiMocks({
      chemAppsFirst: {
        items: [_row({ id: "app-1" })],
        next_cursor: "cursor-abc",
      },
      chemAppsSecond: {
        items: [_row({ id: "app-2" })],
        next_cursor: null,
      },
    });
    render(<ChemicalApplicationsList />);
    await waitFor(() => {
      expect(screen.getByTestId("chemical-applications-load-more")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("chemical-applications-load-more"));
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-row-app-2")).toBeTruthy();
    });
    // First row still there — pagination appends, not replaces.
    expect(screen.getByTestId("chem-app-row-app-1")).toBeTruthy();
    // Button gone once next_cursor is null.
    expect(screen.queryByTestId("chemical-applications-load-more")).toBeNull();
  });
});


// ═══════════════════════════════════════════════════════════════════
// 9. Empty state
// ═══════════════════════════════════════════════════════════════════
describe("ChemicalApplicationsList — empty state", () => {
  it("renders empty state when API returns []", async () => {
    _installApiMocks({ chemAppsFirst: { items: [], next_cursor: null } });
    render(<ChemicalApplicationsList />);
    await waitFor(() => {
      expect(screen.getByTestId("chemical-applications-empty")).toBeTruthy();
    });
    expect(screen.getByTestId("chemical-applications-empty").textContent)
      .toContain("No chemical applications");
  });
});


// ═══════════════════════════════════════════════════════════════════
// 10. Error state + retry
// ═══════════════════════════════════════════════════════════════════
describe("ChemicalApplicationsList — error state", () => {
  it("renders error state + retry re-fetches successfully", async () => {
    apiGetSpy.mockReset();
    let hitCount = 0;
    apiGetSpy.mockImplementation((path) => {
      if (path === "/customers") return Promise.resolve(CUSTOMERS);
      if (path === "/technicians") return Promise.resolve(TECHS);
      if (typeof path === "string" && path.startsWith("/chemical-applications")) {
        hitCount += 1;
        if (hitCount === 1) return Promise.reject(new Error("Boom"));
        return Promise.resolve({ items: [_row({ id: "app-99" })], next_cursor: null });
      }
      return Promise.resolve({});
    });
    render(<ChemicalApplicationsList />);
    await waitFor(() => {
      expect(screen.getByTestId("chemical-applications-error")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("chemical-applications-error-retry"));
    await waitFor(() => {
      expect(screen.getByTestId("chem-app-row-app-99")).toBeTruthy();
    });
  });
});


// ═══════════════════════════════════════════════════════════════════
// 11. Nav-entry shape (permission gate contract)
// ═══════════════════════════════════════════════════════════════════
describe("ChemicalApplicationsList — nav entry shape lock", () => {
  it("adminNav registers /admin/chemical-applications with manager_only hard_rule and aliases", async () => {
    const { ADMIN_NAV_V2 } = await vi.importActual("../nav/adminNav");
    const flat = ADMIN_NAV_V2.flatMap((sec) => sec.entries || []);
    const row = flat.find((e) => e && e.to === "/admin/chemical-applications");
    expect(row).toBeTruthy();
    expect(row.hard_rule).toBe("manager_only");
    expect(row.subsection).toBe("Field Service");
    expect(Array.isArray(row.aliases)).toBe(true);
    for (const alias of ["Spray Log", "Pesticide Log", "Chemical Log", "REI Tracking"]) {
      expect(row.aliases).toContain(alias);
    }
  });
});
