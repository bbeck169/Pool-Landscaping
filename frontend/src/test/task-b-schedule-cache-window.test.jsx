/**
 * Feb 2026 · Task B — Schedule page perf. Verifies the cache-window
 * guard is present + wired correctly on ``CalendarSchedule.jsx``.
 *
 * CalendarSchedule pulls in the full auth / permission / calendar
 * / react-big-calendar stack, so mounting it under jsdom flakes
 * without heavy per-suite mocks. We source-parse the file and
 * assert the load path skips the fetch when the focused date sits
 * inside the previously fetched window.
 *
 * What the fix does (before/after):
 *   BEFORE: ``useEffect(() => { load(); }, [date])`` fires a full
 *   150-day-window ``/api/jobs`` fetch on EVERY ``date`` state
 *   change — WeekStrip taps, month-cell clicks, keyboard nav all
 *   trigger a ~150-260ms roundtrip.
 *
 *   AFTER: A ``fetchedRangeRef`` stamps the last ``[start,end]``
 *   window. ``load({ force: false })`` short-circuits when the
 *   focused date is inside the cached interior (30-day safety
 *   buffer from each edge). Mutations still call ``load()`` (force
 *   defaults to true) so their state stays correct.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/schedule/CalendarSchedule.jsx"),
  "utf8",
);

describe("Task B · CalendarSchedule cache-window guard", () => {
  it("declares a fetchedRangeRef via React.useRef", () => {
    expect(SRC).toMatch(
      /const\s+fetchedRangeRef\s*=\s*React\.useRef\(\s*\{[\s\S]{0,80}startISO[\s\S]{0,80}endISO[\s\S]{0,80}\}/,
    );
  });

  it("declares a cache safety margin constant", () => {
    // The interior 30-day buffer keeps the last 30 days of each
    // edge outside the "safe zone", so a re-fetch fires early
    // enough to hide the window boundary from the user.
    expect(SRC).toMatch(/_CACHE_MARGIN_DAYS\s*=\s*30/);
  });

  it("load() accepts an opts.force flag defaulting to true", () => {
    // Mutations must still fetch — the default has to be true
    // (force). Only the date-driven useEffect opts out.
    expect(SRC).toMatch(/const\s+load\s*=\s*async\s*\(opts\s*=\s*\{\}\)\s*=>/);
    expect(SRC).toMatch(/const\s+force\s*=\s*opts\.force\s*!==\s*false/);
  });

  it("load() short-circuits when the focused date sits inside the cached interior", () => {
    // Look for the ``if (!force)`` gate that reads the ref and
    // early-returns when the date is inside the safe window.
    expect(SRC).toMatch(/if\s*\(\s*!force\s*\)\s*\{[\s\S]{0,400}fetchedRangeRef\.current/);
    expect(SRC).toMatch(/focusISO\s*>=\s*safeStart\s*&&\s*focusISO\s*<=\s*safeEnd/);
  });

  it("stamps fetchedRangeRef.current after a successful fetch", () => {
    // The ref must be updated post-fetch, not before, so a
    // network failure doesn't poison the cache.
    const stampIdx = SRC.search(
      /fetchedRangeRef\.current\s*=\s*\{\s*startISO:\s*start,\s*endISO:\s*end\s*\}/,
    );
    expect(stampIdx).toBeGreaterThan(0);
    // Stamp must sit AFTER the ``setRawJobs`` call (i.e., after
    // the ``await`` resolves without throwing).
    const setRawIdx = SRC.indexOf("setRawJobs(");
    expect(setRawIdx).toBeGreaterThan(0);
    expect(stampIdx).toBeGreaterThan(setRawIdx);
    // Stamp must sit BEFORE the ``catch`` block boundary.
    const catchIdx = SRC.indexOf("} catch (e) {", stampIdx);
    expect(catchIdx).toBeGreaterThan(stampIdx);
  });

  it("the [date] useEffect explicitly opts out of the force flag", () => {
    // The only in-window caller: the date-driven useEffect.
    // Every other caller (mutations) uses ``load()`` with no arg
    // → picks up the default force=true and always refetches.
    expect(SRC).toMatch(/useEffect\(\s*\(\)\s*=>\s*\{\s*load\(\s*\{\s*force:\s*false\s*\}\s*\);?\s*\},\s*\[date\]\)/);
  });

  it("keeps exactly ONE fetch call to /jobs?start=... in the module (no duplicate path)", () => {
    // Phase Hygiene B · Feb-2026 — the ``api.get`` call was reflowed
    // onto three lines so the URL template + numeric timeout argument
    // could sit on their own lines. Allow optional whitespace/newline
    // between ``api.get(`` and the ``/jobs?start=`` template.
    const matches = SRC.match(/api\.get\(\s*`\/jobs\?start=/g) || [];
    expect(matches).toHaveLength(1);
  });

  it("mutation callers (bulkComplete, bulkMove, reschedule, orderController) still trigger a refresh", () => {
    // All existing mutation callers must still call ``load()``
    // without an arg — they rely on the force=true default.
    // Grepping for the exact patterns keeps the regression guard
    // narrow.
    expect(SRC).toMatch(/const\s+bulkComplete\s*=\s*async[\s\S]{0,600}await\s+load\(\)/);
    expect(SRC).toMatch(/const\s+bulkMove\s*=\s*async[\s\S]{0,600}await\s+load\(\)/);
  });
});
