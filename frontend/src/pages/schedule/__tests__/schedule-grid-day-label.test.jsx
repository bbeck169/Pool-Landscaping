/**
 * TD-schedule-date-navigator-current-date-label · Feb-2026 — source-
 * shape locks for the GridPanel day-nav toolbar.
 *
 * Pre-ticket layout pushed the dynamic ``grid-day-label`` to the far
 * right of the toolbar row via a ``flex-1`` spacer, so the triad
 * ``[prev][Today][next]`` read as "always says Today" to operators.
 * This suite locks the hoisted layout:
 *
 *   1. ``grid-day-label`` lives INSIDE the ``grid-day-head`` flex row
 *      (not in a separate container below).
 *   2. Within that row, ``grid-day-label`` appears AFTER
 *      ``grid-next-day`` (adjacency lock — operator sees the viewed
 *      date immediately next to the next-day arrow).
 *   3. There is NO ``flex-1`` spacer between ``grid-next-day`` and
 *      ``grid-day-label`` — the date must not be pushed away from
 *      the triad.
 *   4. The label carries ``text-base font-bold`` (visual dominance
 *      over the ``text-xs font-bold`` Today CTA).
 *   5. All existing day-nav toolbar testIDs still appear in source:
 *      ``grid-view``, ``grid-day-head``, ``grid-prev-day``,
 *      ``grid-today``, ``grid-next-day``, ``grid-day-label``.
 *
 * Deliberately a source-shape lock (no full mount) because
 * ``CalendarSchedule.jsx`` is 3.8k LOC with a transitive dep graph
 * (date-fns, react-big-calendar, google-maps, api) whose collection
 * phase hangs vitest in this repo's config (see ll-ai-rewrite-wiring
 * test for the same pattern — Phase 41.5 handoff note).
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";


function readSrc(rel) {
  return fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");
}


describe("TD-schedule-date-navigator-current-date-label · GridPanel day-nav", () => {
  const SRC = readSrc("src/pages/schedule/CalendarSchedule.jsx");

  it("grid-day-label lives inside the grid-day-head flex row", () => {
    // Slice from the opening ``grid-day-head`` div to its closing
    // ``</div>`` sibling boundary and assert ``grid-day-label``
    // appears inside.
    const headOpen = SRC.indexOf('data-testid="grid-day-head"');
    expect(headOpen).toBeGreaterThan(-1);
    // The grid-day-head container is a single-depth flex row — its
    // closing ``</div>`` is the first bare ``</div>`` after we've
    // closed every inner ``<div...>`` + ``<button...>``.  We don't
    // need to balance perfectly; we just slice a generous window
    // and check adjacency / order via substring positions.
    const headBlock = SRC.slice(headOpen, headOpen + 3000);
    expect(headBlock).toContain('data-testid="grid-day-label"');
  });

  it("grid-day-label appears AFTER grid-next-day in source order "
     + "(adjacency lock — operator sees the date next to the next-day arrow)", () => {
    const nextIdx = SRC.indexOf('data-testid="grid-next-day"');
    const labelIdx = SRC.indexOf('data-testid="grid-day-label"');
    expect(nextIdx).toBeGreaterThan(-1);
    expect(labelIdx).toBeGreaterThan(-1);
    expect(labelIdx).toBeGreaterThan(nextIdx);
  });

  it("no flex-1 spacer sits BETWEEN grid-next-day and grid-day-label "
     + "(spacer is what caused the pre-ticket visual disconnect)", () => {
    const nextIdx = SRC.indexOf('data-testid="grid-next-day"');
    const labelIdx = SRC.indexOf('data-testid="grid-day-label"');
    const between = SRC.slice(nextIdx, labelIdx);
    expect(between).not.toMatch(/className=["']flex-1["']/);
  });

  it("grid-day-label carries text-base font-bold "
     + "(visual dominance over the text-xs Today CTA)", () => {
    const labelIdx = SRC.indexOf('data-testid="grid-day-label"');
    expect(labelIdx).toBeGreaterThan(-1);
    // Walk backwards up to 400 chars to the opening ``<div`` of this
    // label element and inspect its className.
    const back = Math.max(0, labelIdx - 400);
    const openBlock = SRC.slice(back, labelIdx);
    expect(openBlock).toMatch(/text-base font-bold/);
    // Regression lock — pre-ticket class string must be gone from
    // this element.
    expect(openBlock).not.toMatch(/className=["']text-sm font-semibold["']\s+style=\{\{\s*color:\s*colors\.onSurface\s*\}\}\s+data-testid=["']grid-day-label["']/);
  });

  it("preserves every existing day-nav toolbar testID", () => {
    for (const tid of [
      "grid-view",
      "grid-day-head",
      "grid-prev-day",
      "grid-today",
      "grid-next-day",
      "grid-day-label",
    ]) {
      expect(SRC, `missing testid: ${tid}`)
        .toContain(`data-testid="${tid}"`);
    }
  });
});
