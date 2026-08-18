/**
 * Feb-2026 · Schedule Select-All affordance (web) role gate + wiring.
 *
 * Source-inspection contract:
 *   1. Pre-selection bar renders "Select all in view (N)" for admin+.
 *   2. Toolbar (when items selected) exposes the same
 *      ``grid-selection-select-all`` testid so users can escalate.
 *   3. ``canMultiSelectDelete`` widened to include manager.
 *   4. ``onSelectAllInView`` is passed into ``GridPanel``.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const src = fs.readFileSync(
  path.resolve(__dirname, "../pages/schedule/CalendarSchedule.jsx"),
  "utf8",
);

describe("Schedule · Select-All affordance", () => {
  it("canMultiSelectDelete includes manager", () => {
    expect(src).toMatch(
      /canMultiSelectDelete\s*=\s*\[["']admin["'],\s*["']super_admin["'],\s*["']manager["']\]/,
    );
  });

  it("pre-selection bar renders Select all in view (N) for admins", () => {
    expect(src).toMatch(/data-testid=["']grid-selection-preselect-bar["']/);
    expect(src).toMatch(/Select all in view \(\{jobs\.length\}\)/);
    // Guarded by canMultiSelectDelete (chained after the active-toolbar
    // ternary — just assert both fragments coexist in the same file).
    expect(src).toMatch(
      /canMultiSelectDelete\s*&&\s*Array\.isArray\(jobs\)\s*&&\s*jobs\.length\s*>\s*0/,
    );
  });

  it("active toolbar also exposes Select all in view (for escalation)", () => {
    expect(src).toMatch(
      /data-testid=["']grid-selection-toolbar["'][\s\S]{0,900}data-testid=["']grid-selection-select-all["']/,
    );
  });

  it("selectAllInView is threaded through to GridPanel via props", () => {
    expect(src).toMatch(/onSelectAllInView=\{selectAllInView\}/);
    expect(src).toMatch(/onSelectAllInView,\s*\n/);
  });
});
