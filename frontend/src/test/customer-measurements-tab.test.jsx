/**
 * Feb-2026 · M2 · CustomerDetail "Measurements" tab.
 *
 * Covers:
 *   1. Role gate — Measurements tab is visible for admin /
 *      super_admin / manager and hidden for technician / customer.
 *   2. Fetches ``/measurements?customer_id=<id>`` + ``/jobs?customer_id=<id>``
 *      on mount and paints one row per measurement.
 *   3. Row rendering — linear / area / perimeter / legacy buckets
 *      compute the right value + unit.
 *   4. Job filter dropdown — filters the visible list.
 *   5. Copy-to-Quote — writes the M2-format string to
 *      ``navigator.clipboard.writeText`` and fires a success toast.
 *   6. Empty state renders when the API returns ``[]``.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render, screen, cleanup, fireEvent, waitFor,
} from "@testing-library/react";


const { apiGetSpy, toastSuccessSpy, toastErrorSpy, clipboardSpy } = vi.hoisted(() => ({
  apiGetSpy: vi.fn(),
  toastSuccessSpy: vi.fn(),
  toastErrorSpy: vi.fn(),
  clipboardSpy: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/api", () => ({
  api: {
    get: (...args) => apiGetSpy(...args),
    post: vi.fn(),
  },
}));

vi.mock("sonner", () => ({
  toast: {
    success: (...args) => toastSuccessSpy(...args),
    error: (...args) => toastErrorSpy(...args),
  },
}));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#FFFFFF",
    surfaceSecondary: "#F4F4F5",
    border: "#E4E4E7",
    muted: "#71717A",
    brand: "#0B4A6F",
    brandTertiary: "#E0F2FE",
    onSurface: "#09090B",
    inputBorder: "#3B82F6",
    nav: { bg: "#1B1F5C" },
  },
}));


import {
  CustomerMeasurementsTab,
  filterCustomerTabs,
  MEASUREMENTS_TAB_ROLES,
  resolveMeasurementValue,
  buildClipboardString,
} from "@/components/customer/CustomerMeasurementsTab";


// ── helpers ─────────────────────────────────────────────────────
function _mockApiOnce({ measurements = [], jobs = [] } = {}) {
  apiGetSpy.mockImplementation((path) => {
    if (path.startsWith("/measurements")) return Promise.resolve(measurements);
    if (path.startsWith("/jobs")) return Promise.resolve(jobs);
    return Promise.reject(new Error(`unmocked path: ${path}`));
  });
}


beforeEach(() => {
  apiGetSpy.mockReset();
  toastSuccessSpy.mockReset();
  toastErrorSpy.mockReset();
  clipboardSpy.mockReset();
  clipboardSpy.mockResolvedValue(undefined);
  // Global clipboard shim — jsdom provides window.navigator but no
  // ``clipboard`` property by default.
  Object.defineProperty(global.navigator, "clipboard", {
    value: { writeText: clipboardSpy },
    configurable: true,
  });
});
afterEach(() => { cleanup(); });


// ═════════════════════════════════════════════════════════════════
// (1) TABS role gate
// ═════════════════════════════════════════════════════════════════
describe("filterCustomerTabs · role gate", () => {
  it("locks the Measurements role set to admin / super_admin / manager", () => {
    expect(MEASUREMENTS_TAB_ROLES.sort()).toEqual(
      ["admin", "manager", "super_admin"],
    );
  });

  it("keeps legacy tabs visible to any role", () => {
    const legacy = [
      { k: "overview", label: "Overview" },
      { k: "jobs", label: "Jobs" },
    ];
    for (const role of ["admin", "manager", "technician", "customer", null]) {
      const seen = filterCustomerTabs(legacy, role);
      expect(seen).toEqual(legacy);
    }
  });

  it("hides Measurements for technician + customer, shows for admin trio", () => {
    const tabs = [
      { k: "overview", label: "Overview" },
      { k: "measurements", label: "Measurements", roles: MEASUREMENTS_TAB_ROLES },
    ];
    for (const role of ["technician", "customer", null, undefined]) {
      const keys = filterCustomerTabs(tabs, role).map((t) => t.k);
      expect(keys).toEqual(["overview"]);
    }
    for (const role of ["admin", "super_admin", "manager"]) {
      const keys = filterCustomerTabs(tabs, role).map((t) => t.k);
      expect(keys).toEqual(["overview", "measurements"]);
    }
  });
});


// ═════════════════════════════════════════════════════════════════
// (2) Value + clipboard helpers · pure functions
// ═════════════════════════════════════════════════════════════════
describe("resolveMeasurementValue · type buckets", () => {
  it("linear + ft returns distance_ft in feet", () => {
    expect(resolveMeasurementValue({
      type: "linear", unit: "ft", distance_ft: 42,
    })).toEqual({ value: 42, unit: "ft" });
  });

  it("linear + yd converts distance_ft to yards", () => {
    expect(resolveMeasurementValue({
      type: "linear", unit: "yd", distance_ft: 9,
    })).toEqual({ value: 3, unit: "yd" });
  });

  it("area always uses sqft", () => {
    expect(resolveMeasurementValue({
      type: "area", unit: "sqft", area_sqft: 250,
    })).toEqual({ value: 250, unit: "sqft" });
  });

  it("perimeter honours ft / yd", () => {
    expect(resolveMeasurementValue({
      type: "perimeter", unit: "yd", perimeter_ft: 84,
    })).toEqual({ value: 28, unit: "yd" });
  });

  it("legacy row (no type) falls back to first non-zero of distance/area/perimeter", () => {
    expect(resolveMeasurementValue({
      distance_ft: 10, area_sqft: 0, perimeter_ft: 0,
    })).toEqual({ value: 10, unit: "ft" });
    expect(resolveMeasurementValue({
      distance_ft: 0, area_sqft: 500, perimeter_ft: 0,
    })).toEqual({ value: 500, unit: "sqft" });
    expect(resolveMeasurementValue({
      distance_ft: 0, area_sqft: 0, perimeter_ft: 60,
    })).toEqual({ value: 60, unit: "ft" });
  });
});


describe("buildClipboardString · M2 wire format", () => {
  it("includes type token when present", () => {
    const s = buildClipboardString(
      { type: "area", unit: "sqft", area_sqft: 125.5,
        created_at: "2026-02-20T12:00:00Z" },
      "Smith Residence", "Pool Deck 2026",
    );
    expect(s).toBe("125.5 sqft — area — Smith Residence, Pool Deck 2026, 2026-02-20");
  });

  it("drops type token on legacy rows", () => {
    const s = buildClipboardString(
      { area_sqft: 125.5, created_at: "2026-02-20T12:00:00Z" },
      "Smith Residence", "Pool Deck 2026",
    );
    expect(s).toBe("125.5 sqft — Smith Residence, Pool Deck 2026, 2026-02-20");
  });

  it("falls back to 'no job' when jobName is empty / null", () => {
    const s = buildClipboardString(
      { type: "linear", unit: "ft", distance_ft: 20,
        created_at: "2026-02-20T00:00:00Z" },
      "Customer X", null,
    );
    expect(s).toContain(", no job, ");
  });
});


// ═════════════════════════════════════════════════════════════════
// (3) Fetch + render
// ═════════════════════════════════════════════════════════════════
describe("CustomerMeasurementsTab · fetch + render", () => {
  const CUSTOMER = { id: "cust-1", name: "Smith Residence" };

  it("fetches /measurements + /jobs and renders one row per measurement", async () => {
    _mockApiOnce({
      measurements: [
        { id: "m1", type: "linear", unit: "ft", distance_ft: 12,
          technician_name: "Mike", created_at: "2026-02-20T00:00:00Z" },
        { id: "m2", type: "area", unit: "sqft", area_sqft: 250,
          technician_name: "Sarah", created_at: "2026-02-19T00:00:00Z" },
      ],
      jobs: [],
    });

    render(<CustomerMeasurementsTab customer={CUSTOMER} />);

    await waitFor(() => expect(apiGetSpy).toHaveBeenCalledTimes(2));
    const paths = apiGetSpy.mock.calls.map((c) => c[0]);
    expect(paths).toEqual(expect.arrayContaining([
      "/measurements?customer_id=cust-1",
      "/jobs?customer_id=cust-1",
    ]));

    await screen.findByTestId("customer-measurement-row-m1");
    expect(screen.getByTestId("customer-measurement-value-m1").textContent)
      .toContain("12");
    expect(screen.getByTestId("customer-measurement-value-m1").textContent)
      .toContain("ft");
    expect(screen.getByTestId("customer-measurement-value-m2").textContent)
      .toContain("250");
    expect(screen.getByTestId("customer-measurement-value-m2").textContent)
      .toContain("sqft");
    expect(screen.getByTestId("customer-measurement-type-m1").textContent).toBe("Linear");
    expect(screen.getByTestId("customer-measurement-type-m2").textContent).toBe("Area");
    expect(screen.getByTestId("customer-measurement-tech-m1").textContent)
      .toContain("Mike");
    expect(screen.getByTestId("customer-measurements-count").textContent).toBe("2");
  });

  it("renders empty state when the API returns []", async () => {
    _mockApiOnce({ measurements: [], jobs: [] });
    render(<CustomerMeasurementsTab customer={CUSTOMER} />);
    await screen.findByTestId("customer-measurements-empty");
    expect(screen.queryByTestId("customer-measurements-list")).toBeNull();
  });
});


// ═════════════════════════════════════════════════════════════════
// (4) Job filter dropdown
// ═════════════════════════════════════════════════════════════════
describe("CustomerMeasurementsTab · job filter", () => {
  const CUSTOMER = { id: "cust-1", name: "Smith Residence" };

  it("filters rows down to a single job when picked", async () => {
    _mockApiOnce({
      measurements: [
        { id: "m1", type: "linear", unit: "ft", distance_ft: 10,
          job_id: "job-a", created_at: "2026-02-20T00:00:00Z" },
        { id: "m2", type: "linear", unit: "ft", distance_ft: 20,
          job_id: "job-b", created_at: "2026-02-20T00:00:00Z" },
        { id: "m3", type: "area", unit: "sqft", area_sqft: 30,
          created_at: "2026-02-20T00:00:00Z" },   // no job
      ],
      jobs: [
        { id: "job-a", title: "Pool Deck Landscape" },
        { id: "job-b", title: "Front Yard Sod" },
      ],
    });

    render(<CustomerMeasurementsTab customer={CUSTOMER} />);
    await screen.findByTestId("customer-measurement-row-m1");

    // Default = All jobs → all 3 visible
    expect(screen.queryByTestId("customer-measurement-row-m1")).toBeTruthy();
    expect(screen.queryByTestId("customer-measurement-row-m2")).toBeTruthy();
    expect(screen.queryByTestId("customer-measurement-row-m3")).toBeTruthy();

    // Pick job-a → only m1 shows
    fireEvent.change(screen.getByTestId("customer-measurements-job-filter"),
                       { target: { value: "job-a" } });
    expect(screen.queryByTestId("customer-measurement-row-m1")).toBeTruthy();
    expect(screen.queryByTestId("customer-measurement-row-m2")).toBeNull();
    expect(screen.queryByTestId("customer-measurement-row-m3")).toBeNull();

    // Pick "— no job — " → only m3 shows
    fireEvent.change(screen.getByTestId("customer-measurements-job-filter"),
                       { target: { value: "__nojob__" } });
    expect(screen.queryByTestId("customer-measurement-row-m1")).toBeNull();
    expect(screen.queryByTestId("customer-measurement-row-m2")).toBeNull();
    expect(screen.queryByTestId("customer-measurement-row-m3")).toBeTruthy();
  });
});


// ═════════════════════════════════════════════════════════════════
// (5) Copy to Quote
// ═════════════════════════════════════════════════════════════════
describe("CustomerMeasurementsTab · Copy to Quote", () => {
  const CUSTOMER = { id: "cust-1", name: "Smith Residence" };

  it("copies the M2-formatted string to the clipboard + fires success toast", async () => {
    _mockApiOnce({
      measurements: [
        { id: "m1", type: "area", unit: "sqft", area_sqft: 125.5,
          job_id: "job-a", technician_name: "Mike",
          created_at: "2026-02-20T12:00:00Z" },
      ],
      jobs: [{ id: "job-a", title: "Pool Deck 2026" }],
    });

    render(<CustomerMeasurementsTab customer={CUSTOMER} />);
    await screen.findByTestId("customer-measurement-row-m1");

    fireEvent.click(screen.getByTestId("customer-measurement-copy-m1"));

    await waitFor(() => expect(clipboardSpy).toHaveBeenCalledTimes(1));
    expect(clipboardSpy).toHaveBeenCalledWith(
      "125.5 sqft — area — Smith Residence, Pool Deck 2026, 2026-02-20",
    );
    await waitFor(() => expect(toastSuccessSpy).toHaveBeenCalledTimes(1));
    expect(toastSuccessSpy.mock.calls[0][0]).toBe("Copied to clipboard");
  });

  it("uses 'no job' when the row has no job_id", async () => {
    _mockApiOnce({
      measurements: [
        { id: "m2", type: "linear", unit: "ft", distance_ft: 20,
          created_at: "2026-02-20T00:00:00Z" },
      ],
      jobs: [],
    });
    render(<CustomerMeasurementsTab customer={CUSTOMER} />);
    await screen.findByTestId("customer-measurement-row-m2");
    fireEvent.click(screen.getByTestId("customer-measurement-copy-m2"));
    await waitFor(() => expect(clipboardSpy).toHaveBeenCalledTimes(1));
    expect(clipboardSpy.mock.calls[0][0]).toBe(
      "20 ft — linear — Smith Residence, no job, 2026-02-20",
    );
  });

  it("fires the error toast when the clipboard write throws", async () => {
    clipboardSpy.mockRejectedValueOnce(new Error("perm denied"));
    _mockApiOnce({
      measurements: [
        { id: "m3", type: "area", unit: "sqft", area_sqft: 1,
          created_at: "2026-02-20T00:00:00Z" },
      ],
      jobs: [],
    });
    render(<CustomerMeasurementsTab customer={CUSTOMER} />);
    await screen.findByTestId("customer-measurement-row-m3");
    fireEvent.click(screen.getByTestId("customer-measurement-copy-m3"));
    await waitFor(() => expect(toastErrorSpy).toHaveBeenCalledTimes(1));
    expect(toastSuccessSpy).not.toHaveBeenCalled();
  });
});
