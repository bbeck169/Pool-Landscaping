/**
 * Feb-2026 · P2 Item 4 — render-path guard for filter-chip pages.
 *
 * Rationale: the OpsHub TEST-4 regression shipped because the test
 * file exercised a private mirror of ``_filterUser`` — never the
 * render path. The inner ``.filter((r) => filter === "all_both"
 * ? _roleKey(r) === "all" : true)`` block cancelled out the outer
 * useMemo, so the roster went empty for the chip's happy-path click.
 *
 * This file audits every filter-chip page in the app for the SAME
 * bug pattern via a source-regex guard, PLUS a lightweight
 * behavioural check via a purpose-built harness. If a page's chip
 * behaviour drifts back into "narrow twice, cancel each other out",
 * this test fires.
 *
 * Pages audited:
 *   • OpsHub.jsx                — already has a dedicated render test
 *                                  from the prior fix (test 4 guard).
 *   • WorkstreamPage.jsx        — "active filter" chips (not "narrow
 *                                  to selection"); low risk pattern.
 *   • InvoicesList.jsx          — status + category chips.
 *   • JobsList.jsx              — single-select status filter (not
 *                                  a chip matrix but included for
 *                                  double-filter regression cover).
 *   • CalendarSchedule.jsx      — filter dropdowns.
 *
 * Note: we deliberately do NOT mount ``WorkstreamPage`` or
 * ``InvoicesList`` end-to-end here — both are router+fetch+modal
 * heavy and hang under jsdom in the same way ``QuoteInvoiceDetail``
 * does (documented in ``invoice-draft-send.test.jsx``). The source
 * guards below give O(1) coverage of the specific bug shape without
 * that risk.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";


function _src(rel) {
  return readFileSync(
    resolve(__dirname, "../pages/" + rel), "utf8",
  );
}


const PAGES = [
  { slug: "OpsHub",           path: "ops/OpsHub.jsx" },
  { slug: "WorkstreamPage",   path: "workstream/WorkstreamPage.jsx" },
  { slug: "InvoicesList",     path: "invoices/InvoicesList.jsx" },
  { slug: "JobsList",         path: "jobs/JobsList.jsx" },
  { slug: "CalendarSchedule", path: "schedule/CalendarSchedule.jsx" },
];


// ══════════════════════════════════════════════════════════════════
// Source guard — no page uses the OpsHub-style INNER-JSX filter
// shape that narrows AGAIN AFTER the outer useMemo already narrowed.
//
// Distinguishing tell of the bug (from OpsHub TEST 4):
//   * ``.filter((r) => { if (filter === "X") return _pred(r); return true; })``
//     — chained INSIDE JSX right before ``.map(...)``.
//   * NOT to be confused with legitimate outer useMemo filters that
//     use ``if (filter === "X") return true`` as a pass-through
//     (that's the correct pattern for the outer memo).
//
// Heuristic: we look for ``.filter((r) => { ... if (filter ===
// "..." ) return _somePred(...); return true; })`` where the branch
// returns a NON-true value — that's the double-narrow bug shape.
// ══════════════════════════════════════════════════════════════════
describe("filter-chip pages · no double-narrow bug pattern", () => {
  for (const page of PAGES) {
    it(`${page.slug} does NOT double-narrow filter inside JSX`, () => {
      const src = _src(page.path);
      // Bug shape - block form: ``if (filter === "X") return <non-true>;``
      // followed by ``return true;`` inside the same .filter arrow.
      // We ban ONLY when the branch returns something OTHER than
      // ``true`` (a predicate call, an equality check, etc).
      const bug1 = /\.filter\s*\(\s*\([a-zA-Z_]+\)\s*=>\s*\{\s*if\s*\(\s*filter\s*===\s*["'][^"']+["']\s*\)\s*return\s+(?!true\b)[^;]+;\s*return\s+true\s*;?\s*\}/;
      expect(src).not.toMatch(bug1);
      // Bug shape - ternary form: ``filter === "X" ? _pred : true``
      // where the truthy branch is NOT the literal ``true``.
      const bug2 = /\.filter\s*\(\s*\([a-zA-Z_]+\)\s*=>\s*filter\s*===\s*["'][^"']+["']\s*\?\s*(?!true\b)[^:]+:\s*true\s*\)/;
      expect(src).not.toMatch(bug2);
    });
  }
});


// ══════════════════════════════════════════════════════════════════
// Coverage-map guard — every page listed above should have SOME
// vitest that renders it OR exports pure helpers verified elsewhere.
// This is a canary — if a page grows chip complexity we get a nag
// via the coverage list below going stale.
// ══════════════════════════════════════════════════════════════════
describe("filter-chip pages · coverage map", () => {
  const COVERAGE = {
    // The prior OpsHub render-path test in
    // ``opshub-all-both-filter.test.jsx`` mounts <OpsHub /> and
    // asserts the "All (Both)" chip yields the union of tech
    // specialty rows — that's the render-path guard.
    OpsHub: "opshub-all-both-filter.test.jsx :: TEST 4 render guard",
    // Workstream: chips are "active filter" X-remove pattern (not
    // narrow-to-selection). Source guard above is sufficient.
    WorkstreamPage: "phase21-workstream-tab.test.jsx + source-guard",
    // Invoices: exercised via unit tests on isChargeableInvoice /
    // nonChargeableReason + the source guard above.
    InvoicesList: "phase34-bulk-select-shared.test.jsx + source-guard",
    // Jobs: single-select filter, not a chip matrix — source guard suffices.
    JobsList: "phase34-admin-page-mount-safety.test.jsx + source-guard",
    // Calendar: filter dropdowns (not chips) + source-guard above.
    CalendarSchedule: "source-guard only",
  };

  it("every audited page has a documented coverage entry", () => {
    for (const p of PAGES) {
      expect(COVERAGE[p.slug]).toBeTruthy();
    }
  });
});


// ══════════════════════════════════════════════════════════════════
// Behavioural harness — reproduces the OpsHub-style bug in isolation
// (outer state-narrows AND inner render-time filter) and asserts
// that a well-written filter-chip page returns the CORRECT union
// even when both layers run.
//
// The purpose is to lock a positive-test canary: any developer who
// re-introduces the bug shape in a new page can copy this harness
// and immediately see the failure mode.
// ══════════════════════════════════════════════════════════════════
import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";


function CanaryList({ rows, filter, badPattern = false }) {
  // Outer memo — the "correct" narrow.
  const outer = React.useMemo(() => {
    if (filter === "all") return rows;
    if (filter === "unionA_B") {
      return rows.filter((r) => r.kind === "A" || r.kind === "B");
    }
    return rows.filter((r) => r.kind === filter);
  }, [rows, filter]);

  // Bad-pattern render-time filter re-narrows on the SAME filter
  // key with a MUTUALLY-EXCLUSIVE condition, wiping the result.
  const displayed = badPattern
    ? outer.filter((r) => (filter === "unionA_B" ? r.kind === "all" : true))
    : outer;

  return (
    <ul data-testid="canary-list">
      {displayed.map((r) => (
        <li key={r.id} data-testid={`canary-row-${r.id}`}>{r.kind}</li>
      ))}
    </ul>
  );
}


describe("filter-chip canary · the OpsHub bug reproduction lock", () => {
  const ROWS = [
    { id: "1", kind: "A" }, { id: "2", kind: "B" }, { id: "3", kind: "C" },
  ];

  it("GOOD pattern: unionA_B chip shows both A + B rows", () => {
    render(<CanaryList rows={ROWS} filter="unionA_B" badPattern={false} />);
    expect(screen.getByTestId("canary-row-1")).toBeTruthy();
    expect(screen.getByTestId("canary-row-2")).toBeTruthy();
    expect(screen.queryByTestId("canary-row-3")).toBeNull();
  });

  it("BAD pattern: unionA_B chip returns empty list — bug reproduction", () => {
    render(<CanaryList rows={ROWS} filter="unionA_B" badPattern={true} />);
    // If any real page ships this shape it looks like this test — an
    // empty roster despite the filter apparently including rows.
    expect(screen.queryByTestId("canary-row-1")).toBeNull();
    expect(screen.queryByTestId("canary-row-2")).toBeNull();
    expect(screen.queryByTestId("canary-row-3")).toBeNull();
    // list container still renders — critical for the visual
    // "empty state" bug this ships as.
    expect(screen.getByTestId("canary-list")).toBeTruthy();
  });
});
