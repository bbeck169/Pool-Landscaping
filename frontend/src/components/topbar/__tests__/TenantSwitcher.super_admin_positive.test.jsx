/**
 * Phase S1 hotfix · Feb-2026 — TenantSwitcher **positive** case
 * with the REAL ``usePermissions`` hook wired in.
 *
 * Motivation: the lockdown vitest suite
 * (``TenantSwitcher.lockdown.test.jsx``) mocks
 * ``@/hooks/usePermissions`` and can therefore report false-green if
 * the runtime hook ever drifts (e.g. reads from a different context,
 * gates on a stale ``previewRole`` value, etc.). This suite mounts
 * the switcher inside the real ``<PermissionsProvider>`` so we
 * exercise the actual hook path the pod uses.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach }
       from "vitest";
import { MemoryRouter } from "react-router-dom";
import { render, screen, cleanup }
       from "@testing-library/react";


const useAuthMock = vi.fn();


vi.mock("@/api", () => ({
  api: {
    post: vi.fn(),
    // ``usePermissions`` fires a GET /permissions on mount to hydrate
    // the matrix. Return an object shape the hook accepts.
    get: () => Promise.resolve({
      super_admin: {}, admin: {}, technician: {}, customer: {},
    }),
  },
  TOKEN_KEY: "token",
}));

vi.mock("@/auth", () => ({
  useAuth: () => useAuthMock(),
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


// Import the REAL provider + component. NO vi.mock on usePermissions.
import { PermissionsProvider }
       from "@/hooks/usePermissions";
import TenantSwitcher
       from "@/components/topbar/TenantSwitcher";


beforeEach(() => {
  useAuthMock.mockReset();
  // Belt-and-braces: some earlier tests may have persisted a preview
  // role. Clear it so the real hook resolves ``effectiveRole`` from
  // the user's actual role.
  try { window.sessionStorage.removeItem("aq-preview-role-v1"); } catch { /* noop */ }
});
afterEach(() => cleanup());


const SUPER_USER_TWO_TENANTS = {
  id: "u-super",
  email: "super@aquaterra.com",
  role: "super_admin",
  active_tenant_id: "t-a",
  available_tenants: [
    { id: "t-a", name: "Aquaterra",  is_active_now: true,
      role: "super_admin" },
    { id: "t-b", name: "Pool Pilot", is_active_now: false,
      role: "super_admin" },
  ],
};

const ADMIN_USER_TWO_TENANTS = {
  id: "u-admin",
  email: "admin@aquaterra.com",
  role: "admin",
  active_tenant_id: "t-a",
  available_tenants: [
    { id: "t-a", name: "Aquaterra",  is_active_now: true,
      role: "admin" },
    { id: "t-b", name: "Pool Pilot", is_active_now: false,
      role: "admin" },
  ],
};


function _render(user) {
  return render(
    <MemoryRouter>
      <PermissionsProvider user={user}>
        <TenantSwitcher />
      </PermissionsProvider>
    </MemoryRouter>,
  );
}


describe("TenantSwitcher · S1 hotfix positive case with real usePermissions",
  () => {

  it("super_admin with 2 memberships renders the trigger (real hook path)",
    () => {
      useAuthMock.mockReturnValue({ user: SUPER_USER_TWO_TENANTS });
      _render(SUPER_USER_TWO_TENANTS);
      expect(screen.getByTestId("topbar-tenant-switcher-btn"))
        .toBeInTheDocument();
    });

  it("admin with 2 memberships renders null (real hook path)", () => {
    useAuthMock.mockReturnValue({ user: ADMIN_USER_TWO_TENANTS });
    _render(ADMIN_USER_TWO_TENANTS);
    expect(screen.queryByTestId("topbar-tenant-switcher-btn"))
      .toBeNull();
  });

  it("super_admin with a stale preview role of 'admin' → still null "
     + "(fail-closed while previewing)", () => {
    // Simulate a super_admin that clicked "Test as admin" earlier —
    // usePermissions honours the preview and reports
    // ``effectiveRole = 'admin'``. The switcher must NOT render.
    try {
      window.sessionStorage.setItem("aq-preview-role-v1", "admin");
    } catch { /* noop */ }
    useAuthMock.mockReturnValue({ user: SUPER_USER_TWO_TENANTS });
    _render(SUPER_USER_TWO_TENANTS);
    expect(screen.queryByTestId("topbar-tenant-switcher-btn"))
      .toBeNull();
    // Cleanup for the next describe block if any.
    try {
      window.sessionStorage.removeItem("aq-preview-role-v1");
    } catch { /* noop */ }
  });
});
