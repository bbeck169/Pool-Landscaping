/**
 * Phase P37 · Feb-2026 — CustomersList row-callback memoization
 * contract tests.
 *
 * Source-lint style (same pattern as
 * ``customer-details-pagination.test.jsx``) — a full
 * ``<CustomersList />`` mount would pull in ~40 dependency
 * components (bulk-select toolkit, tag-filter dropdown, portal-
 * onboarding tile, communications timeline, add-card flow, …)
 * that don't need to be exercised to lock the P37 contract.
 *
 * P37 refinement note — the top-level CustomersList already
 * server-side paginates at ``pageSize ∈ [25, 50, 100]``, so full
 * row-component extraction + windowing would net a marginal DOM
 * win at high risk (the row is 250 lines of JSX with 15+
 * parent-scope references). Instead we shipped the actually-
 * effective perf fix: ``useCallback``-stable ``toggle`` so the
 * per-row checkbox reference doesn't churn on every parent
 * re-render (search-input keystroke, delivery-status poll tick,
 * etc.). Full row-extraction + windowing is deferred to a
 * follow-up phase — see the P37 PRD section for the rationale.
 *
 * These tests lock:
 *   1. ``toggle`` is wrapped in ``useCallback`` — reference stable.
 *   2. ``toggle`` uses functional ``setSelected`` so it doesn't
 *      capture a stale ``selected`` in its closure.
 *   3. P34 bulk-invite testids on rows still exist (regression
 *      guard against the memoization refactor accidentally
 *      dropping the checkbox).
 *   4. P34 delivery-status polling column still renders (survives
 *      the memoization refactor).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const PAGE_PATH = resolve(
  __dirname,
  "../pages/customers/CustomersList.jsx",
);
const pageSrc = readFileSync(PAGE_PATH, "utf8");


describe("P37 · CustomersList · memoization contract", () => {
  it("1) toggle is wrapped with useCallback for stable identity", () => {
    // P37 · replaced the inline arrow ``const toggle = (id) => {…}``
    // with a useCallback-wrapped version so the checkbox onChange
    // handler reference is stable across parent re-renders.
    expect(pageSrc).toMatch(
      /const\s+toggle\s*=\s*useCallback\(\s*\(id\)\s*=>/,
    );
    // Empty deps array — the callback doesn't close over any
    // parent-scope variable that could go stale (uses functional
    // setSelected).
    expect(pageSrc).toMatch(
      /const\s+toggle\s*=\s*useCallback\([\s\S]*?\},\s*\[\]\);/,
    );
  });

  it("2) toggle uses functional setSelected — no stale closure", () => {
    // ``setSelected((prev) => { … })`` is the shape that survives
    // when useCallback deps are empty. A ``setSelected(next)``
    // that references a captured ``selected`` would be a bug.
    expect(pageSrc).toMatch(/setSelected\(\(prev\)\s*=>\s*\{/);
    expect(pageSrc).toMatch(/const\s+next\s*=\s*new\s+Set\(prev\)/);
  });

  it("3) P34 bulk-invite checkbox testids survive the P37 refactor", () => {
    // Per-row checkbox testid must still render inside the map so
    // the bulk-invite selection flow still works.
    expect(pageSrc).toMatch(/data-testid=\{`bulk-select-row-\$\{c\.id\}`\}/);
    // Select-all header checkbox.
    expect(pageSrc).toMatch(/data-testid="bulk-select-all"/);
    // Row selection wraps the row's leading td.
    expect(pageSrc).toMatch(/data-testid=\{`customer-select-\$\{c\.id\}`\}/);
  });

  it("4) P34 delivery-status polling column survives — testids intact", () => {
    // The P34 delivery panel + per-cid status testid must still
    // render (panel is separate from the row loop; regression
    // guard so a future refactor doesn't accidentally drop it).
    expect(pageSrc).toMatch(/data-testid="p34-delivery-panel"/);
    expect(pageSrc).toMatch(/data-testid=\{`p34-delivery-status-\$\{cid\}`\}/);
    // Polling effect still fires every 15s for up to 2min (8 ticks).
    expect(pageSrc).toMatch(/_POLL_INTERVAL_MS\s*=\s*15_000/);
    expect(pageSrc).toMatch(/_POLL_MAX_TICKS\s*=\s*8/);
  });

  it("5) toggle references useCallback from the React import list", () => {
    expect(pageSrc).toMatch(
      /import\s+React,\s*\{[^}]*useCallback[^}]*\}\s+from\s+["']react["']/,
    );
  });
});
