/**
 * Feb-2026 · Clock-in gate — CalendarSchedule opener wiring.
 *
 * The gate lives at the OPENER call sites (schedule surface),
 * not inside ``<ChecklistModal>`` itself.  Mounting the 3.4kLoc
 * calendar page in a unit test is impractical, so this file uses
 * a source-scan pattern — same convention already established for
 * ``k71-line-items-editor.test.jsx`` and the drilldown-forbidden
 * spec — to prove the wiring is intact.
 *
 * Contract locked in:
 *   1. The hook + dialog are imported from ``@/hooks/useClockInGate``.
 *   2. The hook is invoked ONCE at the component top level with the
 *      current user (``useClockInGate(user)``).
 *   3. Every checklist opener path wraps its ``setChecklistJobId``
 *      through ``clockGate.openJob(id, cb)`` — never a direct call.
 *   4. The ``<ClockInGateDialog />`` is mounted with the shared
 *      ``clockGate`` prop so the prompt surfaces on demand.
 *   5. The pending-state selector (``data-testid=
 *      "clockin-gate-dialog"``) is preserved so QA + downstream
 *      wiring tests keep resolving.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (rel) =>
  fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");

const CAL = read("src/pages/schedule/CalendarSchedule.jsx");


describe("CalendarSchedule · clock-in gate wiring", () => {
  it("imports both ``useClockInGate`` and ``ClockInGateDialog`` from the shared hook", () => {
    expect(CAL).toMatch(
      /import\s*\{\s*useClockInGate\s*,\s*ClockInGateDialog\s*\}\s*from\s*["']@\/hooks\/useClockInGate["']/,
    );
  });

  it("invokes the hook once at the component top level with the current user", () => {
    // ``const clockGate = useClockInGate(user);`` — one and only
    // one hook mount per calendar-page render.
    const mounts = CAL.match(/useClockInGate\s*\(\s*user\s*\)/g) || [];
    expect(mounts.length).toBe(1);
  });

  it("every checklist opener routes through clockGate.openJob(id, cb)", () => {
    // Direct calls like ``setChecklistJobId(id)`` outside a
    // ``clockGate.openJob(...)`` callback would bypass the gate.
    // The wiring pattern is:
    //     clockGate.openJob(id, () => setChecklistJobId(id))
    // At least two call sites exist on the schedule surface
    // (top-level tap + <BulkGrid onOpenJob>).
    const wired = CAL.match(
      /clockGate\.openJob\s*\(\s*[a-zA-Z_.[\]]+\s*,\s*\(\)\s*=>\s*setChecklistJobId/g,
    ) || [];
    expect(wired.length).toBeGreaterThanOrEqual(2);
  });

  it("mounts <ClockInGateDialog gate={clockGate} /> so the prompt can surface", () => {
    expect(CAL).toMatch(
      /<ClockInGateDialog\s+gate=\{clockGate\}\s*\/>/,
    );
  });

  it("no rogue direct ``setChecklistJobId(ev.id)`` OUTSIDE the gate callback", () => {
    // Guards against a future refactor accidentally re-introducing
    // a direct opener that skips the gate.  Every occurrence of
    // ``setChecklistJobId(<jobId>)`` inside JSX / handler bodies
    // must live INSIDE a ``clockGate.openJob`` arrow-function
    // callback — never as a standalone statement.
    //
    // Whitelist: setter declarations, ``setChecklistJobId(null)``
    // to close the modal, and calls whose immediate lexical
    // context is inside a ``clockGate.openJob(..., () =>
    // setChecklistJobId(...))`` arrow.
    const directCalls = [
      ...CAL.matchAll(/setChecklistJobId\s*\(\s*([^)\s]+)\s*\)/g),
    ];
    const rogue = directCalls.filter((m) => {
      const arg = m[1];
      // Allowed: close-modal null-set + the useState setter.
      if (arg === "null") return false;
      // Allowed: inside ``clockGate.openJob(id, () => setChecklistJobId(id))`` —
      // detect by scanning the preceding 80 chars for the arrow-
      // wrapping pattern.
      const start = Math.max(0, m.index - 80);
      const window = CAL.slice(start, m.index);
      if (/clockGate\.openJob\s*\([^,]+,\s*\(\)\s*=>\s*$/.test(window)) {
        return false;
      }
      return true;
    });
    expect(rogue).toHaveLength(0);
  });
});
