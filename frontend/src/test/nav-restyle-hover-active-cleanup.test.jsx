/**
 * NAV-restyle · Feb-2026 — app-wide hover glow + isActive-driven active state.
 *
 * Source-lint suite (pattern-mirror of ``nav-hover-polish.test.jsx``).
 * JSDOM cannot resolve stylesheet-declared ``:hover`` pseudos AND Tailwind
 * ``hover:*`` classes are static class mounts (not runtime pseudos), so
 * class-presence + inline-style-string assertions on the source code are
 * the most stable technique. Zero DOM ``mouseEnter`` — those are checked
 * by the human tester in preview.
 *
 * Contract locked:
 *   1. ``colors.nav.hoverGlow`` token exists in ``theme.js`` with the
 *      exact ``"0 0 10px #3B82F6"`` value (ruling R14 · B).
 *   2. Each of the 5 nav files imports ``colors`` from ``@/theme`` (or
 *      the relative equivalent) and references ``colors.nav.hoverGlow``.
 *   3. Each NavLink-driven file references ``colors.nav.bgActiveNavy``
 *      in an isActive-style block (ruling R9 · B).
 *   4. All 36 ``data-testid`` values from Phase 0 recon R6 are still
 *      present in their respective source files (preservation contract).
 *   5. Negative-guard: none of the 5 files reintroduce click-to-persist
 *      patterns (activeTab / selectedNav / clickedTab / persistedActive).
 *      Ruling R17 belt-and-suspenders.
 *   6. Preserved-contract cross-checks: hover:scale-[1.02] (K75) and
 *      focus-visible:ring-* (a11y) still present in the files that
 *      carried them pre-NAV-restyle.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";


const _SRC_ROOT = path.resolve(__dirname, "..");
const _read = (rel) =>
  fs.readFileSync(path.resolve(_SRC_ROOT, rel), "utf-8");

const THEME_SRC          = _read("theme.js");
const APP_LAYOUT_SRC     = _read("layouts/AppLayout.jsx");
const ADMIN_TOPBAR_SRC   = _read("layouts/AdminTopBar.jsx");
const ADMIN_SIDEBAR_SRC  = _read("layouts/AdminSidebar.jsx");
const QUICK_PINS_RAIL_SRC = _read("components/nav/QuickPinsRail.jsx");
const UNIVERSAL_MENU_SRC = _read("layouts/UniversalMenu.jsx");


// ═══════════════════════════════════════════════════════════════
// 1) theme.js — token contract
// ═══════════════════════════════════════════════════════════════
describe("NAV-restyle · theme.js hoverGlow token", () => {
  it("defines colors.nav.hoverGlow with the exact NAV-restyle value", () => {
    // Ruling R14 · Option B — single source of truth string.
    expect(THEME_SRC).toMatch(
      /hoverGlow:\s*["']0 0 10px #3B82F6["']/,
    );
  });

  it("colors.nav.bg + bgActiveNavy + inputBorder unchanged", () => {
    // Regression guard on the tokens NAV-restyle references.
    expect(THEME_SRC).toMatch(/bg:\s*["']#1B1F5C["']/);
    expect(THEME_SRC).toMatch(/bgActiveNavy:\s*["']#303AA0["']/);
    expect(THEME_SRC).toMatch(/inputBorder:\s*["']#3B82F6["']/);
  });
});


// ═══════════════════════════════════════════════════════════════
// 2) Each of the 5 nav files references colors.nav.hoverGlow
// ═══════════════════════════════════════════════════════════════
const _NAV_FILES = [
  ["AppLayout.jsx",       APP_LAYOUT_SRC],
  ["AdminTopBar.jsx",     ADMIN_TOPBAR_SRC],
  ["AdminSidebar.jsx",    ADMIN_SIDEBAR_SRC],
  ["QuickPinsRail.jsx",   QUICK_PINS_RAIL_SRC],
  ["UniversalMenu.jsx",   UNIVERSAL_MENU_SRC],
];

describe("NAV-restyle · glow-token adoption across the 5 nav files", () => {
  for (const [name, src] of _NAV_FILES) {
    it(`${name} imports colors from @/theme and uses colors.nav.hoverGlow`, () => {
      // Import assertion — the file must pull ``colors`` from
      // ``@/theme`` (or the relative equivalent). Both patterns are
      // valid in this codebase.
      const _hasColorsImport =
        /import\s*\{[^}]*\bcolors\b[^}]*\}\s*from\s*["'](?:@\/theme|\.\.?\/theme|\.\.?\/\.\.?\/theme)["']/
          .test(src);
      expect(_hasColorsImport).toBe(true);
      // Glow reference — every file uses the token in at least one
      // hover handler. AdminTopBar uses the literal string inside a
      // Tailwind arbitrary shadow class for the shadcn dropdown
      // menuitems (Tailwind can't resolve a JS token inside a class
      // string), so ALSO accept the literal ``"0 0 10px #3B82F6"``.
      const _hasGlow =
        /colors\.nav\.hoverGlow/.test(src)
        || /shadow-\[0_0_10px_#3B82F6\]/.test(src);
      expect(_hasGlow).toBe(true);
    });
  }
});


// ═══════════════════════════════════════════════════════════════
// 3) NavLink-driven files reference colors.nav.bgActiveNavy for active
// ═══════════════════════════════════════════════════════════════
describe("NAV-restyle · active-state token (K64 canonical)", () => {
  const _ACTIVE_FILES = [
    ["AdminTopBar.jsx",    ADMIN_TOPBAR_SRC],
    ["QuickPinsRail.jsx",  QUICK_PINS_RAIL_SRC],
  ];

  for (const [name, src] of _ACTIVE_FILES) {
    it(`${name} renders active pill with colors.nav.bgActiveNavy`, () => {
      // Ruling R9 · Option B — active = ``bgActiveNavy`` (#303AA0),
      // NOT ``colors.nav.bg`` (#1B1F5C, which would collide with
      // parent chrome).
      expect(src).toMatch(/colors\.nav\.bgActiveNavy/);
    });
  }
});


// ═══════════════════════════════════════════════════════════════
// 4) 36 data-testid preservation contract (Phase 0 · R6)
// ═══════════════════════════════════════════════════════════════
const _APP_LAYOUT_TESTIDS = [
  "app-boot-loading", "app-logo-mobile-white", "app-main", "app-shell",
  "bottom-nav", "impersonation-banner", "mobile-nav-backdrop",
  "mobile-nav-close", "mobile-nav-drawer", "mobile-nav-open",
  "mobile-nav-scroll", "portal-sticky-header", "preview-banner",
  "preview-banner-exit", "revert-impersonation",
  "shell-logout-button-mobile", "side-nav", "side-nav-logo-slot",
  "sidebar-logout-button",
];
const _ADMIN_TOPBAR_TESTIDS = [
  "admin-topbar", "admin-topbar-add-job", "admin-topbar-mobile-menu",
  "admin-topbar-mobile-trigger", "admin-topbar-narrow-wrap",
  "admin-topbar-tech-wrap", "admin-topbar-wide-wrap",
  "header-settings-sprocket", "header-signout", "topbar-add-customer-btn",
];
const _ADMIN_SIDEBAR_TESTIDS = [
  "nav-dashboard-link", "nav-help-btn", "nav-palette", "nav-palette-input",
  "nav-palette-trigger", "nav-pinned", "nav-pinned-sortable",
  "nav-shortcut-help",
];
const _QUICK_PINS_RAIL_TESTIDS = [
  "quick-nav-rail", "quick-nav-rail-header", "rail-pin-add-btn",
];
const _UNIVERSAL_MENU_TESTIDS = [
  "portal-signout", "universal-menu-floating-wrap", "web-menu-chip-all",
  "web-menu-empty", "web-menu-search", "web-menu-search-clear",
  "web-menu-sheet", "web-menu-trigger",
];

describe("NAV-restyle · data-testid preservation", () => {
  const _PAIRS = [
    ["AppLayout.jsx",     APP_LAYOUT_SRC,     _APP_LAYOUT_TESTIDS],
    ["AdminTopBar.jsx",   ADMIN_TOPBAR_SRC,   _ADMIN_TOPBAR_TESTIDS],
    ["AdminSidebar.jsx",  ADMIN_SIDEBAR_SRC,  _ADMIN_SIDEBAR_TESTIDS],
    ["QuickPinsRail.jsx", QUICK_PINS_RAIL_SRC, _QUICK_PINS_RAIL_TESTIDS],
    ["UniversalMenu.jsx", UNIVERSAL_MENU_SRC, _UNIVERSAL_MENU_TESTIDS],
  ];

  for (const [file, src, ids] of _PAIRS) {
    for (const tid of ids) {
      it(`${file} preserves data-testid="${tid}"`, () => {
        // Support both ``data-testid="foo"`` and template-literal
        // ``data-testid={\`prefix-${var}\`}`` — for the latter the
        // static prefix (e.g. ``btm-nav-``) is what's guaranteed.
        // We accept either match.
        const _rx = new RegExp(
          `data-testid=(?:["']${tid}["']|\\{\`[^\`]*${tid}[^\`]*\`\\})`,
        );
        expect(src).toMatch(_rx);
      });
    }
  }
});


// ═══════════════════════════════════════════════════════════════
// 5) Negative guard — click-to-persist patterns MUST NOT appear
// ═══════════════════════════════════════════════════════════════
describe("NAV-restyle · click-to-persist negative-guard (cleanup lock)", () => {
  // Ruling R17 belt-and-suspenders — the "cleanup" clause in the
  // user's brief was a no-op because grep confirmed zero click-to-
  // persist patterns exist. This test lock-boxes that state: if any
  // of the 4 legacy patterns re-enter one of the 5 files, the guard
  // trips.
  const _LEGACY_PATTERNS = [
    /\bactiveTab\b/,
    /\bselectedNav\b/,
    /\bclickedTab\b/,
    /\bpersistedActive\b/,
  ];

  for (const [name, src] of _NAV_FILES) {
    for (const rx of _LEGACY_PATTERNS) {
      it(`${name} does NOT reintroduce ${rx.source}`, () => {
        expect(src).not.toMatch(rx);
      });
    }
  }
});


// ═══════════════════════════════════════════════════════════════
// 6) Preserved-contract cross-checks (K75 hover-scale + a11y)
// ═══════════════════════════════════════════════════════════════
describe("NAV-restyle · preserved K75 + a11y contracts", () => {
  it("QuickPinsRail still ships hover:scale-[1.02] (K75)", () => {
    expect(QUICK_PINS_RAIL_SRC).toMatch(/hover:scale-\[1\.02\]/);
  });

  it("AdminSidebar still ships hover:scale-[1.02] (K75)", () => {
    expect(ADMIN_SIDEBAR_SRC).toMatch(/hover:scale-\[1\.02\]/);
  });

  it("AdminTopBar still ships hover:scale-[1.02] (K75)", () => {
    expect(ADMIN_TOPBAR_SRC).toMatch(/hover:scale-\[1\.02\]/);
  });

  it("QuickPinsRail preserves focus-visible ring", () => {
    expect(QUICK_PINS_RAIL_SRC).toMatch(/focus-visible:ring-/);
  });

  it("AdminSidebar preserves focus-visible ring", () => {
    expect(ADMIN_SIDEBAR_SRC).toMatch(/focus-visible:ring-/);
  });

  it("AdminTopBar preserves focus-visible ring", () => {
    expect(ADMIN_TOPBAR_SRC).toMatch(/focus-visible:ring-/);
  });

  it("AppLayout mobile drawer-open button preserves focus-visible ring", () => {
    // Line ~557 mobile-nav-open + line ~508 sidebar-logout.
    expect(APP_LAYOUT_SRC).toMatch(/focus-visible:ring-white\/40/);
  });

  it("AdminTopBar root still uses colors.nav.bg (K50 navy chrome)", () => {
    // Preserves the K50 backdrop contract the ``nav-hover-polish``
    // regression test also guards.
    expect(ADMIN_TOPBAR_SRC).toMatch(/backgroundColor:\s*colors\.nav\.bg,/);
  });
});


// ═══════════════════════════════════════════════════════════════
// 7) Active-item glow-suppression contract (R11 · A)
// ═══════════════════════════════════════════════════════════════
describe("NAV-restyle · glow suppression on active items", () => {
  it("AdminTopBar TopNavChip gates boxShadow on aria-current='page'", () => {
    // The suppression check reads ``aria-current === 'page'`` before
    // setting boxShadow. This lock-boxes ruling R11.
    expect(ADMIN_TOPBAR_SRC).toMatch(
      /aria-current["']\)\s*!==\s*["']page["'][\s\S]{0,120}?boxShadow\s*=\s*colors\.nav\.hoverGlow/,
    );
  });

  it("QuickPinsRail gates boxShadow on aria-current='page'", () => {
    expect(QUICK_PINS_RAIL_SRC).toMatch(
      /aria-current["']\)\s*!==\s*["']page["'][\s\S]{0,120}?boxShadow\s*=\s*colors\.nav\.hoverGlow/,
    );
  });

  it("AdminSidebar Entry gates boxShadow on aria-current='page'", () => {
    expect(ADMIN_SIDEBAR_SRC).toMatch(
      /aria-current["']\)\s*!==\s*["']page["'][\s\S]{0,200}?boxShadow\s*=\s*colors\.nav\.hoverGlow/,
    );
  });

  it("AdminTopBar CategoryDropdown gates boxShadow on data-state='open'", () => {
    // Dropdown-open state is the analogue of ``aria-current`` for the
    // top-bar category trigger. Ruling R11 · A covers both surfaces.
    expect(ADMIN_TOPBAR_SRC).toMatch(
      /data-state["']\)\s*!==\s*["']open["'][\s\S]{0,120}?boxShadow\s*=\s*colors\.nav\.hoverGlow/,
    );
  });
});
