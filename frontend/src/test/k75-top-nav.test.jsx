/**
 * Phase K75 · Feb-2026 — Web Nav Revert · Step A contract tests.
 *
 * Locks:
 *   1. ``nav/topNavRegistry.js`` exports the 7-item admin fixed
 *      set in the exact spec order (Dashboard, Schedule, Customers,
 *      Estimates, Invoices, Reports, Settings) with the K75 icons.
 *   2. Technicians get the 6-item tech-flavored set (Schedule, D2D,
 *      Time Clock, Tools, Training, Profile).
 *   3. Customer / customer_portal receive an empty list — that role
 *      mounts its own <UniversalMenu> in <AppLayout>.
 *   4. ``AdminTopBar`` DOM contract: three testid branches remain
 *      (tech-wrap, narrow-wrap, wide-wrap) and each carries the
 *      right-cluster order Sign Out → <UniversalMenu inline>.
 *   5. Source-lint: the retired 6-inline-category-dropdowns layout
 *      is GONE — the top bar no longer emits the K64-era
 *      ``admin-topbar-{group.key}`` testid pattern for six triggers.
 *   6. Every K75 chip resolves through the K64 canonical
 *      ``colors.nav.bgActiveNavy`` for active + hover (no
 *      brandGradient re-introduction on the top nav surfaces).
 */
import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import fs from "node:fs";
import path from "node:path";


