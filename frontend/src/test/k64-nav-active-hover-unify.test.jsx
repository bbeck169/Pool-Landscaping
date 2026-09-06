/**
 * Phase K64 · Feb-2026 — main nav active/hover unification.
 *
 * Locks the invariants for the two main-nav surfaces:
 *   • Left admin sidebar rail (``AppLayout.jsx``)
 *   • Top-nav category dropdowns (``AdminTopBar.jsx`` :: CategoryDropdown)
 *
 * Contract:
 *   1. ``colors.nav.bgActiveNavy`` exists in ``theme.js`` as
 *      ``#303AA0`` (lighter-navy solid, ~+15% L over ``nav.bg``).
 *   2. Both surfaces bind BOTH hover AND active states to
 *      ``bgActiveNavy`` — the K52 mint gradient is retired on the
 *      main nav. Non-nav gradient consumers (BusinessOS sub-nav,
 *      badges, filter pills) are intentionally untouched — see
 *      the second describe() block for the regression guard.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

import { colors } from "../theme.js";

const read = (rel) =>
  fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");

const THEME       = read("src/theme.js");
const APP_LAYOUT  = read("src/layouts/AppLayout.jsx");
const TOP_BAR     = read("src/layouts/AdminTopBar.jsx");


describe("K64 · theme token — colors.nav.bgActiveNavy", () => {
  it("exports a lighter-navy solid at #303AA0", () => {
    expect(colors.nav).toBeDefined();
    expect(colors.nav.bgActiveNavy).toBe("#303AA0");
  });

  it("preserves the K50 nav.bg + nav.bgHover tokens (no regression)", () => {
    expect(colors.nav.bg).toBe("#1B1F5C");
    expect(colors.nav.bgHover).toBe("#2A2F7A");
    expect(colors.nav.fg).toBe("#FFFFFF");
  });

  it("theme.js keeps the K52 gradient block intact (non-nav consumers still resolve it, K67 · navy end)", () => {
    // K64 does NOT retire the gradient token — only stops the two
    // main-nav surfaces from consuming it. Existing badge / sub-nav
    // callers still resolve through colors.gradient.*
    // K67 · Feb-2026 — swapped the sky-300 stop for menu navy.
    expect(THEME).toMatch(/gradient:\s*\{[\s\S]{0,300}from:\s*"#22C55E"/);
    expect(colors.gradient.css)
      .toBe("linear-gradient(90deg, #22C55E 0%, #1B1F5C 100%)");
  });
});


describe("K64 · AppLayout QuickNavRail source-body contract", () => {
  it("active state binds background to nav.bgActiveNavy (no more K52 gradient)", () => {
    expect(APP_LAYOUT).toMatch(
      /background:\s*isActive\s*\?\s*colors\.nav\.bgActiveNavy\s*:\s*"transparent"/,
    );
    // Text stays white (idle or active).
    expect(APP_LAYOUT).toMatch(/color:\s*colors\.nav\.fg,/);
    // Regression guard — the K52 gradient no longer paints the rail
    // active state.
    expect(APP_LAYOUT).not.toMatch(
      /background:\s*isActive\s*\?\s*colors\.gradient\.css/,
    );
  });

  it("hover state resolves to the same nav.bgActiveNavy solid (hover == active)", () => {
    // The onMouseEnter handler force-paints bgActiveNavy so hover
    // ≡ active. onMouseLeave restores transparent for idle rows +
    // keeps bgActiveNavy for active rows.
    expect(APP_LAYOUT).toMatch(
      /onMouseEnter=\{\(e\) => \{\s*e\.currentTarget\.style\.background = colors\.nav\.bgActiveNavy;/,
    );
    // Regression guard — the K52 white-on-hover overlay is no
    // longer applied to the RAIL NavLink (removed from the
    // conditional className branch). Other unrelated hover:bg-
    // white/10 usages in AppLayout (e.g. mobile bottom bar) are
    // untouched.
    const railBlock = APP_LAYOUT.split("data-testid={`rail-nav-")[0].slice(-2000);
    expect(railBlock).not.toMatch(/hover:bg-white\/10/);
  });
});


describe("K64 · AdminTopBar top-nav chip source-body contract (K75-refactored)", () => {
  // Phase K75 · Feb-2026 — CategoryDropdown was retired; the
  // K64-canonical chip is now ``TopNavChip`` (NavLink-based).
  const cat = TOP_BAR.split("function TopNavChip(")[1]
    .split("\nfunction ")[0];

  it("active state binds background to nav.bgActiveNavy", () => {
    // K75: NavLink signature uses ``isActive``.
    expect(cat).toMatch(
      /background:\s*isActive\s*\?\s*colors\.nav\.bgActiveNavy\s*:\s*"transparent"/,
    );
    // No lingering K52 gradient on the chip.
    expect(cat).not.toMatch(/colors\.gradient\.css/);
    expect(cat).not.toMatch(/colors\.gradient\.cssHover/);
    expect(cat).not.toMatch(/colors\.gradient\.textShadow/);
  });

  it("hover paints the same nav.bgActiveNavy solid (hover == active)", () => {
    expect(cat).toMatch(
      /onMouseEnter=\{\(e\) => \{\s*e\.currentTarget\.style\.background = colors\.nav\.bgActiveNavy;/,
    );
    // Leave handler restores either bgActiveNavy (still active) or
    // transparent (idle). Uses ``aria-current`` since NavLink drives
    // active state through that attribute; equivalent to the pre-K75
    // ``active`` local variable.
    expect(cat).toMatch(
      /onMouseLeave=\{\(e\) => \{[\s\S]{0,200}e\.currentTarget\.style\.background =[\s\S]{0,200}colors\.nav\.bgActiveNavy[\s\S]{0,80}:\s*"transparent";/,
    );
  });
});


describe("K64 · non-nav gradient consumers left untouched", () => {
  // Guards the user's constraint — K64 scope is main nav only.
  // A future scatter-refactor must not accidentally retire the
  // gradient on badges / filter pills.
  const OK_TO_KEEP_GRADIENT = [
    "src/pages/invoices/InvoicesList.jsx",
    "src/pages/os/BusinessOS.jsx",
    "src/pages/schedule/CalendarSchedule.jsx",
    "src/pages/customers/CustomersList.jsx",
  ];

  for (const rel of OK_TO_KEEP_GRADIENT) {
    it(`${rel} still references colors.gradient.css`, () => {
      const src = read(rel);
      expect(src).toMatch(/colors\.gradient\.css/);
    });
  }

  it("no main-nav file leaks colors.gradient.* on the active/hover state", () => {
    expect(APP_LAYOUT).not.toMatch(/colors\.gradient\.css/);
    expect(APP_LAYOUT).not.toMatch(/colors\.gradient\.cssHover/);
    // Phase K75 · Feb-2026 — CategoryDropdown retired; assert the
    // K75-refactored TopNavChip block instead.
    const chipBlock = TOP_BAR.split("function TopNavChip(")[1]
      .split("\nfunction ")[0];
    expect(chipBlock).not.toMatch(/colors\.gradient/);
  });
});
