/**
 * Phase K52 · Feb-2026 — Theming expansion suite.
 *
 * Four slices:
 *   • Slice A — Filter row FULL navy (Schedule filter strip).
 *   • Slice B — Dropdown popover MENU navy (CategoryDropdown +
 *     shadcn ``<Select>`` popover panel primitive).
 *   • Slice C — Gradient primary CTA button variant.
 *   • Slice D — Active nav item = signature gradient (sidebar rail,
 *     top-bar CategoryDropdown trigger, BusinessOS sub-nav).
 *
 * Contract checks live at the source-body level (mirrors K50 /
 * K48 / K41) so the suite runs without mounting the full app
 * graph — the ``theme.js`` token block is the single source of
 * truth and every consumer resolves through it.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";
import { colors } from "@/theme";

const read = (rel) => fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");

const THEME       = read("src/theme.js");
const APP_LAYOUT  = read("src/layouts/AppLayout.jsx");
const TOP_BAR     = read("src/layouts/AdminTopBar.jsx");
const BUSINESS_OS = read("src/pages/os/BusinessOS.jsx");
const BUTTON      = read("src/components/ui/button.jsx");
const SELECT      = read("src/components/ui/select.jsx");
const CAL_SCHED   = read("src/pages/schedule/CalendarSchedule.jsx");
// K52.1 · Filter row navy sweep — swept pages.
const CUSTOMERS   = read("src/pages/customers/CustomersList.jsx");
const QUOTES      = read("src/pages/quotes/QuotesList.jsx");
const INVOICES    = read("src/pages/invoices/InvoicesList.jsx");
const LEADS       = read("src/pages/leads/LeadsDashboardPage.jsx");
const TIMERS      = read("src/pages/timers/JobTimersPage.jsx");


/* ══════════════════════════════════════════════════════════════════ */
/* Token contract                                                     */
/* ══════════════════════════════════════════════════════════════════ */

