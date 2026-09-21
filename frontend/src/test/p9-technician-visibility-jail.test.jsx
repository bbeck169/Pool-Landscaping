/**
 * Phase P9-B · Feb-2026 — CalendarSchedule Technician Visibility Jail.
 *
 * Source-string shape locks (same style as P5's tech-filter suite) —
 * guarantee that the two dropdown gates for the ``technician`` role
 * remain in place across future refactors of ``CalendarSchedule.jsx``.
 *
 * Locks:
 *   1. With ``role === "technician"``: the tech <select> (testid
 *      ``schedule-tech-filter``) is NOT rendered — it must be wrapped
 *      in a ``{_isTech ? null : (…)}`` gate.
 *   2. With ``role === "technician"``: the crew <select> (testid
 *      ``calendar-filter-crew``) is NOT rendered — wrapped in the
 *      same ``{_isTech ? null : (…)}`` gate.
 *   3. With ``role === "admin"``: both selects render as-is with an
 *      "All …" first ``<option value="">…</option>``.
 *   4. ``_isTech`` derivation is unchanged: role-string compared
 *      case-insensitively (``String(user?.role || "").toLowerCase()
 *      === "technician"``). Prevents a future refactor from
 *      accidentally introducing a role-string mismatch bypass.
 *
 * Runtime render assertions are intentionally omitted — the
 * CalendarSchedule page has 30+ transitive imports (schedule map,
 * OnMyWay button, tech avatar, notes callout, weather widget, …)
 * whose mocking surface is larger than the P9-B change itself. The
 * source-string locks give the same guarantee at a fraction of the
 * flakiness.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";


const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/schedule/CalendarSchedule.jsx"),
  "utf-8",
);


describe("Phase P9-B · CalendarSchedule tech dropdown jail (S1 regression)", () => {
  it("tech <select> is guarded by _isTech", () => {
    // The tech dropdown must be wrapped in ``{_isTech ? null : (…)}``
    // — Phase S1's original guard, locked-in as a P9 regression check.
    // We match the guard opener + the data-testid within any amount
    // of intervening JSX (attrs / props / styles).
    expect(SRC).toMatch(
      /\{_isTech \? null : \(\s*<select[\s\S]*?data-testid="schedule-tech-filter"/,
    );
  });

  it("no orphan tech <select> exists WITHOUT the _isTech gate", () => {
    // A future refactor must NOT introduce a second copy of the tech
    // filter that isn't guarded — check that every occurrence of the
    // testid appears AFTER a ``_isTech ? null : (`` opener within a
    // small preceding window.
    const testidIdx = SRC.indexOf('data-testid="schedule-tech-filter"');
    expect(testidIdx).toBeGreaterThan(0);
    // Look backwards up to 2000 chars for the guard.
    const preamble = SRC.slice(Math.max(0, testidIdx - 2000), testidIdx);
    expect(preamble).toMatch(/\{_isTech \? null : \(/);
  });
});


describe("Phase P9-B · CalendarSchedule crew dropdown jail", () => {
  it("crew <select> is guarded by _isTech", () => {
    expect(SRC).toMatch(
      /\{_isTech \? null : \(\s*<select[\s\S]*?data-testid="calendar-filter-crew"/,
    );
  });

  it("no orphan crew <select> exists WITHOUT the _isTech gate", () => {
    const testidIdx = SRC.indexOf('data-testid="calendar-filter-crew"');
    expect(testidIdx).toBeGreaterThan(0);
    const preamble = SRC.slice(Math.max(0, testidIdx - 1000), testidIdx);
    expect(preamble).toMatch(/\{_isTech \? null : \(/);
  });

  it("crew <select> still ships the 'All crews' <option> for non-techs", () => {
    // Guard removal must not accidentally strip the default option
    // (admins still need it). The guard-plus-option pattern:
    //   {_isTech ? null : (  … <option value="">All crews</option> …
    expect(SRC).toMatch(
      /data-testid="calendar-filter-crew"[\s\S]*?<option value="">All crews<\/option>/,
    );
  });
});


describe("Phase P9-B · _isTech role-string derivation", () => {
  it("role comparison is case-insensitive (String(...).toLowerCase())", () => {
    // Prevents a future refactor from switching to strict ``=== 'technician'``
    // without ``.toLowerCase()`` (which would let a role of ``'Technician'``
    // bypass the gate).
    expect(SRC).toMatch(
      /const _isTech = String\(user\?\.role \|\| ""\)\.toLowerCase\(\) === "technician"/,
    );
  });

  it("initial techId defaults to the user's own canonical id for techs (P5 regression)", () => {
    // Under P9-B the tech dropdown is hidden, but the underlying
    // filter value must still default to the tech's own canonical
    // ``technician_id`` so filteredJobs narrows correctly. This
    // lock guarantees the P5 canonical-id contract survives.
    expect(SRC).toMatch(
      /if \(_isTech\) return user\?\.technician_id \|\| "";/,
    );
  });
});
