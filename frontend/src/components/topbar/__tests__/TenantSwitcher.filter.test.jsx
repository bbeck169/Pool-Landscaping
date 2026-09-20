/**
 * Phase G3.3 · Feb-2026 — TenantSwitcher dropdown text-filter.
 *
 * With super_admin now seeing every active tenant on the platform
 * (post-S1 hotfix), the dropdown can carry 100+ rows. G3.3 adds a
 * substring filter over ``name || slug || id`` when the list has
 * more than 6 rows. This suite covers the filter contract:
 *
 * 1.  Filter input renders only when memberships > 6.
 * 2.  Typing narrows the visible rows (name match).
 * 3.  Typing also matches slug + id.
 * 4.  No-match state renders the ``empty`` block.
 * 5.  Case-insensitive match.
 * 6.  Filter resets when the menu closes+reopens.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach }
       from "vitest";
import { MemoryRouter } from "react-router-dom";
import { render, screen, cleanup, fireEvent, act }
       from "@testing-library/react";


const useAuthMock = vi.fn();
const usePermissionsMock = vi.fn();


vi.mock("@/api", () => ({
  api: { post: vi.fn(), get: () => Promise.resolve({}) },
  TOKEN_KEY: "token",
}));

vi.mock("@/auth", () => ({
  useAuth: () => useAuthMock(),
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => usePermissionsMock(),
}));

vi.mock("@/theme", () => ({
  colors: {
    surface: "#fff",  surfaceSecondary: "#F4F4F5",
    border: "#E4E4E7", borderStrong: "#D4D4D8",
    muted: "#71717A", onSurface: "#09090B",
    onSurfaceSecondary: "#52525B",
    brand: "#0284C7", error: "#DC2626", warning: "#CA8A04",
    onBrandPrimary: "#FFFFFF",
  },
}));


import TenantSwitcher from "@/components/topbar/TenantSwitcher";


beforeEach(() => {
  useAuthMock.mockReset();
  usePermissionsMock.mockReset();
});
afterEach(() => cleanup());


function _tenants(names) {
  return names.map((n, i) => ({
    id: `t-${i}-${n.toLowerCase().replace(/\s+/g, "-")}`,
    name: n,
    slug: n.toLowerCase().replace(/\s+/g, "-"),
    is_active_now: i === 0,
    role: "super_admin",
  }));
}


function _renderWith(memberships) {
  useAuthMock.mockReturnValue({
    user: {
      role: "super_admin",
      active_tenant_id: memberships[0]?.id,
      available_tenants: memberships,
    },
  });
  usePermissionsMock.mockReturnValue({ effectiveRole: "super_admin" });
  return render(
    <MemoryRouter>
      <TenantSwitcher />
    </MemoryRouter>,
  );
}


describe("TenantSwitcher · G3.3 dropdown filter", () => {

  it("filter input is HIDDEN when memberships ≤ 6", () => {
    _renderWith(_tenants(["Aquaterra", "Pool Pilot"]));
    fireEvent.click(screen.getByTestId("topbar-tenant-switcher-btn"));
    expect(
      screen.queryByTestId("topbar-tenant-switcher-filter"),
    ).toBeNull();
  });

  it("filter input renders when memberships > 6", () => {
    const many = _tenants([
      "Aquaterra", "Pool Pilot", "Landscape Co", "Blue Valley",
      "Sunset Pools", "Green Yards", "River Estates",
    ]);
    _renderWith(many);
    fireEvent.click(screen.getByTestId("topbar-tenant-switcher-btn"));
    expect(
      screen.getByTestId("topbar-tenant-switcher-filter"),
    ).toBeInTheDocument();
  });

  it("typing narrows the visible rows by name (case-insensitive)", () => {
    const many = _tenants([
      "Aquaterra", "Pool Pilot", "Landscape Co", "Blue Valley",
      "Sunset Pools", "Green Yards", "River Estates",
    ]);
    _renderWith(many);
    fireEvent.click(screen.getByTestId("topbar-tenant-switcher-btn"));

    const input = screen.getByTestId("topbar-tenant-switcher-filter");
    fireEvent.change(input, { target: { value: "pool" } });

    // Pool Pilot + Sunset Pools should be visible (name contains
    // "pool"); Aquaterra should NOT.
    const rows = screen.queryAllByRole("menuitem");
    const names = rows.map((r) => r.textContent);
    expect(names.some((n) => /Pool Pilot/.test(n))).toBe(true);
    expect(names.some((n) => /Sunset Pools/.test(n))).toBe(true);
    expect(names.some((n) => /Aquaterra/.test(n))).toBe(false);
  });

  it("filter matches slug and id as well as name", () => {
    const many = _tenants([
      "Aquaterra", "Pool Pilot", "Landscape Co", "Blue Valley",
      "Sunset Pools", "Green Yards", "River Estates",
    ]);
    _renderWith(many);
    fireEvent.click(screen.getByTestId("topbar-tenant-switcher-btn"));

    const input = screen.getByTestId("topbar-tenant-switcher-filter");
    // Any part of the id also matches — id is "t-2-landscape-co".
    fireEvent.change(input, { target: { value: "t-2" } });
    const rows = screen.queryAllByRole("menuitem");
    expect(rows.length).toBe(1);
    expect(rows[0].textContent).toMatch(/Landscape Co/);
  });

  it("no-match renders the empty state", () => {
    const many = _tenants([
      "Aquaterra", "Pool Pilot", "Landscape Co", "Blue Valley",
      "Sunset Pools", "Green Yards", "River Estates",
    ]);
    _renderWith(many);
    fireEvent.click(screen.getByTestId("topbar-tenant-switcher-btn"));

    const input = screen.getByTestId("topbar-tenant-switcher-filter");
    fireEvent.change(input, { target: { value: "zzzzz-nomatch" } });
    expect(
      screen.getByTestId("topbar-tenant-switcher-empty"),
    ).toBeInTheDocument();
    expect(screen.queryAllByRole("menuitem").length).toBe(0);
  });

  it("filter resets when the dropdown is closed + reopened", () => {
    const many = _tenants([
      "Aquaterra", "Pool Pilot", "Landscape Co", "Blue Valley",
      "Sunset Pools", "Green Yards", "River Estates",
    ]);
    _renderWith(many);
    fireEvent.click(screen.getByTestId("topbar-tenant-switcher-btn"));

    const input = screen.getByTestId("topbar-tenant-switcher-filter");
    fireEvent.change(input, { target: { value: "pool" } });
    // Toggle closed.
    fireEvent.click(screen.getByTestId("topbar-tenant-switcher-btn"));
    // Reopen.
    fireEvent.click(screen.getByTestId("topbar-tenant-switcher-btn"));
    const inputAgain = screen.getByTestId("topbar-tenant-switcher-filter");
    expect(inputAgain.value).toBe("");
    expect(screen.queryAllByRole("menuitem").length).toBe(many.length);
  });
});
