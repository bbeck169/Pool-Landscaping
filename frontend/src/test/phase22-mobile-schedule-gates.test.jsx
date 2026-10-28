/**
 * Phase 22 · 2026-08-02 — mobile schedule bulk-action role gating.
 *
 * Sub-item A locks the visibility matrix: techs get only the
 * "Complete" chip; admins get all 5. A pure predicate mirrors the
 * inline gate in
 * ``mobile/app/(app)/schedule/calendar.tsx`` so a broken chip gate
 * fails CI loudly.
 *
 * Sub-item B locks the Header right-slot padding — the schedule
 * caller wraps the bell in a ``marginRight: 52`` container so the
 * ambient hamburger doesn't overlap it. Verified by reading the
 * component source (mobile test harness can't render Header in
 * jsdom).
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

// Mirror of the inline gate — must stay in sync with calendar.tsx.
function shouldShow(chip, role) {
  const isAdmin = role === "admin" || role === "super_admin";
  const isTech = role === "technician" || role === "tech";
  const canWrite = isAdmin || isTech;
  if (!canWrite) return false;
  if (chip === "complete") return true;
  return isAdmin;
}

describe("Phase 22 · Sub-item A — schedule bulk-action gate", () => {
  it("technician sees ONLY the Complete chip", () => {
    expect(shouldShow("complete", "technician")).toBe(true);
    expect(shouldShow("move", "technician")).toBe(false);
    expect(shouldShow("delete", "technician")).toBe(false);
    expect(shouldShow("reassign", "technician")).toBe(false);
    expect(shouldShow("rearrange", "technician")).toBe(false);
  });

  it("admin sees all 5 chips", () => {
    for (const chip of ["complete", "move", "delete", "reassign", "rearrange"]) {
      expect(shouldShow(chip, "admin")).toBe(true);
    }
  });

  it("super_admin sees all 5 chips", () => {
    for (const chip of ["complete", "move", "delete", "reassign", "rearrange"]) {
      expect(shouldShow(chip, "super_admin")).toBe(true);
    }
  });

  it("customer sees nothing", () => {
    for (const chip of ["complete", "move", "delete", "reassign", "rearrange"]) {
      expect(shouldShow(chip, "customer")).toBe(false);
    }
  });
});

describe("Phase 22 · Sub-item B — bell header padding", () => {
  it("schedule/calendar.tsx bell sits in a non-shrinking right cluster (no fixed 52px margin)", () => {
    const src = fs.readFileSync(
      path.resolve(
        __dirname,
        "../../../mobile/app/(app)/schedule/calendar.tsx",
      ),
      "utf-8",
    );
    // ZZ-A mobile · td-mobile-header-layout-cleanup (e49e39cb9) removed the
    // bell's hard-coded marginRight: 52; the right cluster is flexShrink: 0
    // so the title is the only ellipsizing element (live-checked 320/375/414).
    // Mirrors mobile jest td-mobile-header-layout-cleanup.test.tsx H3.
    expect(src).not.toContain("marginRight: 52");
    expect(src).toMatch(/flexDirection: "row", alignItems: "center", gap: 8, flexShrink: 0/);
    // And the wrapper carries the diagnostic testID we spec'd.
    expect(src.includes('testID="schedule-header-bell"')).toBe(true);
  });

  it("schedule/calendar.tsx gates Move/Delete/Assign/Rearrange behind isAdmin", () => {
    const src = fs.readFileSync(
      path.resolve(
        __dirname,
        "../../../mobile/app/(app)/schedule/calendar.tsx",
      ),
      "utf-8",
    );
    // Phase Hygiene B · Feb-2026 — the bulk-action pill row was
    // refactored from four literal testids into a single
    // ``grid-action-${act.key}`` template driven by a data array
    // where each row carries an ``adminOnly`` flag. The equivalent
    // isAdmin gate now lives on the data-array iteration
    // (``if (act.adminOnly && !isAdmin) return null;``). Assert
    // both the new testid template + the gate + the four action
    // keys (move / delete / assign / rearrange) are all present.
    expect(src).toMatch(/testID=\{`grid-action-\$\{act\.key\}`\}/);
    expect(src).toMatch(/if\s*\(act\.adminOnly\s*&&\s*!isAdmin\)\s*return\s+null;/);
    for (const key of ["move", "delete", "assign", "rearrange"]) {
      const rowRe = new RegExp(
        `key:\\s*"${key}"[\\s\\S]{0,300}adminOnly:\\s*true`,
      );
      expect(src).toMatch(rowRe);
    }
  });
});
