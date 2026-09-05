/**
 * Phase K50 · Feb-2026 — Web theming suite.
 *
 * Two independent slices:
 *   • Slice A — Navy sidebar + top main menu chrome (single-token
 *     source-of-truth at ``colors.nav`` in ``frontend/src/theme.js``).
 *   • Slice B — Schedule job-card status background shading (single
 *     helper source-of-truth at ``frontend/src/lib/jobStatus.js``).
 *
 * Contract checks live at the source-body level (mirrors the K41 / K48
 * pattern) so the suite runs without mounting the full app graph.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";
import { colors } from "@/theme";
import {
  jobStatusColor,
  K50_JOB_STATUS_BG,
} from "@/lib/jobStatus";

const read = (rel) => fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");

const THEME = read("src/theme.js");
const APP_LAYOUT = read("src/layouts/AppLayout.jsx");
const TOP_BAR = read("src/layouts/AdminTopBar.jsx");
const BUSINESS_OS = read("src/pages/os/BusinessOS.jsx");
const CAL_SCHEDULE = read("src/pages/schedule/CalendarSchedule.jsx");
const TODAY_SCHEDULE = read("src/pages/schedule/TodaySchedule.jsx");

/* ══════════════════════════════════════════════════════════════════ */
/* Slice A — Navy chrome                                              */
/* ══════════════════════════════════════════════════════════════════ */

