/**
 * Feb-2026 · Drill-down role expansion — 403 UX contract.
 *
 * Mirrors the K41 / K48 / INCOME-DRILLDOWN-EDIT source-scan pattern
 * already used in
 * ``src/components/dashboard/__tests__/DashboardDrillDownModal.categoryServiceUnit.test.jsx``
 * — no full modal mount, no ``@/api`` mock plumbing.  Each spec
 * targets the ``ModalBody`` function body so the tests run fast and
 * only fail when the observable contract inside the load-error
 * catch clause actually drifts.
 *
 * Contract locked in:
 *   1. The load-effect catch handler surfaces the exact
 *      ``You do not have permission to view this data`` copy when
 *      the backend returns HTTP 403.
 *   2. The 500 / network / timeout fallback is preserved verbatim
 *      (``e?.message || "Load failed"``) so unrelated failures keep
 *      the pre-existing generic banner.
 *   3. The 403 branch keys off ``e?.status === 403`` — the shape the
 *      ``@/api`` fetch wrapper attaches to every non-ok response
 *      (see ``src/api.js`` line 258 · ``err.status = res.status``).
 *   4. The rendered error banner still uses ``data-testid=
 *      "drilldown-error"`` in both variant branches so the QA
 *      selector suite keeps working.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (rel) =>
  fs.readFileSync(path.resolve(process.cwd(), rel), "utf-8");

const MODAL = read("src/components/dashboard/DashboardDrillDownModal.jsx");

/* Slice the ModalBody function body once so per-test regex scans
 * stay focused on the right lexical scope. */
const MODAL_BODY = MODAL.split("function ModalBody(")[1].split(
  "\nfunction ",
)[0];

const CATCH_BLOCK = MODAL_BODY.split(".catch((e) => {")[1].split("})")[0];


describe("Drill-down role expansion — 403 UX", () => {
  it("catch handler branches on e?.status === 403", () => {
    // The 403 check keys off the ``err.status`` field attached by
    // ``src/api.js`` — a bare ``e.response.status`` (axios-style)
    // would silently miss every failure.
    expect(CATCH_BLOCK).toMatch(/if\s*\(\s*e\?\.status\s*===\s*403\s*\)/);
  });

  it("403 branch surfaces the exact QA-contract copy", () => {
    // Character-exact match — the spec fixes the string verbatim
    // so a copy tweak surfaces here immediately.
    expect(CATCH_BLOCK).toContain(
      'setErr("You do not have permission to view this data")',
    );
  });

  it("non-403 errors preserve the pre-existing generic fallback", () => {
    // Fallback must remain ``e?.message || "Load failed"`` so 500 /
    // network / timeout keep firing the same banner they always did.
    expect(CATCH_BLOCK).toMatch(
      /setErr\(\s*e\?\.message\s*\|\|\s*"Load failed"\s*\)/,
    );
  });

  it("permission copy is only rendered in the 403 branch — never as a fallback", () => {
    // Guards against a copy-paste where the string leaks into the
    // else-branch and swallows real 500 messages.
    const parts = CATCH_BLOCK.split(
      'setErr("You do not have permission to view this data")',
    );
    expect(parts).toHaveLength(2);
    // The generic ``Load failed`` fallback must exist AFTER the
    // permission-copy setter — proving the else-branch survives.
    expect(parts[1]).toMatch(/setErr\(\s*e\?\.message/);
  });

  it("error banner selector (data-testid=drilldown-error) still renders in both variant branches", () => {
    // ``err`` is surfaced through the SAME banner both variants
    // already used — no bespoke 403-only widget.  Guards the
    // selector contract the QA suite reads.
    const bannerHits = MODAL_BODY.match(
      /data-testid="drilldown-error">\{err\}</g,
    );
    expect(bannerHits?.length ?? 0).toBeGreaterThanOrEqual(2);
  });

  it("permission copy is NOT used as the successful-load fallback", () => {
    // The rows-success path (``.then((r) => …)``) must not touch
    // the permission-copy string — it lives inside the catch only.
    const thenBlock = MODAL_BODY.split(".then((r) => {")[1]
      .split("})")[0];
    expect(thenBlock).not.toMatch(/permission to view this data/i);
  });
});
