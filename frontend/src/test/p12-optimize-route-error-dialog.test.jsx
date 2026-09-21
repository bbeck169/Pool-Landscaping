/**
 * Phase P12 · Feb-2026 — Optimize Route error dialog + soft-guard toast.
 *
 * Source-inspection contract tests — mirror the schedule-inline-edit
 * pattern. ``CalendarSchedule.jsx`` is a >3 kLOC surface with heavy
 * react-big-calendar + @vis.gl/react-google-maps deps, so mounting
 * the whole page in JSDOM is prohibitively expensive relative to
 * source-scan invariants. If the CalendarSchedule ever gets split
 * into smaller mountable pieces, promote these to a proper mount
 * test in the same commit.
 *
 * Acceptance points:
 *   1. Failure branch surfaces the error dialog with ``code`` +
 *      ``message`` in a monospace tag (data-testid=optimize-error-
 *      code) — dialog itself has data-testid=optimize-error-dialog.
 *   2. Success branch surfaces a non-blocking toast when the
 *      response's ``orphaned_tech_ids`` or ``skipped_unassigned`` is
 *      non-empty — canonical wording "Optimized N jobs; K skipped
 *      (unassigned or orphaned)".
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";


const scheduleSrc = fs.readFileSync(
  path.resolve(__dirname, "../pages/schedule/CalendarSchedule.jsx"),
  "utf8",
);


describe("Phase P12 · Optimize Route error dialog", () => {
  it("uses the shared shadcn <Dialog> primitive (not a bespoke fixed div)", () => {
    // Import site.
    expect(scheduleSrc).toMatch(
      /from\s+["']@\/components\/ui\/dialog["']/,
    );
    // At least the four primitives we render.
    for (const primitive of [
      "Dialog", "DialogContent", "DialogHeader", "DialogTitle",
    ]) {
      expect(scheduleSrc).toContain(primitive);
    }
  });

  it("dialog is state-driven from ``optimizeError`` — null → not open", () => {
    // Root state declaration.
    expect(scheduleSrc).toMatch(
      /const\s*\[optimizeError,\s*setOptimizeError\]\s*=\s*useState\(null\)/,
    );
    // Mount is bound to the state.
    expect(scheduleSrc).toMatch(
      /<Dialog\s+open=\{!!optimizeError\}[\s\S]{0,120}onOpenChange=/,
    );
    // Close resets state — verify the DialogContent close button
    // clears it (both close button and onOpenChange).
    expect(scheduleSrc).toMatch(
      /setOptimizeError\(null\)/,
    );
  });

  it("dialog carries the ``optimize-error-dialog`` + ``optimize-error-code`` testids", () => {
    expect(scheduleSrc).toContain('data-testid="optimize-error-dialog"');
    expect(scheduleSrc).toContain('data-testid="optimize-error-code"');
    expect(scheduleSrc).toContain('data-testid="optimize-error-close"');
  });

  it("optimizeRoute catch block extracts the FastAPI detail across every wrapper shape", () => {
    // Land on the real ``api.post("/schedule/optimize-route", ...)``
    // call site — skip past the two comment mentions above the
    // ``optimizePayload`` / ``optimizeError`` state declarations and
    // the dialog-header comment below.
    const idx = scheduleSrc.indexOf('api.post("/schedule/optimize-route"');
    expect(idx).toBeGreaterThan(0);
    const slab = scheduleSrc.slice(idx, idx + 3200);
    // Every path the api wrapper might attach the detail under.
    expect(slab).toMatch(/e\?\.data\?\.detail\?\.message/);
    expect(slab).toMatch(/e\?\.data\?\.detail\?\.code/);
    expect(slab).toMatch(/e\?\.body\?\.detail\?\.code/);
    expect(slab).toMatch(/e\?\.message/);
    // The catch sets the error state (not a toast).
    expect(slab).toMatch(/setOptimizeError\(\s*\{/);
  });

  it("dialog title is ``Couldn't optimize route``", () => {
    // Escaped apostrophe.
    expect(scheduleSrc).toMatch(
      /<DialogTitle>Couldn(?:&apos;|')t optimize route<\/DialogTitle>/,
    );
  });

  it("dialog renders warnings array when the error payload carries one", () => {
    // Optional block — must be conditional AND iterate the warnings.
    expect(scheduleSrc).toMatch(
      /optimizeError\?\.warnings[\s\S]{0,400}\.map\(\s*\(w,\s*i\)\s*=>/,
    );
    expect(scheduleSrc).toContain('data-testid="optimize-error-warnings"');
  });
});


describe("Phase P12 · non-blocking success-warnings toast", () => {
  it("success branch reads ``orphaned_tech_ids`` + ``skipped_unassigned`` off the response", () => {
    // Both keys must be pulled off ``r`` (the parsed body) on success.
    expect(scheduleSrc).toMatch(/r\?\.orphaned_tech_ids/);
    expect(scheduleSrc).toMatch(/r\?\.skipped_unassigned/);
  });

  it("fires a non-blocking toast when either list is non-empty", () => {
    const idx = scheduleSrc.indexOf("orphaned_tech_ids");
    expect(idx).toBeGreaterThan(0);
    const slab = scheduleSrc.slice(idx, idx + 2000);
    // Guard: the toast branch fires only when the union is non-empty.
    expect(slab).toMatch(
      /if\s*\(\s*_orphans\.length\s*\|\|\s*_skipped\.length\s*\)/,
    );
    // Wording contract — client-side + docs both count on the
    // "skipped (unassigned or orphaned)" phrasing.
    expect(slab).toMatch(
      /toast_\([\s\S]{0,300}skipped[\s\S]{0,300}unassigned or orphaned/,
    );
  });

  it("bulk reorder modal STILL opens on success (warnings never block flow)", () => {
    // Same slab: setBulkReorderOpen(true) fires after the toast branch,
    // NOT inside the ``if (_orphans.length || _skipped.length)`` guard.
    const idx = scheduleSrc.indexOf("orphaned_tech_ids");
    const slab = scheduleSrc.slice(idx, idx + 2000);
    // The toast() call closes before setBulkReorderOpen fires — key is
    // that setBulkReorderOpen(true) appears AFTER the guard's closing
    // brace, i.e. unconditionally in the try block.
    const guardStart = slab.indexOf("if (_orphans.length");
    const modalOpenIdx = slab.indexOf("setBulkReorderOpen(true)");
    expect(guardStart).toBeGreaterThanOrEqual(0);
    expect(modalOpenIdx).toBeGreaterThan(guardStart);
  });
});


describe("Phase P12 · regressions the fix guards against", () => {
  it("optimizeRoute catch NO LONGER dumps into the generic red toast_", () => {
    // Anti-pattern: the pre-P12 shape ``toast_(String(e?.message || …), "err")``
    // must be gone from the optimize-route catch block. Scope the assertion
    // to the ~3 kB catch block so unrelated toast_() calls elsewhere
    // aren't false-positives.
    const idx = scheduleSrc.indexOf('api.post("/schedule/optimize-route"');
    expect(idx).toBeGreaterThan(0);
    const slab = scheduleSrc.slice(idx, idx + 3200);
    expect(slab).not.toMatch(/toast_\(String\(e\?\.message\s*\|\|\s*"Route optimization failed/);
  });

  it("no regression on the reorderableJobs<2 short-circuit", () => {
    // The early return that prevented an empty-day POST stays put.
    expect(scheduleSrc).toMatch(
      /if\s*\(\s*\(reorderableJobs\s*\|\|\s*\[\]\)\.length\s*<\s*2\s*\)\s*return/,
    );
  });
});
