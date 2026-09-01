/**
 * Phase K7 · Feb-2026 — Workstream defaults to today on open.
 *
 * Contract:
 *   1. The ``since`` and ``until`` filter state both initialize to
 *      today's ISO date (``YYYY-MM-DD``) so the first
 *      ``GET /workstream/jobs`` roundtrip returns only today's
 *      completed jobs — matches the DispatchBoard "Today" default
 *      for every role.
 *   2. Users can still widen the range after mount — the constraint
 *      is on the *initial* value, not the setter.
 *   3. The wire URL for the initial fetch contains
 *      ``since=YYYY-MM-DD&until=YYYY-MM-DD`` in the query string.
 *
 * Source-inspection form to avoid the WorkstreamPage runtime setup
 * (customer picker + technicians fetch + shared ScheduleJobEditModal
 * tree — already covered by the sibling ``workstream-bulk-actions``
 * suite for other behaviours).
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";


const SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/workstream/WorkstreamPage.jsx"),
  "utf8",
);


describe("WorkstreamPage · K7 today-default filter", () => {
  it("initializes ``since`` and ``until`` to today's ISO date", () => {
    // The K7 helper computes ``new Date().toISOString().slice(0, 10)``
    // and passes it to BOTH ``useState`` calls.
    expect(SRC).toMatch(
      /new\s+Date\(\)\s*\.\s*toISOString\(\)\s*\.\s*slice\(\s*0\s*,\s*10\s*\)/,
    );
    expect(SRC).toMatch(
      /const\s+\[since,\s*setSince\]\s*=\s*useState\(\s*_K7_TODAY_ISO\s*\)/,
    );
    expect(SRC).toMatch(
      /const\s+\[until,\s*setUntil\]\s*=\s*useState\(\s*_K7_TODAY_ISO\s*\)/,
    );
    // Regression guard: the pre-K7 empty-string defaults MUST NOT
    // return silently.
    expect(SRC).not.toMatch(
      /useState\(\s*""\s*\)\s*;\s*\/\/[^\n]*(since|until)/i,
    );
  });

  it("the initial fetch URL carries ``since`` and ``until`` in the querystring", () => {
    // ``load()`` builds a URLSearchParams and conditionally appends
    // both fields.  Since the K7 initial state is truthy for both,
    // the first roundtrip URL contains them.
    expect(SRC).toMatch(
      /if\s*\(\s*since\s*\)\s*qs\.set\(\s*"since"\s*,\s*since\s*\)/,
    );
    expect(SRC).toMatch(
      /if\s*\(\s*until\s*\)\s*qs\.set\(\s*"until"\s*,\s*until\s*\)/,
    );
    // Fetch wire hits the K7-affected endpoint.
    expect(SRC).toMatch(/api\.get\(`\/workstream\/jobs\?\$\{qs\.toString\(\)\}`\)/);
  });

  it("still allows users to widen the range after mount (setters are exposed)", () => {
    // Regression guard — the setters must remain bound to the
    // filter inputs so the user can override the default.
    expect(SRC).toMatch(/setSince\b/);
    expect(SRC).toMatch(/setUntil\b/);
  });
});
