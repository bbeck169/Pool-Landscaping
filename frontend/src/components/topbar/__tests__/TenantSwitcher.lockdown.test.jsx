/**
 * Phase S1.3 · Feb-2026 — TenantSwitcher lockdown vitest.
 *
 * The switcher is now a super_admin-only surface (fail-closed).
 * Any other role — including the previously-allowed ``admin`` —
 * gets a plain ``null`` render even when the user carries 2+
 * memberships.
 *
 * Cases:
 *   1. Admin with 2 memberships → null.
 *   2. Manager with 2 memberships → null.
 *   3. Technician with 2 memberships → null.
 *   4. Customer with 2 memberships → null.
 *   5. Super_admin with 2 memberships → renders + trigger visible.
 *   6. Super_admin with 1 membership → still null (nothing to switch).
 *   7. Loading auth state → null (fail-closed).
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach }
       from "vitest";
import { MemoryRouter } from "react-router-dom";
import { render, screen, cleanup }
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


const TWO_MEMBERSHIPS = {
  active_tenant_id: "t-a",
  available_tenants: [
    { id: "t-a", name: "Aquaterra",  is_active_now: true,  role: "admin" },
    { id: "t-b", name: "Pool Pilot", is_active_now: false, role: "admin" },
  ],
};


function _render() {
  return render(
    <MemoryRouter><TenantSwitcher /></MemoryRouter>,
  );
}


describe.each([
  ["admin"],
  ["manager"],
  ["technician"],
  ["customer"],
  ["office"],
])("TenantSwitcher · S1.3 lockdown — role=%s renders null", (role) => {
  it(`role=${role} → null with 2 memberships`, () => {
    useAuthMock.mockReturnValue({ user: { role, ...TWO_MEMBERSHIPS } });
    usePermissionsMock.mockReturnValue({ effectiveRole: role });
    _render();
    expect(screen.queryByTestId("topbar-tenant-switcher-btn"))
      .toBeNull();
  });
});


describe("TenantSwitcher · S1.3 lockdown — super_admin path", () => {
  it("super_admin + 2 memberships renders the trigger", () => {
    useAuthMock.mockReturnValue({
      user: { role: "super_admin", ...TWO_MEMBERSHIPS } });
    usePermissionsMock.mockReturnValue({ effectiveRole: "super_admin" });
    _render();
    expect(screen.getByTestId("topbar-tenant-switcher-btn"))
      .toBeInTheDocument();
  });

  it("super_admin + 1 membership → null (nothing to switch)", () => {
    useAuthMock.mockReturnValue({
      user: { role: "super_admin",
        active_tenant_id: "t-a",
        available_tenants: [
          { id: "t-a", name: "Solo",
            is_active_now: true, role: "super_admin" },
        ]}});
    usePermissionsMock.mockReturnValue({ effectiveRole: "super_admin" });
    _render();
    expect(screen.queryByTestId("topbar-tenant-switcher-btn"))
      .toBeNull();
  });

  it("loading auth state → null (fail-closed)", () => {
    useAuthMock.mockReturnValue({ loading: true, user: null });
    usePermissionsMock.mockReturnValue({ effectiveRole: "super_admin" });
    _render();
    expect(screen.queryByTestId("topbar-tenant-switcher-btn"))
      .toBeNull();
  });

  it("effectiveRole=super_admin but user.role=admin → still shown "
     + "(preview 'test as' path never demotes real supers)", () => {
    useAuthMock.mockReturnValue({
      user: { role: "admin", ...TWO_MEMBERSHIPS } });
    usePermissionsMock.mockReturnValue({ effectiveRole: "super_admin" });
    _render();
    expect(screen.getByTestId("topbar-tenant-switcher-btn"))
      .toBeInTheDocument();
  });
});
