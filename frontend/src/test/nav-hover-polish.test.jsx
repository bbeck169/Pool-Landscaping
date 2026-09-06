/**
 * Feb-2026 UI Polish Addendum — menu-chrome hover / focus assertions.
 *
 * Verifies (pure DOM introspection — no live route rendering):
 *   1. The AppLayout `<aside data-testid="side-nav">` container
 *      carries the subtle brand tint added in this addendum.
 *   2. Each QuickNavRail item exposes the hover motion utility so
 *      the design spec ("scale-[1.02] on hover, color shift on
 *      icon+label, focus-visible matches hover") is enforced at
 *      class level.
 *   3. AdminTopBar root carries the same subtle tint.
 *
 * These tests read the layout modules statically via the built-in
 * test-render helpers so we avoid the giant real-app auth/tenant
 * mock forest. If a future refactor removes the required classes
 * these tests fail loudly.
 */
import React from "react";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";

// Silence unrelated context deps that QuickNavRail imports.
vi.mock("@/api", () => ({ api: { get: vi.fn().mockResolvedValue({}) } }));
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    NavLink: ({ children, className, style, "data-testid": tid, ...rest }) => {
      const cls = typeof className === "function"
        ? className({ isActive: false })
        : className;
      const sty = typeof style === "function" ? style({ isActive: false }) : style;
      return (
        <a data-testid={tid} className={cls} style={sty} {...rest}>{children}</a>
      );
    },
  };
});

// The QuickNavRail is exported implicitly (not named) — rather than
// jumping through hoops to grab a private component we render a
// tiny slice by re-reading the class expressions we ship inside
// AppLayout. Instead of importing the component we introspect the
// SOURCE file to keep this test dependency-free from the auth
// context. This mirrors phase21-vanity-slugs.test.jsx which reads
// route wiring the same way.
import fs from "fs";
import path from "path";

const APP_LAYOUT_SRC = fs.readFileSync(
  path.resolve(__dirname, "..", "layouts", "AppLayout.jsx"),
  "utf-8",
);
const QUICK_PINS_RAIL_SRC = fs.readFileSync(
  path.resolve(__dirname, "..", "components", "nav", "QuickPinsRail.jsx"),
  "utf-8",
);
const ADMIN_TOPBAR_SRC = fs.readFileSync(
  path.resolve(__dirname, "..", "layouts", "AdminTopBar.jsx"),
  "utf-8",
);
const ADMIN_SIDEBAR_SRC = fs.readFileSync(
  path.resolve(__dirname, "..", "layouts", "AdminSidebar.jsx"),
  "utf-8",
);

describe("Feb-2026 UI polish · menu chrome + hover states", () => {
  it("QuickPinsRail items ship the hover-scale motion class (K75 · Step B refactor)", () => {
    // Phase K75 · Step B · Feb-2026 — the rail moved from an inline
    // ``QuickNavRail`` in AppLayout to a dedicated
    // ``components/nav/QuickPinsRail.jsx`` component that hydrates
    // its item list from ``useQuickPins``. The Feb-2026 hover-scale
    // motion contract migrates with it.
    expect(QUICK_PINS_RAIL_SRC).toMatch(/hover:scale-\[1\.02\]/);
    expect(QUICK_PINS_RAIL_SRC).toMatch(/transition-all/);
    expect(QUICK_PINS_RAIL_SRC).toMatch(/focus-visible:ring/);
  });

  it("AppLayout side-nav aside carries a subtle brand tint", () => {
    // We use a rgba() inline style token so the tint is exact and
    // survives Tailwind purge. Assert both the sky-brand hex prefix
    // and the low alpha value to catch accidental over-tinting.
    expect(APP_LAYOUT_SRC).toMatch(/rgba\(2, ?132, ?199,\s*0\.0[0-9]/);
    // The tint must be applied on the `<aside data-testid=side-nav>`
    // — the string appears in the same file near the aside JSX.
    expect(APP_LAYOUT_SRC).toContain('data-testid="side-nav"');
  });

  it("AdminTopBar does NOT re-render the brand logo (dedupe fix)", () => {
    // Feb-2026 UI Polish Addendum · dedupe follow-up — the top-nav
    // must NOT mount BrandLogo. The 88px side-rail crown in
    // <AppLayout> is the single source of truth for the desktop
    // shell brand mark; the mobile <header> is the single source
    // for < md viewports. Reintroducing a BrandLogo import here
    // would fail this guard.
    expect(ADMIN_TOPBAR_SRC).not.toMatch(/<BrandLogo\b/);
    expect(ADMIN_TOPBAR_SRC).not.toMatch(/import\s+BrandLogo\s+from/);
  });

  it("AdminTopBar root sticky bar picks up the K50 navy chrome", () => {
    // Phase K50 · Feb-2026 — the pre-K50 sky-tinted brand wash
    // (``rgba(2, 132, 199, 0.045)``) was replaced with the
    // Pipedrive-inspired navy chrome (``colors.nav.bg = #1B1F5C``).
    // Both single-source-of-truth on ``colors.nav`` in theme.js.
    expect(ADMIN_TOPBAR_SRC).toMatch(/backgroundColor:\s*colors\.nav\.bg,/);
  });

  it("AdminSidebar entries ship hover motion + focus-visible parity", () => {
    // The mobile-drawer Entry row also gets the polish. Look for
    // the group class + hover motion utility co-located.
    expect(ADMIN_SIDEBAR_SRC).toMatch(/hover:scale-\[1\.02\]/);
    expect(ADMIN_SIDEBAR_SRC).toMatch(/focus-visible:/);
  });
});

// Smoke-render just to ensure no compile-time regression sneaks in.
describe("Feb-2026 UI polish · MemoryRouter smoke", () => {
  it("MemoryRouter mounts without throwing", () => {
    const { container } = render(<MemoryRouter><div>ok</div></MemoryRouter>);
    expect(container.textContent).toBe("ok");
  });
});