describe("K52 · Theme tokens", () => {
  it("exports the ``colors.gradient`` block with the locked values (K67 · navy end)", () => {
    expect(colors.gradient).toBeDefined();
    expect(colors.gradient.from).toBe("#22C55E");   // emerald-500 (unchanged)
    expect(colors.gradient.to).toBe("#1B1F5C");     // K67 · menu navy (was #7DD3FC sky-300)
    expect(colors.gradient.css)
      .toBe("linear-gradient(90deg, #22C55E 0%, #1B1F5C 100%)");
    expect(colors.gradient.cssHover)
      .toBe("linear-gradient(90deg, #34D673 0%, #2A2F7A 100%)");
    expect(colors.gradient.fg).toBe("#FFFFFF");
    expect(colors.gradient.fgHover).toBe("#FFFFFF");
    expect(colors.gradient.textShadow).toBe("0 1px 2px rgba(0, 0, 0, 0.25)");
  });

  it("``theme.js`` keeps the K50 nav block intact + adds the K52 gradient block inline (K67 · navy end)", () => {
    // Guards against a scatter-refactor moving gradient tokens
    // out of ``theme.js``.  Single source of truth is the K52 rule.
    expect(THEME).toMatch(/gradient:\s*\{[\s\S]{0,900}from:\s*"#22C55E"[\s\S]{0,600}to:\s*"#1B1F5C"/);
    expect(THEME).toMatch(/css:\s*"linear-gradient\(90deg,\s*#22C55E\s*0%,\s*#1B1F5C\s*100%\)"/);
    expect(THEME).toMatch(/textShadow:\s*"0 1px 2px rgba\(0,\s*0,\s*0,\s*0\.25\)"/);
    // K50 tokens preserved.
    expect(THEME).toMatch(/nav:\s*\{[\s\S]{0,400}bg:\s*"#1B1F5C"/);
  });

  it("``colors.nav.fgMuted`` bumped from K50's 0.65 → K52's 0.72 for the filter-strip placeholder legibility", () => {
    // K52 Slice A · Feb-2026 — the filter-strip placeholder text
    // sits directly on ``colors.nav.bg``; the K50 0.65 alpha was
    // borderline under WCAG AA for placeholder copy.  0.72 keeps
    // the visual hierarchy but lifts the ratio.
    expect(colors.nav.fgMuted).toBe("rgba(255, 255, 255, 0.72)");
  });
});


/* ══════════════════════════════════════════════════════════════════ */
/* Slice A — Filter row navy                                          */
/* ══════════════════════════════════════════════════════════════════ */

describe("K52 · Slice A — Filter row navy (Schedule)", () => {
  it("``calendar-filters`` strip renders on ``colors.nav.bg`` (was ``colors.surface``)", () => {
    const idx = CAL_SCHED.indexOf('data-testid="calendar-filters"');
    expect(idx).toBeGreaterThan(-1);
    const block = CAL_SCHED.slice(Math.max(0, idx - 600), idx);
    expect(block).toMatch(/background:\s*colors\.nav\.bg,/);
    // The K52 marker attribute is present so the tester can locate
    // every navy strip via a single selector.
    const forward = CAL_SCHED.slice(idx, idx + 200);
    expect(forward).toMatch(/data-k52-navy-strip="true"/);
    // Regression guard — the pre-K52 ``colors.surface`` bg MUST
    // NOT reappear on this strip.
    expect(block).not.toMatch(/background:\s*colors\.surface,\s*border:\s*`1px solid \$\{colors\.border\}`\s*\}\s*}\s*data-testid="calendar-filters"/);
  });

  it("Search input, all four ``<select>`` triggers, and the Clear button render white on navy", () => {
    // Search wrapper — white/10 tinted card on navy.
    const searchBlock = CAL_SCHED.split('data-testid="calendar-search"')[0].slice(-800);
    expect(searchBlock).toMatch(/background:\s*"rgba\(255,255,255,0\.10\)"/);
    expect(searchBlock).toMatch(/color:\s*colors\.nav\.fgMuted/);
    // Each of the four selects on the strip uses ``colors.nav.bg``
    // + ``colors.nav.fg``.  We assert on the strip source block
    // (idx range from filters open through crew chips row).
    const stripStart = CAL_SCHED.indexOf('data-testid="calendar-filters"');
    const stripEnd = CAL_SCHED.indexOf('data-testid="calendar-presets"');
    expect(stripStart).toBeGreaterThan(-1);
    expect(stripEnd).toBeGreaterThan(stripStart);
    const strip = CAL_SCHED.slice(stripStart, stripEnd);
    ["calendar-filter-tech", "calendar-filter-crew",
     "calendar-filter-service", "calendar-filter-status"].forEach((tid) => {
      const trigIdx = strip.indexOf(`data-testid="${tid}"`);
      expect(trigIdx, `trigger ${tid} present`).toBeGreaterThan(-1);
      // The style prop follows the testid on <select> tags — scan
      // forward ~600 chars to cover the multi-line style object.
      const trigBlock = strip.slice(trigIdx, Math.min(strip.length, trigIdx + 600));
      expect(trigBlock, `trigger ${tid} bg`).toMatch(/background:\s*colors\.nav\.bg/);
      expect(trigBlock, `trigger ${tid} fg`).toMatch(/color:\s*(crewId\s*\?\s*colors\.nav\.fgMuted\s*:\s*)?colors\.nav\.fg/);
    });
    // Clear button — white outline pill on navy.  Style prop
    // follows the testid on this <button> too, so scan forward.
    const clearIdx = CAL_SCHED.indexOf('data-testid="calendar-filter-clear"');
    expect(clearIdx).toBeGreaterThan(-1);
    const clearBlock = CAL_SCHED.slice(clearIdx, clearIdx + 400);
    expect(clearBlock).toMatch(/color:\s*colors\.nav\.fg,/);
    expect(clearBlock).toMatch(/background:\s*"rgba\(255,255,255,0\.10\)"/);
  });

  it("``calendar-presets`` row is also a navy K52 strip with gradient-active chips", () => {
    const idx = CAL_SCHED.indexOf('data-testid="calendar-presets"');
    expect(idx).toBeGreaterThan(-1);
    const block = CAL_SCHED.slice(Math.max(0, idx - 500), idx);
    expect(block).toMatch(/background:\s*colors\.nav\.bg,/);
    const forward = CAL_SCHED.slice(idx, idx + 3000);
    // Active preset chip paints the K52 gradient; idle stays
    // transparent with a white outline.
    expect(forward).toMatch(/background:\s*active\s*\?\s*colors\.gradient\.css\s*:\s*"transparent"/);
    expect(forward).toMatch(/border:\s*`1px solid \$\{active\s*\?\s*"transparent"\s*:\s*colors\.nav\.fgMuted\}`/);
    // Regression guard — the pre-K52 ``colors.brand`` solid fill
    // for the active preset MUST NOT reappear.
    expect(forward).not.toMatch(/background:\s*active\s*\?\s*colors\.brand\s*:\s*colors\.surface/);
  });
});


