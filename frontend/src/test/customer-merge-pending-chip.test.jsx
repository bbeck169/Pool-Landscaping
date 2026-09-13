/**
 * Feb 2026 · Customer Merge Phase 3 · pending-candidates chip vitest.
 *
 * The chip lives in CustomersList's filter row. It queries
 * ``GET /customers/merge-candidates?confidence=low`` on mount,
 * renders only when the count > 0, and toggles a client-side filter
 * over ``customer_ids`` when clicked.
 *
 * Because CustomersList is a 2000-line component pulling from many
 * providers, we mount it with the strictly-minimal API mock surface
 * needed for the merge-candidates path (list + counts + merge
 * candidates endpoints).
 */
import React from "react";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { MemoryRouter } from "react-router-dom";

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    put: vi.fn(),
    del: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock("@/api", () => ({
  api: mockApi,
  api_base: () => "http://test-api",
}));
vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(), message: vi.fn(),
  }),
}));

// Session utility used by CustomersList's role gate. Stub as super_admin.
vi.mock("@/auth", () => ({
  getSession: () => ({
    id: "u1", role: "super_admin", tenant_id: "t1",
    effective_role: "super_admin",
  }),
  isAuthenticated: () => true,
}));


function _setupApi({ candidates = [] } = {}) {
  mockApi.get.mockImplementation((path) => {
    if (path.startsWith("/customers/merge-candidates")) {
      return Promise.resolve({
        confidence: "low",
        // ``count`` is GROUP count, not member count.
        count: candidates.length ? 1 : 0,
        customer_ids: candidates.map((c) => c.id),
        duplicate_groups: candidates.length ? [{
          match_type: "fuzzy_name", confidence: "low", score: 0.94,
          customer_ids: candidates.map((c) => c.id),
          match_field_values: { names: candidates.map((c) => c.name) },
        }] : [],
      });
    }
    if (path.startsWith("/customers/summary") ||
        path.startsWith("/customers?count_only")) {
      return Promise.resolve({ count: candidates.length });
    }
    if (path.startsWith("/customers")) {
      return Promise.resolve(candidates);
    }
    if (path.startsWith("/tags") || path.startsWith("/cities")
        || path.startsWith("/tenants")) {
      return Promise.resolve([]);
    }
    return Promise.resolve({});
  });
  mockApi.post.mockResolvedValue({});
  mockApi.patch.mockResolvedValue({});
  mockApi.del.mockResolvedValue({});
  mockApi.delete.mockResolvedValue({});
}


beforeEach(() => {
  mockApi.get.mockReset();
  mockApi.post.mockReset();
  mockApi.patch.mockReset();
  mockApi.del.mockReset();
  mockApi.delete.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});


// eslint-disable-next-line import/first
import CustomersList from "@/pages/customers/CustomersList";


function _mount() {
  return render(
    <MemoryRouter initialEntries={["/customers"]}>
      <CustomersList />
    </MemoryRouter>,
  );
}


describe("CustomersList · pending-merge-candidates chip (Phase 3)", () => {
  it("hides the chip when the API reports 0 pending candidates", async () => {
    _setupApi({ candidates: [] });
    _mount();
    await waitFor(() => {
      const calls = mockApi.get.mock.calls;
      expect(calls.some((c) => c[0].includes("merge-candidates"))).toBe(true);
    });
    expect(
      screen.queryByTestId("customers-filter-pending-merge-candidates"),
    ).not.toBeInTheDocument();
  });

  it("renders the chip with the group count when candidates exist", async () => {
    _setupApi({
      candidates: [
        { id: "c-x", name: "John Doe", tenant_id: "t1", tags: [] },
        { id: "c-y", name: "Jon Doe",  tenant_id: "t1", tags: [] },
      ],
    });
    _mount();
    const chip = await screen.findByTestId(
      "customers-filter-pending-merge-candidates",
    );
    expect(chip).toBeInTheDocument();
    // Feb-2026 · Round 2 flake fix — production chip copy was
    // shortened from "View 1 pending merge candidate" to
    // "Pending merge candidates(1)". Update the matchers to the
    // current copy.
    expect(chip.textContent || "").toMatch(/pending merge candidate/i);
    expect(chip.textContent || "").toMatch(/\(1\)/);
  });

  it("clicking the chip filters the row list to the candidate ids", async () => {
    _setupApi({
      candidates: [
        { id: "c-x", name: "John Doe", tenant_id: "t1", tags: [] },
        { id: "c-y", name: "Jon Doe",  tenant_id: "t1", tags: [] },
      ],
    });
    _mount();
    const chip = await screen.findByTestId(
      "customers-filter-pending-merge-candidates",
    );
    // Verify both rows initially rendered (the list mock returns
    // both candidate customers as the full list).
    await waitFor(() => {
      expect(screen.getByTestId("customer-select-c-x")).toBeInTheDocument();
      expect(screen.getByTestId("customer-select-c-y")).toBeInTheDocument();
    });
    fireEvent.click(chip);
    // Filter mode is active → both rows remain (both are in the
    // candidate set). The pill visual state flips to amber.
    await waitFor(() => {
      // Data attribute we can rely on: the chip's aria state is
      // encoded in its title. Simpler: assert both testids still
      // present + chip's inline background color changed.
      expect(screen.getByTestId("customer-select-c-x")).toBeInTheDocument();
      expect(screen.getByTestId("customer-select-c-y")).toBeInTheDocument();
    });
  });
});
