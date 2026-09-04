/**
 * Phase K39a AMENDMENT · Feb-2026 — Customer-portal maps guard.
 *
 * Contract: the shell-level ``<MapsProviderGate>`` must NEVER wrap
 * customer-portal users. Staff users (admin, super_admin, manager,
 * technician, etc.) still get the wrapper.
 *
 * Covers:
 *   1. Customer role → no <MapsProviderGate> in the tree AND no
 *      google.maps / H.map <script> tag injected.
 *   2. Admin role → <MapsProviderGate> IS present.
 *   3. Unauthenticated portal visitor → structurally redirected to
 *      /portal/login (never reaches the maps mount branch).
 */
import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

// ── Global mocks (must be declared before importing AppLayout) ────
const _mockAuth = { user: null, loading: false, logout: vi.fn() };
vi.mock("@/auth", () => ({
  useAuth: () => _mockAuth,
}));
// The inner ``AppLayout`` component is the heavy part — mock it to
// a marker so we can focus solely on the wrapper-selection logic.
vi.mock("@/layouts/AdminSidebar", () => ({ default: () => null }));
vi.mock("@/layouts/AdminTopBar", () => ({ default: () => null }));
vi.mock("@/components/RolePreviewSwitcher", () => ({ default: () => null }));
vi.mock("@/hooks/usePermissions", () => ({ usePermissions: () => ({}) }));
vi.mock("@/hooks/useBrandTheme", () => ({ default: () => ({}) }));
vi.mock("@/pages/onboarding/OnboardingLoginModal", () => ({
  default: () => null,
}));
vi.mock("@/pages/onboarding/OnboardingChecklistDrawer", () => ({
  default: () => null,
}));
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    Outlet: () => <div data-testid="portal-shell-outlet" />,
    NavLink: (p) => <a {...p} />,
  };
});

// Trap ``<MapsProviderGate>`` so tests can assert its presence.
let _gateMountCount = 0;
vi.mock("@/lib/maps/MapsProviderGate", () => ({
  default: ({ children }) => {
    _gateMountCount += 1;
    return (
      <div data-testid="maps-provider-gate-mounted">{children}</div>
    );
  },
}));

// Guard: fail if anything sneaks in `@vis.gl/react-google-maps` at
// shell level for customer users. We can't detect script tag
// injection from CDN in JSDOM, but the direct-import path is what
// the customer-portal amendment forbids.
vi.mock("@vis.gl/react-google-maps", () => {
  return {
    APIProvider: ({ children }) => (
      <div data-testid="google-apiprovider-mounted">{children}</div>
    ),
    Map: () => null,
    AdvancedMarker: () => null,
    InfoWindow: () => null,
    Pin: () => null,
    useMap: () => null,
    useMapsLibrary: () => null,
  };
});

// Ensure the ``REACT_APP_GOOGLE_MAPS_API_KEY`` is present so the
// staff branch would definitely mount the gate (proves the customer
// guard actually blocks the mount).
if (!process.env.REACT_APP_GOOGLE_MAPS_API_KEY) {
  process.env.REACT_APP_GOOGLE_MAPS_API_KEY = "AIza-test-fixture";
}

let ProtectedShell;
beforeAll(async () => {
  vi.resetModules();
  ProtectedShell = (await import("@/layouts/AppLayout")).default;
});

afterEach(() => {
  cleanup();
  _mockAuth.user = null;
  _gateMountCount = 0;
});

function _renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/portal/login" element={<div data-testid="portal-login-page" />} />
        <Route path="/login" element={<div data-testid="staff-login-page" />} />
        <Route path="*" element={<ProtectedShell />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("K39a AMENDMENT · Customer portal must NOT mount MapsProviderGate", () => {
  it("customer role → no <MapsProviderGate>, no google-maps APIProvider", () => {
    _mockAuth.user = { id: "c1", email: "trina@example.com", role: "customer" };
    const { queryByTestId } = _renderAt("/portal/home");
    expect(queryByTestId("maps-provider-gate-mounted")).toBeNull();
    expect(queryByTestId("google-apiprovider-mounted")).toBeNull();
    expect(_gateMountCount).toBe(0);
    // Sanity: no ``<script>`` for Google Maps / HERE was injected into JSDOM.
    const scripts = Array.from(document.querySelectorAll("script")).map((s) => s.src);
    expect(
      scripts.some((src) =>
        /maps\.googleapis\.com|js\.api\.here\.com/.test(src || ""),
      ),
    ).toBe(false);
  });

  it("admin role → <MapsProviderGate> IS mounted", () => {
    _mockAuth.user = { id: "a1", email: "admin@example.com", role: "admin" };
    // Silence AppLayout's own render errors (unrelated to the guard);
    // we only care that MapsProviderGate mounted before any throw.
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    _renderAt("/dispatch");
    expect(_gateMountCount).toBeGreaterThanOrEqual(1);
    errSpy.mockRestore();
  });

  it("super_admin role → <MapsProviderGate> IS mounted", () => {
    _mockAuth.user = { id: "s1", email: "super@example.com", role: "super_admin" };
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    _renderAt("/dispatch");
    expect(_gateMountCount).toBeGreaterThanOrEqual(1);
    errSpy.mockRestore();
  });

  it("unauthenticated /portal/* → redirected to /portal/login (never reaches maps mount)", () => {
    _mockAuth.user = null;
    const { queryByTestId } = _renderAt("/portal/home");
    expect(queryByTestId("portal-login-page")).not.toBeNull();
    expect(queryByTestId("maps-provider-gate-mounted")).toBeNull();
    expect(_gateMountCount).toBe(0);
  });

  it("unauthenticated non-portal path → redirected to /login (also no maps mount)", () => {
    _mockAuth.user = null;
    const { queryByTestId } = _renderAt("/dispatch");
    expect(queryByTestId("staff-login-page")).not.toBeNull();
    expect(queryByTestId("maps-provider-gate-mounted")).toBeNull();
  });
});