/* ══════════════════════════════════════════════════════════════════ */
/* Slice B — Popover navy (CategoryDropdown + shadcn Select)          */
/* ══════════════════════════════════════════════════════════════════ */

describe("K52 · Slice B — Popover panel navy", () => {
  it("MoreDropdown popover renders on ``colors.nav.bg`` with white items + navy-hover (K75-refactored)", () => {
    // Phase K75 · Feb-2026 — CategoryDropdown was retired. The six
    // inline category dropdowns fold into a single "More" dropdown
    // whose popover carries the K52 Slice B navy chrome verbatim.
    const dropdown = TOP_BAR.split("function MoreDropdown(")[1]
      .split("\nfunction ")[0];
    // Panel bg.
    expect(dropdown).toMatch(/backgroundColor:\s*colors\.nav\.bg/);
    // Item hover uses ``bgHover`` = ``#2A2F7A``.
    expect(dropdown).toMatch(/menuitem\]:hover\]:bg-\[#2A2F7A\]/);
    // Marker for testers (K52 grep-lock).
    expect(dropdown).toMatch(/data-k52-navy-popover="true"/);
    // Active row uses the K50 white-pill / navy-text pattern
    // (the K52 gradient is reserved for the nav SURFACES per Slice D).
    const entryBody = TOP_BAR.split("function EntryItem(")[1]
      .split("\nfunction ")[0];
    expect(entryBody).toMatch(/backgroundColor:\s*colors\.nav\.bgActive/);
    expect(entryBody).toMatch(/color:\s*colors\.nav\.fgActive/);
  });

  it("shadcn ``<SelectContent>`` primitive paints navy for every ``<Select>`` popover app-wide", () => {
    // Panel = navy, text white, border white/10.
    expect(SELECT).toMatch(/bg-\[#1B1F5C\]/);
    expect(SELECT).toMatch(/text-white/);
    expect(SELECT).toMatch(/border-white\/10/);
    // Item hover / focus = ``#2A2F7A``.
    expect(SELECT).toMatch(/focus:bg-\[#2A2F7A\]/);
    expect(SELECT).toMatch(/hover:bg-\[#2A2F7A\]/);
    // Selected item = white pill with navy text.
    expect(SELECT).toMatch(/data-\[state=checked\]:bg-white/);
    expect(SELECT).toMatch(/data-\[state=checked\]:text-\[#1B1F5C\]/);
    // Section labels = white 72%.
    expect(SELECT).toMatch(/text-white\/72/);
    // Marker attribute for testers.
    expect(SELECT).toMatch(/data-k52-navy-popover="true"/);
    // Regression guard — pre-K52 ``bg-popover`` / ``bg-muted``
    // Tailwind CSS-var tokens on these primitives MUST NOT
    // resurface (they resolved to a light chrome we no longer want).
    expect(SELECT).not.toMatch(/bg-popover/);
    expect(SELECT).not.toMatch(/bg-muted/);
    expect(SELECT).not.toMatch(/focus:bg-accent/);
  });
});


/* ══════════════════════════════════════════════════════════════════ */
/* Slice C — Gradient primary button                                  */
/* ══════════════════════════════════════════════════════════════════ */

describe("K52 · Slice C — Gradient primary Button", () => {
  it("shadcn Button ``default`` variant paints the K52 signature gradient (K67 · navy end)", () => {
    // Both stops present verbatim in the variant class list.
    expect(BUTTON).toMatch(/default:[^,]*bg-\[linear-gradient\(90deg,_#22C55E_0%,_#1B1F5C_100%\)\]/);
    // Hover uses the +8% brightness gradient (navy hover = colors.nav.bgHover).
    expect(BUTTON).toMatch(/hover:bg-\[linear-gradient\(90deg,_#34D673_0%,_#2A2F7A_100%\)\]/);
    // White text + subtle text-shadow for legibility over the
    // perceptual mid-point (green → navy luminance dip).
    expect(BUTTON).toMatch(/text-white/);
    expect(BUTTON).toMatch(/text-shadow:0_1px_2px_rgba\(0,0,0,0\.25\)/);
    // Focus ring uses the emerald end of the gradient as accent.
    expect(BUTTON).toMatch(/focus-visible:ring-\[#22C55E\]/);
    // Active/press = brightness(0.95) for tactile feedback.
    expect(BUTTON).toMatch(/active:brightness-95/);
    // Regression guard — the pre-K52 ``bg-primary`` flat fill MUST
    // NOT resurface on the ``default`` variant.
    const defBlock = BUTTON.split("default:")[1].split("destructive:")[0];
    expect(defBlock).not.toMatch(/bg-primary\b/);
    // K67 grep-lock — the deprecated sky-300 stop must not
    // resurface in the ACTIVE variant class list (comments
    // explaining the K67 swap may still name #7DD3FC / #93DDFD
    // for context; scope the assertion to the class list itself).
    expect(defBlock).not.toMatch(/bg-\[[^\]]*#7DD3FC/);
    expect(defBlock).not.toMatch(/bg-\[[^\]]*#93DDFD/);
  });

  it("``destructive`` variant is NOT gradient-ified (danger stays flat red)", () => {
    // Explicit spec — destructive keeps a flat red fill so the
    // danger affordance stays semantically distinct.
    //
    // Feb-2026 update · K54 — the destructive variant migrated
    // from the semantic ``bg-destructive`` Tailwind class to the
    // solid #DC2626 hex per ``colors.destructive.bg``.  The
    // "no-gradient" intent is unchanged; the hex spec is locked
    // by ``test/k54-destructive-buttons.test.js``.
    const destBlock = BUTTON.split("destructive:")[1].split("outline:")[0];
    expect(destBlock).toMatch(/bg-\[#DC2626\]/);
    expect(destBlock).not.toMatch(/linear-gradient/);
    expect(destBlock).not.toMatch(/#22C55E/);
    expect(destBlock).not.toMatch(/#7DD3FC/);
  });

  it("``ghost`` / ``outline`` / ``link`` / ``secondary`` variants stay flat (tertiary affordances)", () => {
    // K52 spec explicitly excludes tertiary variants from the
    // gradient promotion — they would fight the primary's visual
    // weight if they shared it.
    ["ghost:", "outline:", "link:", "secondary:"].forEach((label) => {
      const idx = BUTTON.indexOf(label);
      expect(idx, `variant ${label} present`).toBeGreaterThan(-1);
      // Slice out ~200 chars for the variant's class list.
      const varBlock = BUTTON.slice(idx, idx + 200);
      expect(varBlock).not.toMatch(/linear-gradient/);
      expect(varBlock).not.toMatch(/#22C55E/);
      expect(varBlock).not.toMatch(/#7DD3FC/);
    });
  });

  it("disabled state = 55% opacity of the gradient (not a separate flat gray)", () => {
    // K52 spec — reduced-opacity gradient keeps the affordance
    // semantically consistent even on the disabled path.
    expect(BUTTON).toMatch(/disabled:opacity-55/);
    // Regression guard — pre-K52 ``disabled:opacity-50`` MUST NOT
    // resurface (0.55 is the K52 locked value).
    expect(BUTTON).not.toMatch(/disabled:opacity-50/);
  });
});


/* ══════════════════════════════════════════════════════════════════ */
/* Slice D — Active nav = gradient  (K64: main nav uses solid navy)  */
/* ══════════════════════════════════════════════════════════════════ */

describe("K52 · Slice D — Active nav item styling (K64 supersedes on main-nav surfaces)", () => {
  it("QuickNavRail active rail item paints ``colors.nav.bgActiveNavy`` (K64 replaced K52 gradient)", () => {
    // Phase K64 · Feb-2026 — main-nav rail now uses a lighter-navy
    // solid for BOTH hover and active. K52 gradient retained on
    // BusinessOS sub-nav + non-nav consumers (see below).
    expect(APP_LAYOUT).toMatch(/background:\s*isActive\s*\?\s*colors\.nav\.bgActiveNavy\s*:\s*"transparent"/);
    expect(APP_LAYOUT).toMatch(/color:\s*colors\.nav\.fg,/);
    expect(APP_LAYOUT).not.toMatch(/background:\s*isActive\s*\?\s*colors\.gradient\.css/);
  });

  it("AdminTopBar TopNavChip active state paints ``colors.nav.bgActiveNavy`` (K64 replaced K52 gradient; K75 refactored CategoryDropdown → TopNavChip)", () => {
    // Phase K75 · Feb-2026 — CategoryDropdown was retired; the
    // K64-canonical primary chip is now ``TopNavChip`` (NavLink).
    const cat = TOP_BAR.split("function TopNavChip(")[1]
      .split("\nfunction ")[0];
    // K75: NavLink signature uses ``isActive``.
    expect(cat).toMatch(/background:\s*isActive\s*\?\s*colors\.nav\.bgActiveNavy\s*:\s*"transparent"/);
    // Idle text stays white.
    expect(cat).toMatch(/color:\s*colors\.nav\.fg,/);
    // Regression guard — pre-K52 ``bgActive`` white pill on the
    // chip MUST NOT resurface.
    expect(cat).not.toMatch(/backgroundColor:\s*isActive\s*\?\s*colors\.nav\.bgActive[^N]/);
    // Regression guard — K52 gradient no longer paints the chip.
    expect(cat).not.toMatch(/colors\.gradient\.css/);
  });

  it("BusinessOS sub-nav active tab paints the gradient (was white pill)", () => {
    expect(BUSINESS_OS).toMatch(/background:\s*isActive\s*\?\s*colors\.gradient\.css\s*:\s*"transparent"/);
    expect(BUSINESS_OS).toMatch(/color:\s*isActive\s*\?\s*colors\.gradient\.fg\s*:\s*colors\.nav\.fg/);
    expect(BUSINESS_OS).toMatch(/textShadow:\s*isActive\s*\?\s*colors\.gradient\.textShadow/);
  });

  it("K51 Branding preview page NOT touched — light tile stays #FFFFFF, navy tile stays #1B1F5C", () => {
    // Regression guard — Slice D explicitly excludes the K51
    // preview surface.  Painting gradients on the preview tiles
    // would defeat the whole point of showing both chromes
    // side-by-side to admins.
    const PREVIEW = read("src/pages/settings/BrandLogoSettings.jsx");
    const navyIdx = PREVIEW.indexOf('data-testid="logo-preview-navy"');
    const lightIdx = PREVIEW.indexOf('data-testid="logo-preview-light"');
    expect(navyIdx).toBeGreaterThan(-1);
    expect(lightIdx).toBeGreaterThan(-1);
    const navyBlock = PREVIEW.slice(Math.max(0, navyIdx - 400), navyIdx);
    const lightBlock = PREVIEW.slice(Math.max(0, lightIdx - 400), lightIdx);
    expect(navyBlock).toMatch(/#1B1F5C/);
    expect(lightBlock).toMatch(/#FFFFFF/);
    // NEITHER tile carries the K52 gradient.
    expect(navyBlock).not.toMatch(/linear-gradient/);
    expect(lightBlock).not.toMatch(/linear-gradient/);
    expect(navyBlock).not.toMatch(/colors\.gradient/);
    expect(lightBlock).not.toMatch(/colors\.gradient/);
  });
});


/* ══════════════════════════════════════════════════════════════════ */
/* K52.1 — Filter row navy sweep across list-view pages               */
/* ══════════════════════════════════════════════════════════════════ */

/**
 * Contract per swept page: the filter strip container is marked
 * ``data-k52-navy-strip="true"`` and its inline ``style`` prop
 * carries ``backgroundColor: colors.nav.bg`` (or ``background:
 * colors.nav.bg``).  Two assertions per page — that's the
 * paint-only pass contract; deeper input/select recolouring is
 * covered by the source-level ``colors.nav.fg`` /
 * ``colors.nav.border`` refs already present in each file's diff.
 */
function assertNavyStripPresent(sourceText, pageLabel) {
  const idx = sourceText.indexOf('data-k52-navy-strip="true"');
  expect(idx, `${pageLabel} — filter strip marker present`).toBeGreaterThan(-1);
  // Scan ~800 chars preceding the marker (React attributes on JSX
  // wrap onto multiple lines; the ``style`` prop typically opens
  // ~4–8 lines above the marker attribute).
  const block = sourceText.slice(Math.max(0, idx - 800), idx + 80);
  expect(block, `${pageLabel} — filter strip paints navy`).toMatch(
    /(?:background|backgroundColor):\s*colors\.nav\.bg/
  );
}

describe("K52.1 · Filter row navy sweep", () => {
  it("CustomersList filter strip is navy K52", () => {
    assertNavyStripPresent(CUSTOMERS, "CustomersList");
    // Scope chips (All / Unscheduled / Waitlist) are filter-state
    // chips → active paints the K52 gradient (matches K52 Slice A
    // preset-chip pattern).  Regression guard against the pre-K52
    // ``colors.brandTertiary`` teal-mint active fill.
    expect(CUSTOMERS).toMatch(/scope\s*===\s*s\.k\s*\?\s*colors\.gradient\.css\s*:\s*"transparent"/);
    expect(CUSTOMERS).not.toMatch(/scope\s*===\s*s\.k\s*\?\s*colors\.brandTertiary/);
  });

  it("QuotesList filter strip is navy K52", () => {
    assertNavyStripPresent(QUOTES, "QuotesList");
    // Search input + status select both resolve to
    // ``colors.nav.*`` tokens.
    expect(QUOTES).toMatch(/data-testid="quotes-search"/);
    expect(QUOTES).toMatch(/data-testid="quotes-filter-status"/);
    // Regression guard — pre-K52 ``colors.surfaceSecondary`` /
    // ``colors.onSurfaceSecondary`` on the strip's controls MUST
    // be gone.
    const stripStart = QUOTES.indexOf('data-testid="quotes-filters"');
    const stripEnd = QUOTES.indexOf("</div>", stripStart);
    const strip = QUOTES.slice(stripStart, stripEnd);
    expect(strip).not.toMatch(/colors\.surfaceSecondary/);
    expect(strip).not.toMatch(/colors\.onSurfaceSecondary/);
  });

  it("InvoicesList filter strip is navy K52", () => {
    assertNavyStripPresent(INVOICES, "InvoicesList");
    // ``Has late fee`` toggle is a filter-state chip: active paints
    // the K52 gradient.
    expect(INVOICES).toMatch(/hasLateFee\s*\?\s*colors\.gradient\.css\s*:\s*"transparent"/);
    // Selected-category chips also render on the gradient.  Use a
    // simpler forward-scan pattern — the chip's testid uses JSX
    // string interpolation which makes an inline regex tricky.
    const catChipIdx = INVOICES.indexOf("inv-category-chip-");
    expect(catChipIdx).toBeGreaterThan(-1);
    const catChipBlock = INVOICES.slice(Math.max(0, catChipIdx - 800), catChipIdx);
    expect(catChipBlock).toMatch(/background:\s*colors\.gradient\.css/);
    // Regression guard — pre-K52 red-fee-tint (``#FEE2E2``) and
    // blue-category-tint (``#DBEAFE``) fills on chips MUST be gone.
    const stripStart = INVOICES.indexOf('data-testid="invoices-filters"');
    const stripEnd = INVOICES.indexOf('data-testid="inv-search"');
    // The whole filter strip ends after the category chip block —
    // scan forward past that too.
    const bigStrip = INVOICES.slice(stripStart, stripStart + 5000);
    expect(stripStart).toBeGreaterThan(-1);
    expect(stripEnd).toBeGreaterThan(stripStart);
    expect(bigStrip).not.toMatch(/backgroundColor:\s*"#FEE2E2"/);
    expect(bigStrip).not.toMatch(/backgroundColor:\s*"#DBEAFE"/);
  });

  it("LeadsDashboardPage filter strip is navy K52 (was a bare flex row)", () => {
    assertNavyStripPresent(LEADS, "LeadsDashboardPage");
    // Pre-K52.1 rendering was a raw ``<div className="flex …">``
    // with white ``background: "#fff"`` inputs.  Regression guard.
    const stripStart = LEADS.indexOf('data-testid="leads-filters"');
    const stripEnd = LEADS.indexOf("</div>", stripStart + 100);
    const strip = LEADS.slice(stripStart, Math.max(stripStart + 4000, stripEnd));
    expect(stripStart).toBeGreaterThan(-1);
    expect(strip).not.toMatch(/background:\s*"#fff"/);
    // Fields still render — search + source + status selects.
    expect(strip).toMatch(/data-testid="lead-search-input"/);
    expect(strip).toMatch(/data-testid="lead-filter-source-select"/);
    expect(strip).toMatch(/data-testid="lead-filter-status-select"/);
  });

  it("JobTimersPage filter strip is navy K52", () => {
    assertNavyStripPresent(TIMERS, "JobTimersPage");
    // Two ``<input type="date">`` fields carry ``colorScheme: "dark"``
    // so the native calendar icon inverts to white on the navy strip.
    const stripStart = TIMERS.indexOf('data-testid="timers-filters"');
    const stripEnd = TIMERS.indexOf('Export CSV', stripStart);
    const strip = TIMERS.slice(stripStart, stripEnd + 50);
    const darkSchemeMatches = strip.match(/colorScheme:\s*"dark"/g) || [];
    expect(darkSchemeMatches.length, "both date inputs opt into dark colorScheme").toBeGreaterThanOrEqual(2);
    // Text inputs paint the tinted-white card treatment (matches
    // CalendarSchedule search input).
    expect(strip).toMatch(/background:\s*"rgba\(255,255,255,0\.10\)"/);
  });

  it("Ships the K52.1 marker on every swept page — one selector for the tester", () => {
    // Sanity — one selector (``[data-k52-navy-strip="true"]``)
    // reaches all 6 filter strips (CalendarSchedule + 5 K52.1
    // pages).  Any future filter-strip refactor that drops the
    // marker fails this test.
    const swept = [CAL_SCHED, CUSTOMERS, QUOTES, INVOICES, LEADS, TIMERS];
    swept.forEach((src, i) => {
      expect(src.match(/data-k52-navy-strip="true"/g)?.length || 0, `page ${i} carries at least one K52.1 marker`).toBeGreaterThanOrEqual(1);
    });
    // CalendarSchedule ships TWO strips (filter toolbar + preset
    // row) — the marker attribute appears twice there.
    expect(CAL_SCHED.match(/data-k52-navy-strip="true"/g).length).toBe(2);
  });
});