let _role = "admin";
vi.mock("@/auth", () => ({
  useAuth: () => ({
    user: { id: "u", role: _role, email: "u@x.com", name: "User" },
    logout: vi.fn(),
    loading: false,
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
  Forbidden: () => <div />,
}));
// Neutralise peripherals so the top bar renders in isolation.
vi.mock("@/components/NotificationBell", () => ({ default: () => null }));
vi.mock("@/components/AIDock/CreditsBudgetChip", () => ({ default: () => null }));
vi.mock("@/layouts/UniversalMenu", () => ({ default: () => <span data-testid="umenu-stub" /> }));
// Give the ADMIN_NAV_V2 mock a single 1-entry group so ``visible.length``
// is > 0 and the "More" trigger renders.
vi.mock("@/nav/adminNav", () => ({
  ADMIN_NAV_V2: [{
    key: "ops",
    label: "Ops",
    icon: () => null,
    entries: [{ to: "/dashboard", feature: "dashboard", label: "Dashboard" }],
  }],
}));


import AdminTopBar from "@/layouts/AdminTopBar";
import { ADMIN_TOP_NAV, TECH_TOP_NAV, topNavForRole, showMoreDropdownForRole } from "@/nav/topNavRegistry";


const TOPBAR_SRC = fs.readFileSync(
  path.resolve(__dirname, "../layouts/AdminTopBar.jsx"),
  "utf8",
);
const REGISTRY_SRC = fs.readFileSync(
  path.resolve(__dirname, "../nav/topNavRegistry.js"),
  "utf8",
);


describe("K75 · topNavRegistry — role-scoped fixed item sets", () => {
  it("ADMIN_TOP_NAV declares the 7 spec items in exact order", () => {
    expect(ADMIN_TOP_NAV.map((i) => i.key)).toEqual([
      "dashboard", "schedule", "customers",
      "estimates", "invoices", "reports", "settings",
    ]);
  });

  it("ADMIN_TOP_NAV routes point at the K75-spec targets", () => {
    const byKey = Object.fromEntries(ADMIN_TOP_NAV.map((i) => [i.key, i.to]));
    expect(byKey.dashboard).toBe("/");
    expect(byKey.schedule).toBe("/schedule");
    expect(byKey.customers).toBe("/customers");
    expect(byKey.estimates).toBe("/estimates");
    expect(byKey.invoices).toBe("/invoices");
    expect(byKey.reports).toBe("/reports");
    expect(byKey.settings).toBe("/settings");
  });

  it("TECH_TOP_NAV declares the 6 tech-flavored items in order", () => {
    expect(TECH_TOP_NAV.map((i) => i.key)).toEqual([
      "schedule", "d2d", "time-clock", "tools", "training", "profile",
    ]);
  });

  it("topNavForRole gates admin / super_admin / manager to the 7-item set", () => {
    for (const r of ["admin", "super_admin", "manager"]) {
      expect(topNavForRole(r)).toBe(ADMIN_TOP_NAV);
    }
  });

  it("topNavForRole returns the tech set for technicians", () => {
    expect(topNavForRole("technician")).toBe(TECH_TOP_NAV);
  });

  it("topNavForRole returns [] for customer / customer_portal / unknown", () => {
    for (const r of ["customer", "customer_portal", "", null, undefined, "guest"]) {
      expect(topNavForRole(r)).toEqual([]);
    }
  });

  it("showMoreDropdownForRole gates the 'More' trigger to admin+/manager", () => {
    expect(showMoreDropdownForRole("admin")).toBe(true);
    expect(showMoreDropdownForRole("super_admin")).toBe(true);
    expect(showMoreDropdownForRole("manager")).toBe(true);
    expect(showMoreDropdownForRole("technician")).toBe(false);
    expect(showMoreDropdownForRole("customer")).toBe(false);
  });

  it("registry source references the K75 icon set on the admin item list", () => {
    // Source-lint: catches an accidental icon swap that would drift
    // the top nav away from the K75 spec.
    for (const iconName of [
      "LayoutDashboard", "CalendarDays", "Users",
      "FileText", "Receipt", "BarChart3", "SettingsIcon",
    ]) {
      expect(REGISTRY_SRC).toContain(iconName);
    }
  });
});


function mount(role, initial = "/") {
  _role = role;
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <AdminTopBar />
    </MemoryRouter>,
  );
}


describe("K75 · AdminTopBar · admin surface", () => {
  it("renders the 7 fixed items with the K75 testid pattern", () => {
    mount("admin");
    for (const key of [
      "dashboard", "schedule", "customers",
      "estimates", "invoices", "reports", "settings",
    ]) {
      expect(screen.getByTestId(`top-nav-${key}`)).toBeTruthy();
    }
  });

  it("renders the 'More' dropdown trigger when categories are visible", () => {
    mount("admin");
    expect(screen.getByTestId("top-nav-more-trigger")).toBeTruthy();
  });

  it("mounts inside admin-topbar-wide-wrap on default (>=768px) viewports", () => {
    mount("admin");
    const wrap = screen.getByTestId("admin-topbar-wide-wrap");
    expect(wrap).toBeTruthy();
    // Every fixed chip is a descendant of the wide-wrap.
    expect(wrap.querySelector('[data-testid="top-nav-dashboard"]')).toBeTruthy();
  });

  it("right cluster preserves order — SignOut LEFT of UniversalMenu", () => {
    mount("admin");
    const signOut = screen.getByTestId("header-signout");
    const umenu = screen.getByTestId("umenu-stub");
    // DOM order (compareDocumentPosition): 4 == FOLLOWING → umenu is after signOut.
    expect(signOut.compareDocumentPosition(umenu) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("Add Customer + Settings sprocket + Sign Out all render in admin wide-wrap", () => {
    mount("admin");
    expect(screen.getByTestId("topbar-add-customer-btn")).toBeTruthy();
    expect(screen.getByTestId("header-settings-sprocket")).toBeTruthy();
    expect(screen.getByTestId("header-signout")).toBeTruthy();
  });
});


describe("K75 · AdminTopBar · technician surface", () => {
  it("renders the 6 tech-flavored items with the K75 testid pattern", () => {
    mount("technician");
    for (const key of [
      "schedule", "d2d", "time-clock",
      "tools", "training", "profile",
    ]) {
      expect(screen.getByTestId(`top-nav-${key}`)).toBeTruthy();
    }
  });

  it("technicians do NOT see the admin-only fixed items", () => {
    mount("technician");
    for (const key of ["dashboard", "customers", "estimates", "invoices", "reports", "settings"]) {
      expect(screen.queryByTestId(`top-nav-${key}`)).toBeNull();
    }
  });

  it("technicians do NOT see the 'More' dropdown trigger", () => {
    mount("technician");
    expect(screen.queryByTestId("top-nav-more-trigger")).toBeNull();
  });

  it("technicians do NOT see the Add Customer button", () => {
    mount("technician");
    expect(screen.queryByTestId("topbar-add-customer-btn")).toBeNull();
  });

  it("technicians STILL see Sign Out + inline UniversalMenu (right cluster)", () => {
    mount("technician");
    expect(screen.getByTestId("header-signout")).toBeTruthy();
    expect(screen.getByTestId("umenu-stub")).toBeTruthy();
  });
});


describe("K75 · AdminTopBar · DOM shell contract", () => {
  it("root container carries data-testid=admin-topbar + colors.nav.bg", () => {
    // Source-lint: sticky navy bar contract preserved.
    expect(TOPBAR_SRC).toMatch(/data-testid="admin-topbar"/);
    expect(TOPBAR_SRC).toMatch(/backgroundColor:\s*colors\.nav\.bg,/);
  });

  it("three DOM branches remain — tech-wrap / narrow-wrap / wide-wrap", () => {
    for (const testid of [
      "admin-topbar-tech-wrap",
      "admin-topbar-narrow-wrap",
      "admin-topbar-wide-wrap",
    ]) {
      expect(TOPBAR_SRC).toContain(`data-testid="${testid}"`);
    }
  });

  it("each branch ends with SignOutButton BEFORE <UniversalMenu variant='inline'/>", () => {
    for (const testid of [
      "admin-topbar-tech-wrap",
      "admin-topbar-narrow-wrap",
      "admin-topbar-wide-wrap",
    ]) {
      const idx = TOPBAR_SRC.indexOf(`data-testid="${testid}"`);
      expect(idx).toBeGreaterThan(-1);
      const slice = TOPBAR_SRC.slice(idx, idx + 3000);
      const signOutIdx = slice.indexOf("<SignOutButton />");
      const umenuIdx = slice.search(/<UniversalMenu\s+variant="inline"\s*\/>/);
      expect(signOutIdx).toBeGreaterThan(-1);
      expect(umenuIdx).toBeGreaterThan(-1);
      expect(signOutIdx).toBeLessThan(umenuIdx);
    }
  });

  it("<UniversalMenu variant='inline'/> is emitted exactly 3 times (one per branch)", () => {
    const matches = TOPBAR_SRC.match(/<UniversalMenu\s+variant="inline"\s*\/>/g) || [];
    expect(matches.length).toBe(3);
  });

  it("does NOT re-import BrandLogo (dedupe fix preserved)", () => {
    expect(TOPBAR_SRC).not.toMatch(/<BrandLogo\b/);
    expect(TOPBAR_SRC).not.toMatch(/import\s+BrandLogo\s+from/);
  });
});


describe("K75 · retired legacy dropdowns — grep-lock", () => {
  it("the pre-K75 six inline CategoryDropdown testids are RETIRED", () => {
    // The pre-K75 top bar rendered one testid per ADMIN_NAV_V2
    // category (``admin-topbar-{group.key}``). K75 folds them into
    // a single "More" dropdown so the retired pattern must be gone.
    expect(TOPBAR_SRC).not.toMatch(/data-testid=\{`admin-topbar-\$\{group\.key\}`\}/);
    expect(TOPBAR_SRC).not.toMatch(/data-testid=\{`admin-topbar-\$\{group\.key\}-menu`\}/);
    // The QuickAccessRow strip (Phase 55) was retired for admin
    // long before K75 — grep-lock the negative.
    expect(TOPBAR_SRC).not.toMatch(/data-testid="admin-topbar-quick-access"/);
    // The K75 "More" trigger is what replaces the six inline
    // triggers — assert its presence in the source.
    expect(TOPBAR_SRC).toContain('data-testid="top-nav-more-trigger"');
  });

  it("K64 active/hover canonical preserved — colors.nav.bgActiveNavy on chip states", () => {
    // The top-nav chips read the K64 canonical for both active +
    // hover states. brandGradient is NOT reintroduced.
    expect(TOPBAR_SRC).toMatch(/colors\.nav\.bgActiveNavy/);
    // The only ``gradients.navyToGreen.css`` remaining is on the
    // AddCustomerButton (out of K75 scope — its green→navy CTA
    // predates K64 and is untouched).
    const addBtnIdx = TOPBAR_SRC.indexOf("topbar-add-customer-btn");
    const gradientIdx = TOPBAR_SRC.indexOf("gradients.navyToGreen.css");
    expect(addBtnIdx).toBeGreaterThan(-1);
    expect(gradientIdx).toBeGreaterThan(-1);
    // The gradient reference sits inside AddCustomerButton (30-line
    // window around the testid).
    expect(Math.abs(gradientIdx - addBtnIdx)).toBeLessThan(600);
  });
});
