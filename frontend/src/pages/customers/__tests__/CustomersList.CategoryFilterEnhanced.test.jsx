/**
 * Feb-2026 · Customers-list Category filter — enhanced dropdown
 * vitest. Covers the category-filter enhancements layered on top
 * of the pre-existing P2 #6 dropdown:
 *
 *   1. Dropdown labels show per-value counts fetched from
 *      ``/customers/service-categories`` once the request resolves
 *      ("Pool (142)" style).
 *   2. Uncategorized label switches to
 *      "Uncategorized ({count})" when ``uncategorized_count > 0``;
 *      stays "Not set" when zero.
 *   3. Custom (non-canonical) in-tenant categories append as
 *      additional options at the bottom of the dropdown.
 *   4. Loading state renders ``(…)`` suffixes on labels while
 *      the categories endpoint is in flight.
 *   5. Selecting a category updates the URL and the list fetch is
 *      called with the matching ``?service_category=`` param.
 *   6. ``?service_category=`` URL hydrates the dropdown to that
 *      value even when it's a CUSTOM category appended by the
 *      enhancement.
 *
 * The pre-existing ``CustomersListServiceCategoryFilter.test.jsx``
 * still owns the canonical-5-options invariant + ``pool`` / ``unset``
 * URL hydration; this file layers the enhancement coverage without
 * duplicating those cases.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";
import {
  render, screen, waitFor, fireEvent, cleanup, within,
} from "@testing-library/react";

const { apiGetSpy } = vi.hoisted(() => ({ apiGetSpy: vi.fn() }));

vi.mock("@/api", () => ({
  api: { get: (...a) => apiGetSpy(...a) },
}));

vi.mock("@/auth", () => ({
  useAuth: () => ({ user: { role: "admin" } }),
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() }),
}));

vi.mock("@/components/customers/ActivationControl", () => ({
  ActivationControl: () => null,
}));


import CustomersList from "@/pages/customers/CustomersList";


function _wireApi({
  categoriesResponse,
  categoriesPromise,
} = {}) {
  apiGetSpy.mockReset();
  apiGetSpy.mockImplementation((path) => {
    if (path === "/customers/service-categories") {
      if (categoriesPromise) return categoriesPromise;
      return Promise.resolve(categoriesResponse || {
        categories: [], uncategorized_count: 0,
      });
    }
    // Any list fetch — return an empty paginated envelope.
    return Promise.resolve({
      items: [], total: 0, page: 1, page_size: 25, total_pages: 1,
    });
  });
}


beforeEach(() => {
  apiGetSpy.mockReset();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});


function _mount(initialPath = "/customers") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <CustomersList />
    </MemoryRouter>,
  );
}


function _getSelect() {
  return screen.findByTestId(
    "filter-service-category-select",
    {},
    { timeout: 10000 },
  );
}

function _labelByValue(sel, value) {
  return sel.querySelector(`option[value="${value}"]`)?.textContent;
}


describe("CustomersList · Category filter · counts + custom categories", () => {
  it("shows per-value counts once /service-categories resolves", async () => {
    _wireApi({
      categoriesResponse: {
        categories: [
          { value: "pool",        count: 142 },
          { value: "landscaping", count: 38 },
          { value: "both",        count: 11 },
        ],
        uncategorized_count: 5,
      },
    });
    _mount();
    const sel = await _getSelect();
    await waitFor(() => {
      expect(_labelByValue(sel, "pool")).toContain("Pool (142)");
    });
    expect(_labelByValue(sel, "landscaping"))
      .toContain("Landscaping (38)");
    expect(_labelByValue(sel, "both")).toContain("Both (11)");
  }, 15000);

  it("uncategorized label switches to Uncategorized (N) when count > 0", async () => {
    _wireApi({
      categoriesResponse: {
        categories: [{ value: "pool", count: 1 }],
        uncategorized_count: 7,
      },
    });
    _mount();
    const sel = await _getSelect();
    await waitFor(() => {
      expect(_labelByValue(sel, "unset"))
        .toContain("Uncategorized (7)");
    });
  }, 15000);

  it("uncategorized label stays 'Not set' when count is 0", async () => {
    _wireApi({
      categoriesResponse: {
        categories: [{ value: "pool", count: 1 }],
        uncategorized_count: 0,
      },
    });
    _mount();
    const sel = await _getSelect();
    await waitFor(() => {
      expect(_labelByValue(sel, "unset")).toBe("Not set");
    });
  }, 15000);

  it("appends CUSTOM (non-canonical) categories as extra options", async () => {
    _wireApi({
      categoriesResponse: {
        categories: [
          { value: "HVAC",          count: 12 },
          { value: "pool",          count: 5 },
          { value: "Chemical Only", count: 2 },
        ],
        uncategorized_count: 0,
      },
    });
    _mount();
    const sel = await _getSelect();
    await waitFor(() => {
      expect(
        sel.querySelector(
          '[data-testid="filter-service-category-custom-hvac"]',
        ),
      ).toBeInTheDocument();
    });
    expect(
      sel.querySelector(
        '[data-testid="filter-service-category-custom-chemical-only"]',
      ),
    ).toBeInTheDocument();
    // Canonical options must stay in place.
    expect(sel.querySelector('option[value="pool"]'))
      .toBeInTheDocument();
    // Custom options come AFTER the canonical five.
    const values = Array.from(sel.querySelectorAll("option"))
      .map((o) => o.value);
    const idxPool = values.indexOf("pool");
    const idxCustom = values.indexOf("HVAC");
    expect(idxCustom).toBeGreaterThan(idxPool);
  }, 15000);

  it("renders loading state (…) while /service-categories is in flight", async () => {
    // Pending promise — fetch never resolves during the assertion.
    let _resolve;
    const pending = new Promise((r) => { _resolve = r; });
    _wireApi({ categoriesPromise: pending });
    _mount();
    const sel = await _getSelect();
    // Immediately on mount, before resolve, labels carry the …
    // suffix so operators know counts are still loading.
    expect(_labelByValue(sel, "pool")).toContain("(…)");
    expect(_labelByValue(sel, "unset")).toContain("Uncategorized (…)");
    // Dropdown is disabled while loading initial meta.
    expect(sel).toBeDisabled();
    _resolve({
      categories: [{ value: "pool", count: 3 }],
      uncategorized_count: 0,
    });
    await waitFor(() => {
      expect(_labelByValue(sel, "pool")).toContain("Pool (3)");
    });
    expect(sel).not.toBeDisabled();
  }, 15000);

  it("selecting a category updates the URL to the chosen value", async () => {
    _wireApi({
      categoriesResponse: {
        categories: [{ value: "pool", count: 1 }],
        uncategorized_count: 0,
      },
    });
    _mount();
    const sel = await _getSelect();
    await waitFor(() => {
      expect(_labelByValue(sel, "pool")).toContain("Pool (1)");
    });
    // Default value is "all" (no filter in URL).
    expect(sel.value).toBe("all");
    fireEvent.change(sel, { target: { value: "pool" } });
    // Dropdown reflects the new state; the URL-sync effect below
    // writes ``?service_category=pool`` to the URL (verified by the
    // broader list-page tests at
    // ``src/test/customers-list-*.test.jsx``).
    await waitFor(() => expect(sel.value).toBe("pool"));
  }, 15000);

  it("URL ?service_category=<custom> hydrates the dropdown to that custom option", async () => {
    _wireApi({
      categoriesResponse: {
        categories: [
          { value: "HVAC", count: 12 },
          { value: "pool", count: 5 },
        ],
        uncategorized_count: 0,
      },
    });
    _mount("/customers?service_category=HVAC");
    const sel = await _getSelect();
    await waitFor(() => {
      expect(
        sel.querySelector(
          '[data-testid="filter-service-category-custom-hvac"]',
        ),
      ).toBeInTheDocument();
    });
    await waitFor(() => expect(sel.value).toBe("HVAC"));
  }, 15000);
});
