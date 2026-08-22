/**
 * Feb-2026 · P28 — CustomersList "Muted" saved-view tab.
 *
 * Four assertions covering the toolbar chip round-trip:
 *   1. Muted tab visible for admin.
 *   2. Muted tab hidden for tech.
 *   3. Clicking Muted triggers the ``is_muted=true`` backend query.
 *   4. Row list re-renders with muted-only data + "Muted <ago>" label.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";


// ── Mocks — shared toggle so we can switch between admin/tech roles ──
let currentRole = "admin";

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    role: currentRole,
    effectiveRole: currentRole,
    isAdmin: currentRole === "admin" || currentRole === "super_admin",
    isAdminOrManager:
      currentRole === "admin" || currentRole === "super_admin"
      || currentRole === "manager",
    canDo: () => true,
  }),
}));

const mockGet = vi.fn();
vi.mock("@/api", () => ({
  api: {
    get: (...a) => mockGet(...a),
    post: vi.fn(() => Promise.resolve({})),
    put: vi.fn(() => Promise.resolve({})),
    delete: vi.fn(() => Promise.resolve({})),
    patch: vi.fn(() => Promise.resolve({})),
  },
}));

vi.mock("sonner", () => ({
  toast: Object.assign(vi.fn(), {
    success: vi.fn(), error: vi.fn(), warning: vi.fn(),
  }),
}));


import CustomersList from "@/pages/customers/CustomersList";


function _mount(role = "admin") {
  currentRole = role;
  return render(
    <MemoryRouter initialEntries={["/customers"]}>
      <CustomersList />
    </MemoryRouter>,
  );
}


// ── Route the mock's responses by URL path.
function _installGetRouter({ muted = [] } = {}) {
  mockGet.mockImplementation((path) => {
    if (path.startsWith("/customer-tags")) return Promise.resolve({ items: [] });
    if (path.includes("count_only=true")) {
      if (path.includes("is_muted=true")) return Promise.resolve({ count: muted.length });
      if (path.includes("is_active=true")) return Promise.resolve({ count: 3 });
      if (path.includes("is_active=false")) return Promise.resolve({ count: 1 });
      return Promise.resolve({ count: 0 });
    }
    if (path.includes("is_muted=true")) {
      // The Muted saved view — return only muted rows.
      return Promise.resolve(muted);
    }
    if (path.startsWith("/customers")) {
      // Default (Active) tab shows non-muted rows.
      return Promise.resolve([
        { id: "c-1", name: "Alpha Live", is_active: true },
        { id: "c-2", name: "Bravo Live", is_active: true },
      ]);
    }
    return Promise.resolve({});
  });
}


beforeEach(() => {
  mockGet.mockClear();
});


describe("CustomersList · P28 Muted saved view", () => {
  it("renders the Muted tab for admin", async () => {
    _installGetRouter();
    _mount("admin");
    // The tab element carries the ``tab-muted`` testid from TAB_DEFS.
    await waitFor(() => expect(screen.getByTestId("tab-muted")).toBeTruthy());
    expect(screen.getByTestId("tab-muted").textContent).toMatch(/Muted/i);
  });

  it("hides the Muted tab from tech role", async () => {
    _installGetRouter();
    _mount("technician");
    // Wait long enough for the initial render + effects. The Active
    // tab is always visible; Muted is admin-gated so must be absent.
    await waitFor(() => expect(screen.getByTestId("tab-active")).toBeTruthy());
    expect(screen.queryByTestId("tab-muted")).toBeNull();
  });

  it("clicking Muted issues the is_muted=true backend query and renders the muted list", async () => {
    const one_hour_ago = new Date(Date.now() - 3600_000).toISOString();
    _installGetRouter({
      muted: [
        { id: "c-mute-1", name: "Dispute Dan", is_active: false,
          is_muted: true, muted_at: one_hour_ago },
      ],
    });
    _mount("admin");
    // Wait for the tab bar.
    await waitFor(() => expect(screen.getByTestId("tab-muted")).toBeTruthy());
    // Click Muted.
    fireEvent.click(screen.getByTestId("tab-muted"));
    // Assert the muted list fetch fired with ?is_muted=true.
    await waitFor(() => {
      const calls = mockGet.mock.calls.map((c) => c[0]);
      expect(
        calls.some((p) => typeof p === "string"
          && p.startsWith("/customers?")
          && p.includes("is_muted=true")
          && !p.includes("count_only=true")),
      ).toBe(true);
    });
    // The row list re-renders with the muted seed row + "Muted <ago>".
    await waitFor(() =>
      expect(screen.getByTestId("customer-row-c-mute-1")).toBeTruthy());
    expect(screen.getByTestId("muted-badge-c-mute-1")).toBeTruthy();
    expect(screen.getByTestId("muted-since-c-mute-1").textContent)
      .toMatch(/Muted\s+\d+\w+\s+ago/);
  });
});
