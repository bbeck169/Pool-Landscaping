/**
 * Feb-2026 · Schedule card redesign — source + behavior contract
 * tests.
 *
 * Locks the post-redesign contract on the two schedule card
 * pages (``TodaySchedule`` + ``CalendarSchedule``):
 *   1. Neither page imports the ``<NavigateJobButton />`` component
 *      any more; the component file survives in the codebase but
 *      the two schedule cards no longer mount it.
 *   2. The customer name is now the primary directions trigger,
 *      wired via ``@/utils/directions``'s ``openDirections`` helper.
 *   3. The address is a second directions trigger, also wired via
 *      ``openDirections``, and bumped to ``text-lg``.
 *   4. Both triggers land the click through ``stopPropagation`` so
 *      the outer card's "open job" handler does NOT fire.
 *   5. ``buildDirectionsUrl(job)`` behavior parity — the URL shape
 *      matches the pre-Feb-2026 ``<NavigateJobButton />`` output
 *      byte-for-byte.
 *
 * Uses source-inspection for the "no NavigateJobButton import"
 * + "text-lg on address" + "directions button testid" guards
 * (Tests 1-2, 6-9), plus real behavior tests against the
 * ``buildDirectionsUrl`` / ``openDirections`` helpers via
 * ``@/utils/directions`` (Tests 3-5) — the helpers ARE the
 * contract, wiring is asserted from source.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  buildDirectionsUrl,
  openDirections,
  resolveDestination,
} from "@/utils/directions";


const TODAY_SRC = readFileSync(
  resolve(__dirname, "../pages/schedule/TodaySchedule.jsx"), "utf8",
);
const CAL_SRC = readFileSync(
  resolve(__dirname, "../pages/schedule/CalendarSchedule.jsx"), "utf8",
);


// ─────────────────────────────────────────────────────────────
// §1 · TodaySchedule + CalendarSchedule no longer import
//        NavigateJobButton.
// ─────────────────────────────────────────────────────────────
/** Strip ``/* ... *​/`` block comments + ``// ...`` line comments
 *  before checking for JSX usage — trailing comment strings that
 *  reference the pre-cleanup ``<NavigateJobButton />`` shouldn't
 *  trip the regression guard. */
function _stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")   // block comments
    .replace(/\/\/[^\n]*/g, "");        // line comments
}

describe("Schedule card redesign — NavigateJobButton unwired", () => {
  it("Test 1 · TodaySchedule.jsx no longer imports NavigateJobButton", () => {
    expect(TODAY_SRC).not.toMatch(
      /import\s+NavigateJobButton\s+from\s+["'][^"']*NavigateJobButton["']/,
    );
    // JSX mount also gone — check the comment-stripped source so
    // narrative references in ``//`` and ``/* */`` blocks don't
    // trip the guard.
    expect(_stripComments(TODAY_SRC)).not.toMatch(/<NavigateJobButton\b/);
  });

  it("Test 2 · CalendarSchedule.jsx no longer imports NavigateJobButton", () => {
    expect(CAL_SRC).not.toMatch(
      /import\s+NavigateJobButton\s+from\s+["'][^"']*NavigateJobButton["']/,
    );
    expect(_stripComments(CAL_SRC)).not.toMatch(/<NavigateJobButton\b/);
  });
});


