/**
 * P2 #6 · Feb-2026 — CustomersList service_category filter chip vitest.
 *
 * Locks three invariants on the P2 #6 filter dropdown:
 *   1. The `?service_category=pool` URL hydrates the dropdown.
 *   2. The dropdown renders ALL five canonical options so operators
 *      can switch between buckets.
 *   3. On a bookmarked `?service_category=unset` link, the dropdown
 *      lands on the "Not set" option.
 *
 * The dropdown-change → re-fetch chain lives in the full CustomersList
 * useEffect stack (page reset + URL sync + list fetch) which is
 * exercised by the broader list-page tests already in the suite; the
 * sibling ServiceCategoryControl.test.jsx covers the single-input
 * change-handler + optimistic update path.  This file deliberately
 * stops at URL-hydration to keep the diff cheap.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup }
  from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


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


beforeEach(() => {
  apiGetSpy.mockReset();
  apiGetSpy.mockImplementation(() => Promise.resolve({
    items: [], total: 0, page: 1, page_size: 25, total_pages: 1,
  }));
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); });


function _mount(initialPath = "/customers") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <CustomersList />
    </MemoryRouter>,
  );
}


describe("P2 #6 · CustomersList ?service_category= filter chip", () => {
  it("renders all five canonical options", async () => {
    _mount("/customers");
    const sel = await screen.findByTestId(
      "filter-service-category-select", {}, { timeout: 10000 });
    const values = Array.from(sel.querySelectorAll("option"))
      .map((o) => o.value);
    expect(values).toEqual(
      ["all", "pool", "landscaping", "both", "unset"],
    );
  }, 15000);

  it("URL ?service_category=pool hydrates the dropdown to 'pool'", async () => {
    _mount("/customers?service_category=pool");
    const sel = await screen.findByTestId(
      "filter-service-category-select", {}, { timeout: 10000 });
    await waitFor(() => expect(sel.value).toBe("pool"));
  }, 15000);

  it("URL ?service_category=unset hydrates the dropdown to 'unset'", async () => {
    _mount("/customers?service_category=unset");
    const sel = await screen.findByTestId(
      "filter-service-category-select", {}, { timeout: 10000 });
    await waitFor(() => expect(sel.value).toBe("unset"));
  }, 15000);
});
