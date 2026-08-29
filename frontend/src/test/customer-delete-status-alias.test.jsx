/**
 * Feb-2026 · Customer Delete UX overhaul — Dashboard KPI tile-swap
 * URL alias.
 *
 * Dashboard's Active/Inactive KPI tiles navigate to
 * ``/customers?status=active`` / ``/customers?status=inactive``.
 * ``CustomersList`` historically only understood ``?tab=`` so the
 * Inactive tile silently landed on Active. Folded into this phase's
 * scope: teach ``CustomersList`` to accept ``?status`` as an alias
 * for ``?tab`` (backwards-compat: ``?tab`` still wins when both are
 * present).
 *
 * Locks:
 *   1. ``/customers?status=inactive`` lands the Inactive tab
 *      (background style = ``colors.brandTertiary``).
 *   2. ``/customers?status=active`` lands the Active tab.
 *   3. ``/customers?tab=inactive`` (legacy) still lands Inactive.
 *   4. Both present (``?tab=active&status=inactive``): ``tab`` wins.
 *   5. Admin (not super_admin) sees the "Include soft-deleted"
 *      filter chip — role widening from the overhaul.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ── shared mocks ────────────────────────────────────────────────
let _role = "admin";

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    role: _role,
    effectiveRole: _role,
    isAdmin: _role === "admin" || _role === "super_admin",
    isAdminOrManager:
      _role === "admin" || _role === "super_admin" || _role === "manager",
    canDo: () => true,
  }),
}));

const _apiGet = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => _apiGet(...a),
    post: vi.fn(() => Promise.resolve({})),
    put: vi.fn(() => Promise.resolve({})),
    del: vi.fn(() => Promise.resolve({})),
    delete: vi.fn(() => Promise.resolve({})),
    patch: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(), info: vi.fn(),
  }),
}));


import CustomersList from "@/pages/customers/CustomersList";


beforeEach(() => {
  _apiGet.mockReset();
  _apiGet.mockImplementation((path) => {
    if (path.startsWith("/customer-tags")) return Promise.resolve({ items: [] });
    if (path.includes("count_only=true")) return Promise.resolve({ count: 0 });
    return Promise.resolve({
      items: [],
      total: 0, page: 1, page_size: 100, total_pages: 0,
    });
  });
  try { localStorage.clear(); } catch { /* jsdom */ }
});


function _mount(url, role = "admin") {
  _role = role;
  return render(
    <MemoryRouter initialEntries={[url]}>
      <CustomersList />
    </MemoryRouter>,
  );
}


function _isActiveTab(node) {
  // Active tab in this list uses the ``brandTertiary`` bg (#E0F2FE
  // → rgb(224, 242, 254) in JSDOM). Non-active tabs are transparent.
  const bg = (node.style.backgroundColor || "").replace(/\s/g, "");
  return bg !== "" && bg !== "transparent";
}


describe("CustomersList · ?status alias (KPI tile deep-link)", () => {
  it("?status=inactive lands the Inactive tab", async () => {
    _mount("/customers?status=inactive", "admin");
    const inactive = await screen.findByTestId("tab-inactive");
    const active = screen.getByTestId("tab-active");
    await waitFor(() => expect(_isActiveTab(inactive)).toBe(true));
    expect(_isActiveTab(active)).toBe(false);
  });

  it("?status=active lands the Active tab", async () => {
    _mount("/customers?status=active", "admin");
    const active = await screen.findByTestId("tab-active");
    const inactive = screen.getByTestId("tab-inactive");
    await waitFor(() => expect(_isActiveTab(active)).toBe(true));
    expect(_isActiveTab(inactive)).toBe(false);
  });

  it("?tab=inactive (legacy) still lands the Inactive tab", async () => {
    _mount("/customers?tab=inactive", "admin");
    const inactive = await screen.findByTestId("tab-inactive");
    await waitFor(() => expect(_isActiveTab(inactive)).toBe(true));
  });

  it("?tab wins over ?status when both are present", async () => {
    _mount("/customers?tab=active&status=inactive", "admin");
    const active = await screen.findByTestId("tab-active");
    const inactive = screen.getByTestId("tab-inactive");
    await waitFor(() => expect(_isActiveTab(active)).toBe(true));
    expect(_isActiveTab(inactive)).toBe(false);
  });
});


describe("CustomersList · role widening (Feb-2026 delete overhaul)", () => {
  it("admin (not super_admin) sees the 'Include soft-deleted' filter chip", async () => {
    _mount("/customers", "admin");
    // Widened from super_admin-only — admin now sees the chip.
    const chip = await screen.findByTestId("customers-filter-include-deleted");
    expect(chip).toBeTruthy();
  });

  it("technician does NOT see the 'Include soft-deleted' chip", async () => {
    _mount("/customers", "technician");
    // Give the list a beat to render.
    await screen.findByTestId("customers-cohort-tabs").catch(() => null);
    expect(screen.queryByTestId("customers-filter-include-deleted"))
      .toBeNull();
  });
});
