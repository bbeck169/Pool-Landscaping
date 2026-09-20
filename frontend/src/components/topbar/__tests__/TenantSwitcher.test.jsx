/**
 * Phase T1.5 · Feb-2026 — TenantSwitcher vitest suite.
 *
 * Covers:
 *   1. Hidden when 0 memberships.
 *   2. Hidden when exactly 1 membership (single-tenant users).
 *   3. Renders with active tenant name when 2+ memberships.
 *   4. Click trigger → dropdown lists every tenant.
 *   5. Selecting another tenant POSTs /auth/switch-tenant with the
 *      correct id.
 *   6. After a successful switch, ``localStorage`` gets the new
 *      access token AND ``window.location.reload()`` is called.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach }
       from "vitest";
import { MemoryRouter } from "react-router-dom";
import { render, screen, cleanup, fireEvent, waitFor }
       from "@testing-library/react";


const postMock      = vi.fn();
const useAuthMock   = vi.fn();
const reloadMock    = vi.fn();


vi.mock("@/api", () => ({
  api: {
    post: (...a) => postMock(...a),
    get:  () => Promise.resolve({}),
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


import TenantSwitcher from "@/components/topbar/TenantSwitcher";


function _render(ui) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}


beforeEach(() => {
  postMock.mockReset();
  useAuthMock.mockReset();
  reloadMock.mockReset();
  // JSDOM's window.location.reload is not spyable by default;
  // stub the assign path with a fresh object.
  Object.defineProperty(window, "location", {
    writable: true,
    value: { ...window.location, reload: reloadMock },
  });
});
afterEach(() => cleanup());


describe("TenantSwitcher · visibility", () => {
  it("hidden with 0 memberships", () => {
    useAuthMock.mockReturnValue({
      user: { available_tenants: [] },
    });
    _render(<TenantSwitcher />);
    expect(screen.queryByTestId("topbar-tenant-switcher-btn")).toBeNull();
  });

  it("hidden with exactly 1 membership", () => {
    useAuthMock.mockReturnValue({
      user: {
        active_tenant_id: "t-a",
        available_tenants: [
          { id: "t-a", name: "Only",
            is_active_now: true, role: "admin" },
        ],
      },
    });
    _render(<TenantSwitcher />);
    expect(screen.queryByTestId("topbar-tenant-switcher-btn")).toBeNull();
  });

  it("renders trigger + active tenant name with 2+ memberships", () => {
    useAuthMock.mockReturnValue({
      user: {
        active_tenant_id: "t-a",
        available_tenants: [
          { id: "t-a", name: "Aquaterra",
            is_active_now: true, role: "admin" },
          { id: "t-b", name: "Pool Pilot",
            is_active_now: false, role: "admin" },
        ],
      },
    });
    _render(<TenantSwitcher />);
    const btn = screen.getByTestId("topbar-tenant-switcher-btn");
    expect(btn).toBeInTheDocument();
    expect(btn.textContent).toContain("Aquaterra");
  });
});


describe("TenantSwitcher · switch flow", () => {
  it("dropdown lists every tenant on trigger click", () => {
    useAuthMock.mockReturnValue({
      user: {
        active_tenant_id: "t-a",
        available_tenants: [
          { id: "t-a", name: "Aquaterra",
            is_active_now: true, role: "admin" },
          { id: "t-b", name: "Pool Pilot",
            is_active_now: false, role: "admin" },
        ],
      },
    });
    _render(<TenantSwitcher />);
    fireEvent.click(
      screen.getByTestId("topbar-tenant-switcher-btn"));
    expect(screen.getByTestId(
      "topbar-tenant-switcher-item-t-a")).toBeInTheDocument();
    expect(screen.getByTestId(
      "topbar-tenant-switcher-item-t-b")).toBeInTheDocument();
  });

  it("selecting another tenant fires POST with correct id + reloads", async () => {
    useAuthMock.mockReturnValue({
      user: {
        active_tenant_id: "t-a",
        available_tenants: [
          { id: "t-a", name: "Aquaterra",
            is_active_now: true, role: "admin" },
          { id: "t-b", name: "Pool Pilot",
            is_active_now: false, role: "admin" },
        ],
      },
    });
    postMock.mockResolvedValue({
      access_token: "new-token-xyz",
      active_tenant: { id: "t-b", name: "Pool Pilot" },
    });
    _render(<TenantSwitcher />);
    fireEvent.click(
      screen.getByTestId("topbar-tenant-switcher-btn"));
    fireEvent.click(
      screen.getByTestId("topbar-tenant-switcher-item-t-b"));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith(
        "/auth/switch-tenant", { tenant_id: "t-b" }),
    );
    await waitFor(() => {
      expect(localStorage.getItem("token")).toBe("new-token-xyz");
    });
    expect(reloadMock).toHaveBeenCalled();
  });

  it("selecting the ALREADY-active tenant is a no-op", async () => {
    useAuthMock.mockReturnValue({
      user: {
        active_tenant_id: "t-a",
        available_tenants: [
          { id: "t-a", name: "Aquaterra",
            is_active_now: true, role: "admin" },
          { id: "t-b", name: "Pool Pilot",
            is_active_now: false, role: "admin" },
        ],
      },
    });
    _render(<TenantSwitcher />);
    fireEvent.click(
      screen.getByTestId("topbar-tenant-switcher-btn"));
    fireEvent.click(
      screen.getByTestId("topbar-tenant-switcher-item-t-a"));
    expect(postMock).not.toHaveBeenCalled();
    expect(reloadMock).not.toHaveBeenCalled();
  });
});
