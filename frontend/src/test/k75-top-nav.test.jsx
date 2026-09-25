/**
 * Phase K76 · Feb-2026 — Web nav category-restore contract tests.
 *
 * Locks:
 *   1. ``nav/topNavRegistry.js`` still exports the 6-item
 *      ``TECH_TOP_NAV`` in the K75 order (Schedule, D2D, Time
 *      Clock, Tools, Training, Profile). ``ADMIN_TOP_NAV`` is
 *      GONE — admin/manager/super_admin render category dropdowns
 *      via ``useVisibleGroups()`` instead of a fixed strip.
 *   2. ``topNavForRole`` returns [] for admin/manager/super_admin
 *      (they use the category dropdowns) and the tech set for
 *      technicians.
 *   3. Customer / customer_portal receive an empty list — that
 *      role mounts its own <UniversalMenu> in <AppLayout>.
 *   4. ``AdminTopBar`` DOM contract: three testid branches
 *      preserved (tech-wrap, narrow-wrap, wide-wrap) and each
 *      carries the right-cluster order Sign Out →
 *      <UniversalMenu inline>.
 *   5. Admin surface renders one ``admin-topbar-{group.key}``
 *      trigger per visible ``ADMIN_NAV_V2`` category (the
 *      pre-K75 pattern) — NOT the K75 7-fixed-items strip and
 *      NOT a "More" dropdown.
 *   6. K64 canonical preserved — ``colors.nav.bgActiveNavy`` on
 *      both active + hover for chip states AND category
 *      triggers. NO ``brandGradient`` on top-nav surfaces.
 *   7. K52 canonical navy popover marker preserved on category
 *      panels (grep-lock: ``data-k52-navy-popover``).
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
// Feb-2026 · AdminTopBar cleanup — NotificationBell is now mounted
// directly by AdminTopBar (was previously routed through the inline
// UniversalMenu).  Stub it out with a marked <span> so the DOM
// ordering assertions in the ``right cluster preserves order`` +
// technician-cluster tests can locate it.
vi.mock("@/components/NotificationBell", () => ({
  default: () => <span data-testid="notification-bell-inline" />,
}));
vi.mock("@/components/AIDock/CreditsBudgetChip", () => ({ default: () => null }));
// UniversalMenu import was dropped from AdminTopBar by the Feb-2026
// cleanup, but a vi.mock on a path that AdminTopBar never imports
// is harmless — leaving it here so a hypothetical future re-import
// during a refactor doesn't crash the test suite before we notice.
vi.mock("@/layouts/UniversalMenu", () => ({ default: () => <span data-testid="umenu-stub" /> }));
// Give the ADMIN_NAV_V2 mock three groups so category dropdowns
// render for the admin surface. Every entry passes RBAC because
// ``usePermissions.can`` is mocked to always return true.
vi.mock("@/nav/adminNav", () => ({
  ADMIN_NAV_V2: [
    {
      key: "finance",
      label: "Finance",
      icon: () => null,
      entries: [{ to: "/invoices", feature: "invoices", label: "Invoices" }],
    },
    {
      key: "operations",
      label: "Operations",
      icon: () => null,
      entries: [{ to: "/schedule", feature: "jobs", label: "Schedule" }],
    },
    {
      key: "reports",
      label: "Reports",
      icon: () => null,
      entries: [{ to: "/reports", feature: "reports", label: "Reports Hub" }],
    },
  ],
  // Phase Feb-2026 · Multi-industry Phase C — top bar now imports
  // this helper; identity fallback keeps K75 nav tests decoupled
  // from the new industry gate.
  filterNavByIndustries: (entries) => entries,
}));


import AdminTopBar from "@/layouts/AdminTopBar";
import { TECH_TOP_NAV, topNavForRole } from "@/nav/topNavRegistry";


const TOPBAR_SRC = fs.readFileSync(
  path.resolve(__dirname, "../layouts/AdminTopBar.jsx"),
  "utf8",
);
const REGISTRY_SRC = fs.readFileSync(
  path.resolve(__dirname, "../nav/topNavRegistry.js"),
  "utf8",
);


describe("K76 · topNavRegistry — role-scoped fixed item sets", () => {
  it("TECH_TOP_NAV declares the 6 tech-flavored items in order", () => {
    expect(TECH_TOP_NAV.map((i) => i.key)).toEqual([
      "schedule", "d2d", "time-clock", "tools", "training", "profile",
    ]);
  });

  it("topNavForRole returns the tech set for technicians", () => {
    expect(topNavForRole("technician")).toBe(TECH_TOP_NAV);
  });

  it("topNavForRole returns [] for admin / super_admin / manager (they use category dropdowns)", () => {
    for (const r of ["admin", "super_admin", "manager"]) {
      expect(topNavForRole(r)).toEqual([]);
    }
  });

  it("topNavForRole returns [] for customer / customer_portal / unknown", () => {
    for (const r of ["customer", "customer_portal", "", null, undefined, "guest"]) {
      expect(topNavForRole(r)).toEqual([]);
    }
  });

  it("registry export shape — ADMIN_TOP_NAV retained ONLY for K75 Step B pin picker; showMoreDropdownForRole is GONE", () => {
    // K76 walked back the fixed strip for the top nav, but the
    // pin picker (K75 Step B) still surfaces the 7 shortcuts as
    // a "Primary" bundle. Keep the export but the K75 "More"
    // gate must be gone.
    expect(REGISTRY_SRC).toMatch(/export\s+const\s+ADMIN_TOP_NAV\s*=/);
    expect(REGISTRY_SRC).not.toMatch(/\bshowMoreDropdownForRole\b/);
    // Comment guardrail — the export must be documented as
    // legacy-for-pin-picker only, so a future contributor can't
    // wire it back into a top-nav fixed strip by accident.
    expect(REGISTRY_SRC).toMatch(/pin\s+picker/i);
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


describe("K76 · AdminTopBar · admin surface (category dropdowns)", () => {
  it("renders one category dropdown trigger per visible ADMIN_NAV_V2 group", () => {
    mount("admin");
    for (const key of ["finance", "operations", "reports"]) {
      expect(screen.getByTestId(`admin-topbar-${key}`)).toBeTruthy();
    }
  });

  it("does NOT render the K75 7-fixed-items strip on the admin surface", () => {
    mount("admin");
    for (const key of [
      "dashboard", "schedule", "customers",
      "estimates", "invoices", "reports", "settings",
    ]) {
      // K75 ``top-nav-{key}`` chips are retired for admin.
      // (``schedule`` / ``reports`` etc. still exist as ``admin-topbar-{group.key}``
      // category triggers — different testid pattern.)
      expect(screen.queryByTestId(`top-nav-${key}`)).toBeNull();
    }
  });

  it("does NOT render the K75 'More' dropdown trigger", () => {
    mount("admin");
    expect(screen.queryByTestId("top-nav-more-trigger")).toBeNull();
  });

  it("mounts inside admin-topbar-wide-wrap on default (>=768px) viewports", () => {
    mount("admin");
    const wrap = screen.getByTestId("admin-topbar-wide-wrap");
    expect(wrap).toBeTruthy();
    // Every category trigger is a descendant of the wide-wrap.
    expect(wrap.querySelector('[data-testid="admin-topbar-finance"]')).toBeTruthy();
  });

  it("right cluster preserves order — Settings LEFT of NotificationBell LEFT of SignOut (wide branch)", () => {
    mount("admin");
    const wide = screen.getByTestId("admin-topbar-wide-wrap");
    const settings = wide.querySelector('[data-testid="header-settings-sprocket"]');
    const bell = wide.querySelector('[data-testid="notification-bell-inline"]');
    const signOut = wide.querySelector('[data-testid="header-signout"]');
    expect(settings).toBeTruthy();
    expect(bell).toBeTruthy();
    expect(signOut).toBeTruthy();
    expect(settings.compareDocumentPosition(bell) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(bell.compareDocumentPosition(signOut) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("Add Customer + Settings sprocket + Sign Out all render in admin wide-wrap", () => {
    mount("admin");
    const wide = screen.getByTestId("admin-topbar-wide-wrap");
    expect(wide.querySelector('[data-testid="topbar-add-customer-btn"]')).toBeTruthy();
    expect(wide.querySelector('[data-testid="header-settings-sprocket"]')).toBeTruthy();
    expect(wide.querySelector('[data-testid="header-signout"]')).toBeTruthy();
  });
});


describe("K76 · AdminTopBar · technician surface (fixed strip)", () => {
  it("renders the 6 tech-flavored items with the K75 testid pattern", () => {
    mount("technician");
    for (const key of [
      "schedule", "d2d", "time-clock",
      "tools", "training", "profile",
    ]) {
      expect(screen.getByTestId(`top-nav-${key}`)).toBeTruthy();
    }
  });

  it("technicians do NOT see any admin category dropdown triggers", () => {
    mount("technician");
    for (const key of ["finance", "operations", "reports"]) {
      expect(screen.queryByTestId(`admin-topbar-${key}`)).toBeNull();
    }
  });

  it("technicians do NOT see the retired 'More' dropdown trigger", () => {
    mount("technician");
    expect(screen.queryByTestId("top-nav-more-trigger")).toBeNull();
  });

  it("technicians do NOT see the Add Customer button", () => {
    mount("technician");
    expect(screen.queryByTestId("topbar-add-customer-btn")).toBeNull();
  });

  it("technicians STILL see Sign Out + standalone NotificationBell (right cluster in wide-wrap)", () => {
    mount("technician");
    const wide = screen.getByTestId("admin-topbar-wide-wrap");
    // Feb-2026 · AdminTopBar cleanup — technicians hit the
    // ``admin-topbar-tech-wrap`` fallback branch (no admin nav /
    // no tech-fixed strip), so the wide-wrap they see for tech
    // role in isNarrow=false jsdom still ends with the inline
    // NotificationBell + Sign-out per the new cluster contract.
    expect(wide.querySelector('[data-testid="header-signout"]')).toBeTruthy();
    expect(wide.querySelector('[data-testid="notification-bell-inline"]')).toBeTruthy();
  });
});


describe("K76 · AdminTopBar · DOM shell contract", () => {
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

  it("each branch ends with SignOutButton AFTER <NotificationBell variant='inline'/>", () => {
    for (const testid of [
      "admin-topbar-tech-wrap",
      "admin-topbar-narrow-wrap",
      "admin-topbar-wide-wrap",
    ]) {
      const idx = TOPBAR_SRC.indexOf(`data-testid="${testid}"`);
      expect(idx).toBeGreaterThan(-1);
      const slice = TOPBAR_SRC.slice(idx, idx + 3000);
      const bellIdx = slice.search(/<NotificationBell\s+variant="inline"\s*\/>/);
      const signOutIdx = slice.indexOf("<SignOutButton />");
      expect(bellIdx).toBeGreaterThan(-1);
      expect(signOutIdx).toBeGreaterThan(-1);
      expect(bellIdx).toBeLessThan(signOutIdx);
    }
  });

  it("<NotificationBell variant='inline'/> is emitted exactly 3 times (one per branch)", () => {
    // Feb-2026 · AdminTopBar cleanup — the inline UniversalMenu
    // that used to end every branch was replaced by a standalone
    // NotificationBell.  Count-lock stays at 3 (one per wrap).
    const matches = TOPBAR_SRC.match(/<NotificationBell\s+variant="inline"\s*\/>/g) || [];
    expect(matches.length).toBe(3);
  });

  it("does NOT re-import BrandLogo (dedupe fix preserved)", () => {
    expect(TOPBAR_SRC).not.toMatch(/<BrandLogo\b/);
    expect(TOPBAR_SRC).not.toMatch(/import\s+BrandLogo\s+from/);
  });
});


describe("K76.1 · mobile-web breakpoint collapse (CSS-driven, always in DOM)", () => {
  it("both narrow-wrap and wide-wrap render simultaneously; CSS decides visibility", () => {
    mount("admin");
    // The desktop wide-wrap AND the mobile narrow-wrap are both in
    // the DOM at all times — Tailwind's ``md:`` breakpoint (768px)
    // toggles ``display`` on each. This is the K76.1 regression
    // fix: the JS ``resize``-listener approach was unreliable in
    // some mobile browsers.
    expect(screen.getByTestId("admin-topbar-wide-wrap")).toBeTruthy();
    expect(screen.getByTestId("admin-topbar-narrow-wrap")).toBeTruthy();
  });

  it("narrow-wrap carries ``md:hidden`` (visible <768px only)", () => {
    mount("admin");
    const narrow = screen.getByTestId("admin-topbar-narrow-wrap");
    expect(narrow.className).toMatch(/\bmd:hidden\b/);
  });

  it("wide-wrap carries ``hidden md:flex`` (hidden <768px, flex >=768px)", () => {
    mount("admin");
    const wide = screen.getByTestId("admin-topbar-wide-wrap");
    expect(wide.className).toMatch(/\bhidden\b/);
    expect(wide.className).toMatch(/\bmd:flex\b/);
  });

  it("mobile menu trigger renders inside the narrow-wrap on the admin surface", () => {
    mount("admin");
    const narrow = screen.getByTestId("admin-topbar-narrow-wrap");
    const trigger = narrow.querySelector('[data-testid="admin-topbar-mobile-trigger"]');
    expect(trigger).toBeTruthy();
  });

  it("mobile menu trigger renders inside the narrow-wrap on the tech surface too", () => {
    mount("technician");
    const narrow = screen.getByTestId("admin-topbar-narrow-wrap");
    const trigger = narrow.querySelector('[data-testid="admin-topbar-mobile-trigger"]');
    expect(trigger).toBeTruthy();
  });

  it("data-narrow attribute reflects matchMedia state (jsdom default: false)", () => {
    mount("admin");
    // jsdom's matchMedia always returns matches=false unless mocked,
    // so data-narrow="0" on default render.
    const bar = screen.getByTestId("admin-topbar");
    expect(bar.getAttribute("data-narrow")).toBe("0");
  });

  it("data-narrow flips to '1' when matchMedia reports a narrow viewport", () => {
    const orig = window.matchMedia;
    window.matchMedia = vi.fn().mockImplementation((q) => ({
      matches: q.includes("max-width: 767"),
      media: q,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }));
    try {
      mount("admin");
      const bar = screen.getByTestId("admin-topbar");
      expect(bar.getAttribute("data-narrow")).toBe("1");
    } finally {
      window.matchMedia = orig;
    }
  });
});


describe("K76 · category dropdowns — restoration grep-lock", () => {
  it("renders the ``admin-topbar-${group.key}`` trigger pattern (pre-K75)", () => {
    // K76 restores the pre-K75 category-trigger testid shape.
    expect(TOPBAR_SRC).toMatch(/data-testid=\{\s*`admin-topbar-\$\{group\.key\}`\s*\}/);
    expect(TOPBAR_SRC).toMatch(/data-testid=\{\s*`admin-topbar-\$\{group\.key\}-menu`\s*\}/);
  });

  it("the K75 'More' dropdown trigger is GONE from the source", () => {
    expect(TOPBAR_SRC).not.toContain('data-testid="top-nav-more-trigger"');
    expect(TOPBAR_SRC).not.toMatch(/\bMoreDropdown\b/);
  });

  it("the K75 7-fixed-items ADMIN_TOP_NAV wiring is GONE from the top bar source", () => {
    // The K76 top bar renders ``CategoryDropdown`` per visible
    // group instead of iterating over ``fixedItems`` for admin.
    // ``fixedItems.map(...TopNavChip)`` still exists — but only
    // for the technician branch; admin never reaches it.
    expect(TOPBAR_SRC).not.toMatch(/\bADMIN_TOP_NAV\b/);
    expect(TOPBAR_SRC).not.toMatch(/\bshowMoreDropdownForRole\b/);
  });

  it("K52 canonical navy popover marker preserved on category panels", () => {
    // Grep-lock: the pre-K75 popover-styling contract still
    // annotates the K76 category-dropdown content nodes.
    expect(TOPBAR_SRC).toContain('data-k52-navy-popover="true"');
  });

  it("K64 active/hover canonical preserved — colors.nav.bgActiveNavy on chip AND category states", () => {
    // The top-nav chips + category triggers read the K64 canonical
    // for both active + hover states. brandGradient is NOT
    // reintroduced on top-nav surfaces.
    expect(TOPBAR_SRC).toMatch(/colors\.nav\.bgActiveNavy/);
    // The only ``gradients.navyToGreen.css`` remaining is on the
    // AddCustomerButton (out of K76 scope — its green→navy CTA
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
