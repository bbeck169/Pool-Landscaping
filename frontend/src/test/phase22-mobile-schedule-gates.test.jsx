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
  it("schedule/calendar.tsx wraps NotificationBell with marginRight >= 44", () => {
    const src = fs.readFileSync(
      path.resolve(
        __dirname,
        "../../../mobile/app/(app)/schedule/calendar.tsx",
      ),
      "utf-8",
    );
    // The bell wrapper must include a marginRight that clears the
    // hamburger tap target (44dp iOS HIG minimum).
    const m = src.match(/marginRight:\s*(\d+)[^\d]/);
    expect(m).not.toBeNull();
    expect(Number(m[1])).toBeGreaterThanOrEqual(44);
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
    // Every non-Complete pill must sit inside an ``isAdmin ? …`` gate.
    for (const testid of [
      'testID="grid-bulk-move"',
      'testID="grid-bulk-delete"',
      'testID="grid-bulk-reassign"',
      'testID="grid-bulk-rearrange"',
    ]) {
      const idx = src.indexOf(testid);
      expect(idx).toBeGreaterThan(-1);
      // Look for ``isAdmin ?`` in the ~200 chars before the testid.
      const window = src.substring(Math.max(0, idx - 400), idx);
      expect(window.includes("isAdmin ?")).toBe(true);
    }
  });
});
