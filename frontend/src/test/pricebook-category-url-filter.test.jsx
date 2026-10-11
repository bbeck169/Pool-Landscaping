/**
 * Pricebook Category UX fixes · Feb-2026 — Task C.
 *
 * Vitest coverage for the PriceBook URL-param category filter.
 *
 * Cases:
 *   1. ``/pricebook?category_id=<id>`` hydrates the filter on mount,
 *      the dismissible chip renders with the resolved category
 *      name, and the row grid is pre-filtered to that category.
 *   2. Clicking the chip's ✕ clears the URL param + removes the
 *      chip so a reload no longer re-applies the filter.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const mockGet = vi.fn();

vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: () => Promise.resolve({}),
    patch: () => Promise.resolve({}),
    del: () => Promise.resolve({}),
  },
}));
vi.mock("sonner", () => ({
  toast: Object.assign(() => {},
    { success: () => {}, error: () => {} }),
}));
// Stub out useAuth / useIndustries hooks that OpsHub transitively
// imports — the PriceBook sub-component only reads ``user.role``.
vi.mock("@/hooks/useAuth", () => ({
  useAuth: () => ({ user: { role: "admin", id: "u-1" } }),
}));
vi.mock("@/hooks/useIndustries", () => ({
  useIndustries: () => ({ industries: ["pool"] }),
}));

// Avoid pulling the full OpsHub shell — mount only the named
// ``PriceBook`` export. OpsHub.jsx exports it at module-scope so
// vitest can mount it in isolation without the surrounding tabs.
import { PriceBook } from "@/pages/ops/OpsHub";

beforeEach(() => {
  mockGet.mockReset();
});

const _seedItems = [
  { id: "it-1", name: "Weekly Service", unit: "each",
     service_category_id: "svc-10", income_category_id: "inc-1",
     item_type: "service", unit_price: 100, tax_rate: 0 },
  { id: "it-2", name: "Chlorine Tabs", unit: "lb",
     service_category_id: "svc-20", income_category_id: "inc-2",
     item_type: "product", unit_price: 5, tax_rate: 0 },
  { id: "it-3", name: "Pump Repair", unit: "job",
     service_category_id: "svc-10", income_category_id: "inc-1",
     item_type: "service", unit_price: 300, tax_rate: 0 },
];

const _seedServiceCats = [
  { id: "svc-10", name: "Weekly Maintenance", is_archived: false },
  { id: "svc-20", name: "Chemicals", is_archived: false },
];

function _wireFetches() {
  mockGet.mockImplementation((url) => {
    if (url === "/items") return Promise.resolve(_seedItems);
    if (url === "/service-categories") {
      return Promise.resolve({ items: _seedServiceCats });
    }
    if (url === "/income-categories") {
      return Promise.resolve({
        items: [
          { id: "inc-1", name: "Service Revenue", is_archived: false },
          { id: "inc-2", name: "Chemical Sales",  is_archived: false },
        ],
      });
    }
    if (url === "/pricebook/suppliers") return Promise.resolve([]);
    return Promise.resolve([]);
  });
}

describe("PriceBook · ?category_id URL filter · Task C", () => {
  it("hydrates the filter from the URL + renders the dismissible chip + filters rows", async () => {
    _wireFetches();
    render(
      <MemoryRouter initialEntries={["/pricebook?t=pricebook&category_id=svc-10"]}>
        <PriceBook />
      </MemoryRouter>,
    );
    // Chip renders with the resolved category name.
    const chip = await screen.findByTestId("pricebook-category-chip");
    expect(chip).toBeInTheDocument();
    const chipName = await screen.findByTestId("pricebook-category-chip-name");
    expect(chipName.textContent).toBe("Weekly Maintenance");

    // Rows: only the two svc-10 items (it-1 + it-3) remain in the
    // filtered grid; the svc-20 "Chlorine Tabs" row drops out.
    await waitFor(() => {
      expect(screen.queryByText("Weekly Service")).toBeInTheDocument();
    });
    expect(screen.queryByText("Pump Repair")).toBeInTheDocument();
    expect(screen.queryByText("Chlorine Tabs")).not.toBeInTheDocument();
  });

  it("clicking the chip's ✕ strips category_id from the URL + removes the chip + restores all rows", async () => {
    _wireFetches();
    render(
      <MemoryRouter initialEntries={["/pricebook?t=pricebook&category_id=svc-10"]}>
        <PriceBook />
      </MemoryRouter>,
    );
    const chip = await screen.findByTestId("pricebook-category-chip");
    expect(chip).toBeInTheDocument();
    fireEvent.click(chip);
    // Chip vanishes once the URL param is cleared.
    await waitFor(() => {
      expect(screen.queryByTestId("pricebook-category-chip")).toBeNull();
    });
    // All three seed rows now visible again.
    expect(screen.queryByText("Weekly Service")).toBeInTheDocument();
    expect(screen.queryByText("Chlorine Tabs")).toBeInTheDocument();
    expect(screen.queryByText("Pump Repair")).toBeInTheDocument();
  });
});