// ─────────────────────────────────────────────────────────────
// §2 · Helper behavior — buildDirectionsUrl / openDirections.
//        These ARE the contract the schedule cards wire against.
// ─────────────────────────────────────────────────────────────
describe("directions helper — buildDirectionsUrl + openDirections", () => {
  it("Test 3 · buildDirectionsUrl(job) prefers coords when finite + non-(0,0)", () => {
    const job = {
      id: "j-1", customer_name: "Alice",
      latitude: 33.7670356, longitude: -112.3397496,
      address: "123 Main St, Phoenix, AZ",
    };
    const url = buildDirectionsUrl(job);
    expect(url).toBe(
      "https://www.google.com/maps/dir/?api=1&destination=33.7670356%2C-112.3397496",
    );
  });

  it("Test 4 · buildDirectionsUrl(job) falls back to address when coords missing", () => {
    const job = {
      id: "j-2", customer_name: "Bob",
      latitude: null, longitude: undefined,
      address: "  456 Oak Ave, Tucson, AZ  ",
    };
    const url = buildDirectionsUrl(job);
    // ``.trim()`` inside resolveDestination strips the whitespace
    // before URLSearchParams encodes it.
    expect(url).toBe(
      "https://www.google.com/maps/dir/?api=1&destination=456+Oak+Ave%2C+Tucson%2C+AZ",
    );
  });

  it("Test 5 · openDirections stops event propagation + opens the URL in a new tab", () => {
    const stop = vi.fn();
    const originalOpen = window.open;
    const spyOpen = vi.fn();
    // eslint-disable-next-line no-global-assign
    window.open = spyOpen;
    try {
      const job = {
        id: "j-3", customer_name: "Carol",
        latitude: 40.0, longitude: -75.0,
      };
      const opened = openDirections(job, { stopPropagation: stop });
      expect(stop).toHaveBeenCalledTimes(1);
      expect(opened).toBe(true);
      expect(spyOpen).toHaveBeenCalledTimes(1);
      const [url, target, features] = spyOpen.mock.calls[0];
      expect(url).toMatch(
        /^https:\/\/www\.google\.com\/maps\/dir\/\?api=1&destination=40%2C-75/,
      );
      expect(target).toBe("_blank");
      expect(features).toBe("noopener,noreferrer");
    } finally {
      // eslint-disable-next-line no-global-assign
      window.open = originalOpen;
    }
  });

  it("openDirections returns false + does NOT call window.open when the job has no destination", () => {
    const stop = vi.fn();
    const spyOpen = vi.fn();
    const originalOpen = window.open;
    // eslint-disable-next-line no-global-assign
    window.open = spyOpen;
    try {
      const job = { id: "j-4", customer_name: "Dave" };  // no coords, no addr
      const opened = openDirections(job, { stopPropagation: stop });
      // stopPropagation still called — click on a card widget
      // should never bubble to the outer card even if the URL
      // resolution failed.
      expect(stop).toHaveBeenCalledTimes(1);
      expect(opened).toBe(false);
      expect(spyOpen).not.toHaveBeenCalled();
    } finally {
      // eslint-disable-next-line no-global-assign
      window.open = originalOpen;
    }
  });

  it("resolveDestination guards (0, 0) as unusable", () => {
    // Real-world regression — some tenants have (0, 0) rows
    // where the geocode failed.  Coords must NOT win over the
    // address in that case.
    const dest = resolveDestination({
      latitude: 0, longitude: 0, address: "789 Real St",
    });
    expect(dest).toEqual({ kind: "address", value: "789 Real St" });
  });
});


// ─────────────────────────────────────────────────────────────
// §3 · Source-inspection — the two schedule cards wire the
//        directions buttons + preserve outer-card safety.
// ─────────────────────────────────────────────────────────────
describe("Schedule card redesign — wiring guards", () => {
  it("Test 6 · TodaySchedule address block uses text-lg + directions testid", () => {
    // The address ``<div>`` bumped from text-sm to text-lg.
    expect(TODAY_SRC).toMatch(
      /className="text-lg"[\s\S]{0,400}data-testid=\{`schedule-card-address-\$\{j\.id\}`\}/,
    );
    // Directions button testid is present on the address.
    expect(TODAY_SRC).toMatch(
      /data-testid=\{`schedule-card-\$\{j\.id\}-address-directions`\}/,
    );
    // Directions button testid is present on the customer name.
    expect(TODAY_SRC).toMatch(
      /data-testid=\{`schedule-card-\$\{j\.id\}-customer-name-directions`\}/,
    );
  });

  it("Test 7 · CalendarSchedule address block uses text-lg + directions testid", () => {
    // CalendarSchedule bumped from ``text-xs truncate`` → ``text-lg``.
    expect(CAL_SRC).toMatch(/<div className="text-lg" style=\{\{ color: colors\.muted \}\}>/);
    expect(CAL_SRC).toMatch(
      /data-testid=\{`schedule-card-\$\{j\.id\}-address-directions`\}/,
    );
    expect(CAL_SRC).toMatch(
      /data-testid=\{`schedule-card-\$\{j\.id\}-customer-name-directions`\}/,
    );
  });

  it("Test 8 · Both pages route the click through openDirections (stopPropagation guard)", () => {
    // The click handler is a single call to ``openDirections(j, e)``
    // — that helper stops propagation before opening the URL, so
    // the outer card's job-open handler never fires.
    for (const [name, src] of [["TodaySchedule", TODAY_SRC], ["CalendarSchedule", CAL_SRC]]) {
      const opens = src.match(/onClick=\{\(e\) => openDirections\(j, e\)\}/g) || [];
      // 2 per page — one for the customer-name button, one for
      // the address button.
      expect(opens.length,
        `${name}: expected 2 openDirections click handlers, got ${opens.length}`,
      ).toBe(2);
    }
  });

  it("Test 9 · Both pages import the shared directions helper from @/utils/directions", () => {
    for (const [name, src] of [["TodaySchedule", TODAY_SRC], ["CalendarSchedule", CAL_SRC]]) {
      expect(src,
        `${name}: must import buildDirectionsUrl + openDirections from @/utils/directions`,
      ).toMatch(
        /import\s+\{\s*buildDirectionsUrl\s*,\s*openDirections\s*\}\s+from\s+["']@\/utils\/directions["']/,
      );
    }
  });
});
