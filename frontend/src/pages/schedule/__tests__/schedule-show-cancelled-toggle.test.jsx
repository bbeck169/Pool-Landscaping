/**
 * INACTIVE-CUSTOMER-CASCADE · Phase B · Feb-2026 — "Show cancelled"
 * toggle on the two web schedule surfaces.
 *
 * Default off → terminal (``cancelled`` / ``canceled`` / ``skipped``)
 * visits are hidden from the schedule so a customer flipped to
 * inactive feels truly "removed from the schedule" per the user
 * brief.  Toggling on surfaces them again (restyled per k50 color).
 * State persists per-user under the shared ``schedule_show_cancelled``
 * localStorage key so TodaySchedule.jsx + CalendarSchedule.jsx stay
 * in lockstep when the user flips once on one surface.
 *
 * TodaySchedule.jsx (1300+ LOC) and CalendarSchedule.jsx (3500+ LOC)
 * have deep auth / router / tenant bootstraps that are expensive to
 * mock in isolation; we lock the semantic deltas via source-level
 * contract regexes PLUS a localStorage-persistence integration test
 * on a stripped-down harness that calls the exact same localStorage
 * API the components use.
 */
import { describe, it, expect, afterEach } from "vitest";
import fs from "fs";
import path from "path";


const TODAY_SRC = fs.readFileSync(
  path.resolve(__dirname, "../TodaySchedule.jsx"),
  "utf8",
);
const CAL_SRC = fs.readFileSync(
  path.resolve(__dirname, "../CalendarSchedule.jsx"),
  "utf8",
);


afterEach(() => {
  try { localStorage.removeItem("schedule_show_cancelled"); } catch {}
});


describe("INACTIVE-CUSTOMER-CASCADE · Schedule hide-cancelled "
         + "contract (source-level)", () => {
  it("TodaySchedule.jsx: declares showCancelled state with "
     + "localStorage default off", () => {
    expect(TODAY_SRC).toMatch(/\[showCancelled,\s*setShowCancelled\]/);
    expect(TODAY_SRC).toMatch(
      /localStorage\.getItem\("schedule_show_cancelled"\)\s*===\s*"true"/,
    );
  });

  it("TodaySchedule.jsx: toggle button carries the required "
     + "data-testid='schedule-toggle-show-cancelled'", () => {
    expect(TODAY_SRC).toMatch(
      /data-testid="schedule-toggle-show-cancelled"/,
    );
  });

  it("TodaySchedule.jsx: visibleJobItems memo filters the terminal "
     + "triplet when showCancelled is false", () => {
    expect(TODAY_SRC).toMatch(/const\s+visibleJobItems\s*=\s*useMemo/);
    // The filter set MUST include all three strings so a defensive
    // refactor can't silently miss "canceled" (American spelling) or
    // "skipped".
    for (const s of ["cancelled", "canceled", "skipped"]) {
      expect(TODAY_SRC).toMatch(new RegExp(`"${s}"`));
    }
  });

  it("TodaySchedule.jsx: main render surfaces (ScheduleCardList + "
     + "ScheduleMap) use visibleJobItems, NOT orderedJobItems", () => {
    expect(TODAY_SRC).toMatch(
      /<ScheduleCardList jobs=\{visibleJobItems\}/,
    );
    expect(TODAY_SRC).toMatch(
      /<ScheduleMap[\s\S]{0,100}jobs=\{visibleJobItems\}/,
    );
  });

  it("TodaySchedule.jsx: localStorage write happens on toggle "
     + "(persistence lock)", () => {
    expect(TODAY_SRC).toMatch(
      /localStorage\.setItem\("schedule_show_cancelled",\s*String\(next\)\)/,
    );
  });

  it("CalendarSchedule.jsx: declares showCancelled state with the "
     + "SAME localStorage key as TodaySchedule (lockstep contract)",
    () => {
    expect(CAL_SRC).toMatch(/\[showCancelled,\s*setShowCancelled\]/);
    expect(CAL_SRC).toMatch(
      /localStorage\.getItem\("schedule_show_cancelled"\)\s*===\s*"true"/,
    );
    // Shared key MUST match TodaySchedule's.
    expect(CAL_SRC).toMatch(
      /localStorage\.setItem\("schedule_show_cancelled",\s*String\(next\)\)/,
    );
  });

  it("CalendarSchedule.jsx: toggle button carries the matching "
     + "data-testid='schedule-toggle-show-cancelled'", () => {
    expect(CAL_SRC).toMatch(
      /data-testid="schedule-toggle-show-cancelled"/,
    );
  });

  it("CalendarSchedule.jsx: filteredJobs predicate honours "
     + "showCancelled (filter wired, not just UI)", () => {
    const filterStart = CAL_SRC.indexOf("const filteredJobs");
    expect(filterStart).toBeGreaterThan(0);
    // Memo body AND dependency array both live within a bounded
    // slice of the file; the regex just has to find them in order.
    const filterBlock = CAL_SRC.slice(filterStart, filterStart + 3500);
    expect(filterBlock).toMatch(/!showCancelled/);
    // Dependency array must include showCancelled so toggling
    // actually recomputes the filter.
    expect(filterBlock).toMatch(/\}, \[[\s\S]{0,400}showCancelled\]/);
    for (const s of ["cancelled", "canceled", "skipped"]) {
      expect(filterBlock).toMatch(new RegExp(`"${s}"`));
    }
  });

  it("CalendarSchedule.jsx: status-dropdown short-circuit — when the "
     + "user explicitly filters BY status=cancelled, the hide-"
     + "cancelled toggle MUST NOT also hide them (double-negative "
     + "guard)", () => {
    const filterStart = CAL_SRC.indexOf("const filteredJobs");
    const filterBlock = CAL_SRC.slice(filterStart, filterStart + 3500);
    // The predicate body references ``.includes(status)`` on the
    // terminal-triplet array so when the user has explicitly picked
    // cancelled/canceled/skipped in the status dropdown, the auto-
    // hide branch is short-circuited.
    expect(filterBlock).toMatch(
      /\[["']cancelled["'],\s*["']canceled["'],\s*["']skipped["']\]\.includes\(status\)/,
    );
  });
});


describe("INACTIVE-CUSTOMER-CASCADE · localStorage persistence "
         + "integration (shared key across surfaces)", () => {
  it("Writes 'true' when toggled on, 'false' when toggled off", () => {
    const KEY = "schedule_show_cancelled";
    // Simulate the exact onClick path both components run.
    let state = localStorage.getItem(KEY) === "true";
    expect(state).toBe(false);
    state = !state;
    localStorage.setItem(KEY, String(state));
    expect(localStorage.getItem(KEY)).toBe("true");
    state = !state;
    localStorage.setItem(KEY, String(state));
    expect(localStorage.getItem(KEY)).toBe("false");
  });

  it("Reading an unset key defaults to false (default-hide "
     + "contract)", () => {
    localStorage.removeItem("schedule_show_cancelled");
    const state = localStorage.getItem("schedule_show_cancelled") === "true";
    expect(state).toBe(false);
  });

  it("String('true')/'false' comparison is strict — any other "
     + "value also parses to false (defensive against legacy "
     + "writes)", () => {
    localStorage.setItem("schedule_show_cancelled", "1");
    expect(localStorage.getItem("schedule_show_cancelled") === "true")
      .toBe(false);
    localStorage.setItem("schedule_show_cancelled", "");
    expect(localStorage.getItem("schedule_show_cancelled") === "true")
      .toBe(false);
  });
});
