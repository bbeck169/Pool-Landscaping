/**
 * BULK-RESCHEDULE-FIX · Feb-2026 — regression guard for the
 * unified selection pools on CalendarSchedule.
 *
 * Context: the Schedule grid historically carried two parallel
 * selection pools — ``checked`` (round pill, drove Complete +
 * Bulk Reschedule) and ``selectedJobIds`` (square, drove Delete +
 * Reassign + Route). Either checkbox updated only one pool so
 * tapping the visually-obvious SQUARE and then "Bulk Reschedule"
 * showed "(0)" with a disabled button.
 *
 * The fix mirrors every write across both setters.  Because
 * ``CalendarSchedule.jsx`` is a 3.4-kloc component with no
 * exported state helpers, this test locks the contract via a
 * source-text grep (same pattern as ``task-l-jobslist-photos-
 * column.test.jsx``) so a drift that removes the mirror in any
 * of the six touched handlers surfaces here before shipping.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/schedule/CalendarSchedule.jsx"),
  "utf8",
);

describe("BULK-RESCHEDULE-FIX · selection pool unification", () => {
  it("toggleJobSelected mirrors into checked", () => {
    // Pull the body between ``const toggleJobSelected`` and the
    // next top-level ``const`` so the regex stays resilient to
    // whitespace / comment changes inside the function.
    const m = SRC.match(
      /const toggleJobSelected = \(jid\) => \{([\s\S]*?)\n {2}\};\n/,
    );
    expect(m, "toggleJobSelected must exist").toBeTruthy();
    const body = m[1];
    expect(body).toMatch(/setSelectedJobIds\(\(prev\)/);
    expect(body).toMatch(/setChecked\(\(prev\)/);
  });

  it("toggleCheck mirrors into selectedJobIds", () => {
    const m = SRC.match(
      /const toggleCheck = \(id\) => \{([\s\S]*?)\n {2}\};\n/,
    );
    expect(m, "toggleCheck must exist").toBeTruthy();
    const body = m[1];
    expect(body).toMatch(/setChecked\(\(cur\)/);
    expect(body).toMatch(/setSelectedJobIds\(\(cur\)/);
  });

  it("clearSelection clears BOTH pools", () => {
    const m = SRC.match(
      /const clearSelection = \(\) => \{([\s\S]*?)\n {2}\};\n/,
    );
    expect(m, "clearSelection must exist").toBeTruthy();
    const body = m[1];
    expect(body).toMatch(/setSelectedJobIds\(new Set\(\)\)/);
    expect(body).toMatch(/setChecked\(new Set\(\)\)/);
  });

  it("selectAllInView seeds BOTH pools with the same ids", () => {
    const m = SRC.match(
      /const selectAllInView = React\.useCallback\(\(\) => \{([\s\S]*?)\n {2}\}, \[\]\);/,
    );
    expect(m, "selectAllInView must exist").toBeTruthy();
    const body = m[1];
    expect(body).toMatch(/setSelectedJobIds\(new Set\(ids\)\)/);
    expect(body).toMatch(/setChecked\(new Set\(ids\)\)/);
  });

  it("bulkComplete clears BOTH pools after dispatch", () => {
    // Isolate the bulkComplete body so we don't accidentally
    // match the setChecked() calls that live inside unrelated
    // handlers earlier/later in the file.
    const m = SRC.match(
      /const bulkComplete = async \(\) => \{([\s\S]*?)\n {2}\};\n/,
    );
    expect(m, "bulkComplete must exist").toBeTruthy();
    const body = m[1];
    expect(body).toMatch(/setChecked\(new Set\(\)\)/);
    expect(body).toMatch(/setSelectedJobIds\(new Set\(\)\)/);
  });

  it("bulkMove onClear clears BOTH pools after dispatch", () => {
    const m = SRC.match(
      /const bulkMove = async \(\) => \{([\s\S]*?)\n {2}\};\n/,
    );
    expect(m, "bulkMove must exist").toBeTruthy();
    const body = m[1];
    // The onClear callback is the single place in bulkMove that
    // nukes the selection — assert both setters land inside it.
    expect(body).toMatch(/onClear: \(\) => \{[\s\S]*setChecked\(new Set\(\)\)/);
    expect(body).toMatch(/onClear: \(\) => \{[\s\S]*setSelectedJobIds\(new Set\(\)\)/);
  });
});
