/**
 * Feb-2026 UI Polish Addendum · duplicate-logo dedupe guard.
 *
 * The app-shell must render exactly ONE brand-logo <img> per viewport
 * mode, otherwise the header reads as duplicated. This test mounts
 * <AppLayout> for both an admin (desktop rail visible) and a
 * technician (same rail visibility) and asserts the count.
 *
 * Regression trigger: adding a <BrandLogo> back inside <AdminTopBar>
 * (or introducing any other shell-level logo instance) would flip
 * this count and fail the assertion.
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";

let _role = "super_admin";
vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { id: "u-1", role: _role, email: "u@x.com", name: "User" },
    loading: false,
    logout: vi.fn(),
  }),
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    can: () => true,
    effectiveRole: _role,
    role: _role,
    isAdmin: _role === "admin" || _role === "super_admin",
    isAdminOrManager: ["admin", "super_admin", "manager"].includes(_role),
    canDo: () => true,
    previewRole: null,
    setPreviewRole: vi.fn(),
    isPreviewing: false,
  }),
  Forbidden: () => <div data-testid="forbidden" />,
}));
// Stub api so useTenantBrand doesn't try to hit the network.
vi.mock("@/api", () => ({
  api: { get: vi.fn().mockResolvedValue({ id: "t", slug: "aquaterra", name: "PLV" }) },
}));

vi.mock("@/components/RolePreviewSwitcher", () => ({ default: () => null }));
vi.mock("@/layouts/AdminSidebar", () => ({ default: () => <div data-testid="admin-sidebar-stub" /> }));
vi.mock("@/layouts/AdminTopBar", () => ({ default: () => <div data-testid="admin-topbar-stub" /> }));
vi.mock("@/layouts/UniversalMenu", () => ({ default: () => null }));
vi.mock("@/components/LandscapingClockWidget", () => ({ default: () => null }));
vi.mock("@/components/AIDock/AIDock", () => ({ default: () => null }));
vi.mock("@/pages/portal/PortalWalkthrough", () => ({ default: () => null }));
vi.mock("@/components/legal/TosGate", () => ({ default: () => null }));
vi.mock("@/components/portal/ProfileCompletionGate", () => ({ default: () => null }));
vi.mock("@/components/breadcrumbs/Breadcrumbs", () => ({ default: () => null }));
vi.mock("@/components/legal/OnboardingGate", () => ({ default: ({ children }) => <>{children}</> }));
vi.mock("@/pages/onboarding/OnboardingPage", () => ({ OnboardingLoginModal: () => null }));
vi.mock("@vis.gl/react-google-maps", () => ({ APIProvider: ({ children }) => <>{children}</> }));

import AppLayout from "@/layouts/AppLayout";

function mount(role, initial = "/") {
  _role = role;
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <Routes>
        <Route path="*" element={<AppLayout />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("BrandLogo · single-instance guard", () => {
  it("admin shell renders exactly ONE brand-logo <img>", () => {
    mount("admin");
    // Any BrandLogo mount emits a data-testid ending in "-img"; the
    // canonical one is `side-nav-logo-img`. If a duplicate appears
    // in the top-nav (or anywhere else), this count flips to 2+.
    const shellLogos = document.querySelectorAll(
      '[data-testid="app-shell"] img[data-testid$="-logo-img"]',
    );
    expect(shellLogos.length).toBe(1);
    // The single logo lives inside the side-nav crown slot.
    expect(screen.getByTestId("side-nav-logo-img")).toBeInTheDocument();
  });

  it("super_admin shell also renders exactly ONE brand-logo <img>", () => {
    mount("super_admin");
    const shellLogos = document.querySelectorAll(
      '[data-testid="app-shell"] img[data-testid$="-logo-img"]',
    );
    expect(shellLogos.length).toBe(1);
  });

  it("technician shell also renders exactly ONE brand-logo <img>", () => {
    mount("technician");
    const shellLogos = document.querySelectorAll(
      '[data-testid="app-shell"] img[data-testid$="-logo-img"]',
    );
    expect(shellLogos.length).toBe(1);
  });
});
