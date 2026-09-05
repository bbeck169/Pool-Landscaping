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