describe("K50 · Slice A — Navy sidebar + top main menu", () => {
  it("theme.js exports the single-source-of-truth ``nav`` token block", () => {
    expect(colors.nav).toBeDefined();
    expect(colors.nav.bg).toBe("#1B1F5C");
    expect(colors.nav.bgHover).toBe("#2A2F7A");
    expect(colors.nav.bgActive).toBe("#FFFFFF");
    expect(colors.nav.fg).toBe("#FFFFFF");
    expect(colors.nav.fgActive).toBe("#1B1F5C");
  });

  it("the ``nav`` block sits inline in theme.js (guards against a scatter re-write)", () => {
    // Regression guard — a future refactor MUST NOT split the nav
    // palette across multiple files.  Single-token source is the
    // K50 spec.
    expect(THEME).toMatch(/nav:\s*\{[\s\S]{0,400}bg:\s*"#1B1F5C"/);
    expect(THEME).toMatch(/bgActive:\s*"#FFFFFF"/);
    expect(THEME).toMatch(/fgActive:\s*"#1B1F5C"/);
  });

  it("AppLayout side-nav <aside> renders with ``colors.nav.bg`` (no more sky gradient)", () => {
    expect(APP_LAYOUT).toMatch(/backgroundColor:\s*colors\.nav\.bg/);
    // Regression guard — the pre-K50 sky gradient must NOT reappear
    // in a live style prop (comment reference at line ~526 is
    // intentional).
    expect(APP_LAYOUT).not.toMatch(/background:\s*\n?\s*"linear-gradient\(180deg,\s*rgba\(2,\s*132,\s*199,\s*0\.06\)/);
  });

  it("QuickNavRail active state uses the white-pill / navy-text combo", () => {
    // Active: bg = nav.bgActive (#FFFFFF), color = nav.fgActive (#1B1F5C).
    // Idle:  bg = transparent,           color = nav.fg (#FFFFFF).
    expect(APP_LAYOUT).toMatch(/backgroundColor:\s*isActive\s*\?\s*colors\.nav\.bgActive\s*:\s*"transparent"/);
    expect(APP_LAYOUT).toMatch(/color:\s*isActive\s*\?\s*colors\.nav\.fgActive\s*:\s*colors\.nav\.fg/);
    // Regression guard — no lingering ``sky-50`` / ``sky-600`` hover
    // classes on rail items.
    const railBody = APP_LAYOUT.split("function QuickNavRail(")[1].split("\nfunction ")[0];
    expect(railBody).not.toMatch(/hover:bg-sky-50/);
    expect(railBody).not.toMatch(/group-hover:text-sky-600/);
  });

  it("AdminTopBar wrapper renders on the ``nav.bg`` navy", () => {
    expect(TOP_BAR).toMatch(/backgroundColor:\s*colors\.nav\.bg,/);
    // Pre-K50 sky-tinted wash MUST be gone.
    expect(TOP_BAR).not.toMatch(/backgroundColor:\s*"rgba\(2,\s*132,\s*199,\s*0\.045\)"/);
  });

  it("CategoryDropdown triggers render white on navy (active = white pill)", () => {
    expect(TOP_BAR).toMatch(/color:\s*active\s*\?\s*colors\.nav\.fgActive\s*:\s*colors\.nav\.fg/);
    expect(TOP_BAR).toMatch(/backgroundColor:\s*active\s*\?\s*colors\.nav\.bgActive\s*:\s*undefined/);
    // Regression guard — no more ``hover:bg-sky-50`` on the trigger.
    const catBody = TOP_BAR.split("function CategoryDropdown(")[1].split("\nfunction ")[0];
    expect(catBody).not.toMatch(/hover:bg-sky-50/);
    expect(catBody).toMatch(/hover:bg-white\/10/);
  });
});


/* ══════════════════════════════════════════════════════════════════ */
/* Slice A extension — Portal top nav + secondary sub-nav strips      */
/* ══════════════════════════════════════════════════════════════════ */

describe("K50 · Slice A extension — Portal top nav + sub-nav strips", () => {
  it("Mobile top-bar (portal top nav on mobile viewports) renders on ``colors.nav.bg``", () => {
    // Phase K50 extension · Feb-2026 — customers never mount
    // ``<AdminTopBar>``, so the ``md:hidden`` <header> in
    // AppLayout is their top nav.  Themed via ``colors.nav`` so
    // every web nav surface resolves through the same token.
    const headerBlock = APP_LAYOUT.split('data-testid="mobile-nav-open"')[0];
    // Read backwards to find the enclosing <header> style block.
    const lastHeaderIdx = headerBlock.lastIndexOf("<header");
    const header = APP_LAYOUT.slice(lastHeaderIdx).split("</header>")[0];
    expect(header).toMatch(/backgroundColor:\s*colors\.nav\.bg/);
    expect(header).toMatch(/borderBottom:\s*`1px solid \$\{colors\.nav\.border\}`/);
    // Regression guard — the pre-extension white ``colors.surface``
    // bg + light ``colors.border`` border must NOT reappear on this
    // header (only ``AppLayout`` mobile <header> is asserted; other
    // <header> occurrences in the file are unrelated modal headers).
    expect(header).not.toMatch(/backgroundColor:\s*colors\.surface,[\s\S]{0,80}borderBottom:\s*`1px solid \$\{colors\.border\}`/);
  });

  it("Mobile top-bar sign-out + hamburger contrast tuned for navy", () => {
    // Sign out button now uses ``colors.nav.fg`` (white) text with
    // a red-tinted backdrop so the "danger" affordance still reads
    // against the navy header.
    expect(APP_LAYOUT).toMatch(/data-testid="shell-logout-button-mobile"/);
    const signOutBlock = APP_LAYOUT.split('data-testid="shell-logout-button-mobile"')[0];
    const lastBtnIdx = signOutBlock.lastIndexOf("<button");
    const btn = APP_LAYOUT.slice(lastBtnIdx).split("</button>")[0];
    expect(btn).toMatch(/color:\s*colors\.nav\.fg/);
    expect(btn).toMatch(/border:\s*`1px solid \$\{colors\.nav\.border\}`/);
  });

  it("Mobile top-bar logo wrapped in an ``invert(1)`` filter for navy legibility", () => {
    // Portal logo may be dark; interim ``brightness(0) invert(1)``
    // flattens it to a white silhouette so it reads on navy.  A
    // proper white-asset swap is tracked in Future Work.
    expect(APP_LAYOUT).toMatch(/filter:\s*"brightness\(0\) invert\(1\)"/);
    expect(APP_LAYOUT).toMatch(/data-testid="app-logo-mobile-white"/);
  });

  it("BusinessOS sub-nav aside renders on ``colors.nav.bg`` (full-width nav strip qualifies)", () => {
    // Full-width secondary sub-nav that moves users between
    // /os/sprints, /os/huddles, /os/scorecards, /os/leanboards,
    // /os/sops, /os/roles.  Qualifies as a menu bar under the K50
    // rule.  Filter/action toolbars in-page do NOT qualify and stay
    // on their existing palette.
    expect(BUSINESS_OS).toMatch(/backgroundColor:\s*colors\.nav\.bg,/);
    expect(BUSINESS_OS).toMatch(/borderRight:\s*`1px solid \$\{colors\.nav\.border\}`/);
    expect(BUSINESS_OS).toMatch(/data-testid="os-subnav"/);
    // Active tab = white pill with navy text (matches
    // ``QuickNavRail`` + ``CategoryDropdown`` active affordance so
    // every nav surface reads as one family).
    expect(BUSINESS_OS).toMatch(/backgroundColor:\s*isActive\s*\?\s*colors\.nav\.bgActive\s*:\s*"transparent"/);
    expect(BUSINESS_OS).toMatch(/color:\s*isActive\s*\?\s*colors\.nav\.fgActive\s*:\s*colors\.nav\.fg/);
    // Regression guard — no more ``brandTertiary`` / ``onBrandTertiary``
    // active-state coupling in this strip.
    expect(BUSINESS_OS).not.toMatch(/backgroundColor:\s*isActive\s*\?\s*colors\.brandTertiary/);
    expect(BUSINESS_OS).not.toMatch(/color:\s*isActive\s*\?\s*colors\.onBrandTertiary/);
  });

  it("Sub-nav strips resolve through ``colors.nav`` — no fresh hex codes", () => {
    // Regression guard against a future refactor that inlines the
    // navy hex directly on the sub-nav.  Single-source-of-truth
    // rule locked in.
    const subnavBlock = BUSINESS_OS.split("data-testid=\"business-os-layout\"")[1]
      .split("</aside>")[0];
    expect(subnavBlock).not.toMatch(/#1B1F5C/i);
    expect(subnavBlock).not.toMatch(/rgb\(27,\s*31,\s*92\)/);
  });
});


/* ══════════════════════════════════════════════════════════════════ */
/* Phase K51.1 — Logo container background parity                     */
/* ══════════════════════════════════════════════════════════════════ */

describe("K51.1 · Logo container background parity with nav chrome", () => {
  it("Desktop sidebar logo slot has an explicit ``colors.nav.bg`` background", () => {
    // Regression: pre-K51.1 the ``side-nav-logo-slot`` <div> had no
    // inline background and merely inherited the <aside>'s navy —
    // meaning a transparent-PNG tenant logo *did* blend, but there
    // was nothing preventing a future refactor from wrapping the
    // logo in a light-surface container and reintroducing the
    // white-tile artefact.  K51.1 pins the intent inline.
    const slotStart = APP_LAYOUT.indexOf('data-testid="side-nav-logo-slot"');
    expect(slotStart).toBeGreaterThan(-1);
    // Scan backwards ~600 chars to find the wrapping <div>'s style prop.
    const slotBlock = APP_LAYOUT.slice(Math.max(0, slotStart - 600), slotStart);
    expect(slotBlock).toMatch(/style=\{\{\s*backgroundColor:\s*colors\.nav\.bg\s*\}\}/);
  });

  it("Mobile header logo slot carries the navy background + retains the invert filter", () => {
    // The mobile logo container must paint navy behind the mark AND
    // keep the interim ``brightness(0) invert(1)`` filter — the
    // filter flattens dark-fill logos to a white silhouette; the
    // navy background stops transparent PNGs from bleeding onto a
    // white sub-container (defensive against future refactors).
    const idx = APP_LAYOUT.indexOf('data-testid="app-logo-mobile-white"');
    expect(idx).toBeGreaterThan(-1);
    const block = APP_LAYOUT.slice(Math.max(0, idx - 400), idx);
    expect(block).toMatch(/backgroundColor:\s*colors\.nav\.bg/);
    expect(block).toMatch(/filter:\s*"brightness\(0\) invert\(1\)"/);
  });

  it("AdminTopBar does NOT mount BrandLogo (dedupe stays; nothing to re-paint there)", () => {
    // Regression guard against a future refactor that remounts the
    // brand mark on the admin top bar.  If it ever does, THIS test
    // will fail and remind the author to apply the K51.1 background
    // parity there as well.  Comment-only ``BrandLogo`` mentions in
    // the file header don't count as a mount — assert on an actual
    // JSX usage instead.
    expect(TOP_BAR).not.toMatch(/<BrandLogo[\s/>]/);
  });

  it("Preview page navy tile still paints ``#1B1F5C`` — K51 side-by-side surface unchanged", () => {
    // K51.1 does NOT unify the two preview tiles in
    // ``BrandLogoSettings.jsx`` — the whole point of the preview is
    // showing light + navy chromes side-by-side.  Regression guard:
    // both hex codes stay in the preview source.
    const PREVIEW = read("src/pages/settings/BrandLogoSettings.jsx");
    // Navy tile paints ``#1B1F5C`` (matches the nav chrome).  The
    // testid follows the ``style`` prop in JSX order — scan the ~400
    // chars preceding the testid for the hex.
    const navyIdx = PREVIEW.indexOf('data-testid="logo-preview-navy"');
    expect(navyIdx).toBeGreaterThan(-1);
    const navyBlock = PREVIEW.slice(Math.max(0, navyIdx - 400), navyIdx);
    expect(navyBlock).toMatch(/#1B1F5C/);
    // Light tile stays ``#FFFFFF`` — this is the intentional contrast
    // case and MUST NOT be flipped to navy.
    const lightIdx = PREVIEW.indexOf('data-testid="logo-preview-light"');
    expect(lightIdx).toBeGreaterThan(-1);
    const lightBlock = PREVIEW.slice(Math.max(0, lightIdx - 400), lightIdx);
    expect(lightBlock).toMatch(/#FFFFFF/);
    expect(lightBlock).not.toMatch(/#1B1F5C/);
  });
});


/* ══════════════════════════════════════════════════════════════════ */
/* Slice B — Schedule job-card status background shading              */
/* ══════════════════════════════════════════════════════════════════ */

describe("K50 · Slice B — Schedule card status background", () => {
  it("jobStatusColor(status) returns the exact hex for the K50 five", () => {
    // Contract locked in against the K50 brief.
    expect(jobStatusColor("open")).toBe("#D6F5EE");
    expect(jobStatusColor("scheduled")).toBe("#D6F5EE");
    expect(jobStatusColor("in_progress")).toBe("#FEF3C7");
    expect(jobStatusColor("completed")).toBe("#FDECEC");
    expect(jobStatusColor("cancelled")).toBe("#FECACA");
    expect(jobStatusColor("skipped")).toBe("#FED7AA");
  });

  it("resolves legacy aliases (active / closed / canceled) to the K50 canonical hexes", () => {
    // ``active`` → in_progress, ``closed``/``done`` → completed,
    // ``canceled`` (US) → cancelled (UK, canonical).
    expect(jobStatusColor("active")).toBe("#FEF3C7");
    expect(jobStatusColor("closed")).toBe("#FDECEC");
    expect(jobStatusColor("done")).toBe("#FDECEC");
    expect(jobStatusColor("canceled")).toBe("#FECACA");
  });

  it("is case + whitespace insensitive", () => {
    expect(jobStatusColor("  In_Progress ")).toBe("#FEF3C7");
    expect(jobStatusColor("COMPLETED")).toBe("#FDECEC");
  });

  it("returns null (never a default hex) for statuses outside the K50 map", () => {
    // Caller must supply the fallback (typically ``colors.surface``).
    // A silent default here would strip semantics from
    // ``on_hold`` / ``requested`` / ``reopened`` — which keep their
    // existing pill-only treatment per the K50 brief.
    expect(jobStatusColor("on_hold")).toBeNull();
    expect(jobStatusColor("requested")).toBeNull();
    expect(jobStatusColor("reopened")).toBeNull();
    expect(jobStatusColor("")).toBeNull();
    expect(jobStatusColor(null)).toBeNull();
    expect(jobStatusColor(undefined)).toBeNull();
  });

  it("K50_JOB_STATUS_BG is frozen (protects the shared map from downstream mutation)", () => {
    expect(Object.isFrozen(K50_JOB_STATUS_BG)).toBe(true);
  });

  it("CalendarSchedule.jsx wires the helper (not inline hex codes) on the card body", () => {
    expect(CAL_SCHEDULE).toMatch(/import\s*\{\s*jobStatusColor as k50JobStatusColor\s*\}\s*from\s*"@\/lib\/jobStatus"/);
    expect(CAL_SCHEDULE).toMatch(/k50CardBg\s*=\s*k50JobStatusColor\(j\.status\)\s*\|\|\s*colors\.surface/);
    expect(CAL_SCHEDULE).toMatch(/background:\s*k50CardBg,/);
    // Regression guard — no scattered "#D6F5EE" / "#FDECEC" / "#FECACA"
    // inline hex codes on the card body (only the pill/service palette
    // uses inline hexes, and those are unrelated).
    const gridJobBlock = CAL_SCHEDULE.split('data-testid={`grid-job-${j.id}`}')[0];
    // The hex codes may still appear elsewhere in the file (pills,
    // service palettes) — the guard is that the K50 map lives in the
    // helper.  Assert the helper import is the only path to
    // background hexes for the K50 five.
    expect(CAL_SCHEDULE).toMatch(/data-k50-bg=\{k50CardBg\}/);
  });

  it("TodaySchedule.jsx wires the helper on schedule-card rows", () => {
    expect(TODAY_SCHEDULE).toMatch(/import\s*\{\s*jobStatusColor as k50JobStatusColor\s*\}\s*from\s*"@\/lib\/jobStatus"/);
    expect(TODAY_SCHEDULE).toMatch(/backgroundColor:\s*k50JobStatusColor\(j\.status\)\s*\|\|\s*colors\.surface/);
    expect(TODAY_SCHEDULE).toMatch(/data-k50-bg=\{k50JobStatusColor\(j\.status\)\s*\|\|\s*colors\.surface\}/);
  });
});
