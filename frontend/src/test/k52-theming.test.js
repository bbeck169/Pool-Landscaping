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


/* ══════════════════════════════════════════════════════════════════ */
/* Token contract                                                     */
/* ══════════════════════════════════════════════════════════════════ */

describe("K52 · Theme tokens", () => {
  it("exports the ``colors.gradient`` block with the locked values", () => {
    expect(colors.gradient).toBeDefined();
    expect(colors.gradient.from).toBe("#22C55E");   // emerald-500
    expect(colors.gradient.to).toBe("#7DD3FC");     // sky-300
    expect(colors.gradient.css)
      .toBe("linear-gradient(90deg, #22C55E 0%, #7DD3FC 100%)");
    expect(colors.gradient.cssHover)
      .toBe("linear-gradient(90deg, #34D673 0%, #93DDFD 100%)");
    expect(colors.gradient.fg).toBe("#FFFFFF");
    expect(colors.gradient.fgHover).toBe("#FFFFFF");
    expect(colors.gradient.textShadow).toBe("0 1px 2px rgba(0, 0, 0, 0.25)");
  });

  it("``theme.js`` keeps the K50 nav block intact + adds the K52 gradient block inline", () => {
    // Guards against a scatter-refactor moving gradient tokens
    // out of ``theme.js``.  Single source of truth is the K52 rule.
    expect(THEME).toMatch(/gradient:\s*\{[\s\S]{0,600}from:\s*"#22C55E"[\s\S]{0,400}to:\s*"#7DD3FC"/);
    expect(THEME).toMatch(/css:\s*"linear-gradient\(90deg,\s*#22C55E\s*0%,\s*#7DD3FC\s*100%\)"/);
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
  it("CategoryDropdown popover renders on ``colors.nav.bg`` with white items + navy-hover", () => {
    const dropdown = TOP_BAR.split("function CategoryDropdown(")[1]
      .split("\nfunction ")[0];
    // Panel bg.
    expect(dropdown).toMatch(/backgroundColor:\s*colors\.nav\.bg/);
    // Item hover uses ``bgHover`` = ``#2A2F7A``.
    expect(dropdown).toMatch(/menuitem\]:hover\]:bg-\[#2A2F7A\]/);
    // Marker for testers.
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
  it("shadcn Button ``default`` variant paints the K52 signature gradient", () => {
    // Both stops present verbatim in the variant class list.
    expect(BUTTON).toMatch(/default:[^,]*bg-\[linear-gradient\(90deg,_#22C55E_0%,_#7DD3FC_100%\)\]/);
    // Hover uses the +8% brightness gradient.
    expect(BUTTON).toMatch(/hover:bg-\[linear-gradient\(90deg,_#34D673_0%,_#93DDFD_100%\)\]/);
    // White text + subtle text-shadow for legibility on the sky end.
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
  });

  it("``destructive`` variant is NOT gradient-ified (danger stays flat red)", () => {
    // Explicit spec — destructive keeps its ``bg-destructive`` fill
    // so the danger affordance stays semantically distinct.
    const destBlock = BUTTON.split("destructive:")[1].split("outline:")[0];
    expect(destBlock).toMatch(/bg-destructive/);
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
/* Slice D — Active nav = gradient                                    */
/* ══════════════════════════════════════════════════════════════════ */

describe("K52 · Slice D — Active nav item = gradient", () => {
  it("QuickNavRail active rail item paints ``colors.gradient.css`` (K50 white pill retired)", () => {
    expect(APP_LAYOUT).toMatch(/background:\s*isActive\s*\?\s*colors\.gradient\.css\s*:\s*"transparent"/);
    expect(APP_LAYOUT).toMatch(/color:\s*isActive\s*\?\s*colors\.gradient\.fg\s*:\s*colors\.nav\.fg/);
    expect(APP_LAYOUT).toMatch(/textShadow:\s*isActive\s*\?\s*colors\.gradient\.textShadow/);
  });

  it("AdminTopBar CategoryDropdown trigger active state paints the gradient (was white pill)", () => {
    const cat = TOP_BAR.split("function CategoryDropdown(")[1]
      .split("\nfunction ")[0];
    expect(cat).toMatch(/background:\s*active\s*\?\s*colors\.gradient\.css\s*:\s*undefined/);
    expect(cat).toMatch(/textShadow:\s*active\s*\?\s*colors\.gradient\.textShadow/);
    // Idle text stays white — gradient supplies both bg AND fg on
    // active, so the K50 ``fgActive`` swap is retired on the trigger.
    expect(cat).toMatch(/color:\s*colors\.nav\.fg,/);
    // Regression guard — pre-K52 ``bgActive`` white pill on the
    // trigger MUST NOT resurface.
    expect(cat).not.toMatch(/backgroundColor:\s*active\s*\?\s*colors\.nav\.bgActive/);
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
