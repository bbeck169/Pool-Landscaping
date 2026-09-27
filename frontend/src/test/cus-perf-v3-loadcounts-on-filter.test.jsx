/**
 * Feb-2026 · CUS-perf v3 — CustomersList consumes /customers/counts on filter changes.
 *
 * Locks 4 contracts:
 *   1. The load useEffect fires BOTH ``load()`` and ``loadCounts()``
 *      in parallel via ``Promise.all`` on every filter / search /
 *      tab / page / sort change.  (R3=B ruling.)
 *   2. ``loadCounts()`` reads the ``all`` bucket directly from the
 *      ``/customers/counts`` response (R2 ruling — backend is the
 *      single source of truth), with a client-side fallback
 *      (``active + inactive + muted``) for the rollout window.
 *   3. The redundant mount-only ``loadCounts()`` useEffect that
 *      duplicated the primary Promise.all on initial mount was
 *      removed.
 *   4. The ``counts_by_status`` read at line ~638 is still present
 *      (vestigial per R5) — not asserted removed in this commit
 *      (that's the follow-up per
 *      FOLLOWUP_CUS_PERF_V3_ENVELOPE_DEPRECATION.md).
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";


const LIST_PATH = path.resolve(
  process.cwd(), "src/pages/customers/CustomersList.jsx",
);
const readSrc = (p) => fs.readFileSync(p, "utf8");


describe("CUS-perf v3 · CustomersList wiring", () => {
  it("primary useEffect fires load() + loadCounts() in parallel via Promise.all", () => {
    const src = readSrc(LIST_PATH);
    // R3=B — literal Promise.all([load(), loadCounts()]) call site.
    expect(src).toMatch(/Promise\.all\(\[\s*load\(\)\s*,\s*loadCounts\(\)\s*\]\)/);
    // The doc-comment references the R3=B ruling so a future
    // reviewer sees the rationale.
    expect(src).toMatch(/R3=B/);
    // The useEffect's filter-dep array still includes the same
    // filters as the pre-change ``load`` effect — no coverage
    // regression on filter changes.
    expect(src).toMatch(
      /\[searchDeb,\s*tag,\s*scope,\s*tab,\s*missingCardOnly,\s*missingEmail,/,
    );
  });

  it("loadCounts reads the `all` bucket from /customers/counts response with a client-side fallback", () => {
    const src = readSrc(LIST_PATH);
    // Positive — r.all consumption.
    expect(src).toMatch(/Number\.isFinite\(r\?\.all\)/);
    // Client-side fallback for the deploy-order gap (backend not yet
    // shipping ``all``): derive from active + inactive + muted.
    expect(src).toMatch(
      /r\?\.active[\s\S]{0,200}r\?\.inactive[\s\S]{0,200}r\?\.muted/,
    );
    // The R2 comment references the vestigial fallback rationale.
    expect(src).toMatch(/CUS-perf v3.*``all`` bucket/is);
  });

  it("mount-only loadCounts useEffect was removed (folded into Promise.all)", () => {
    const src = readSrc(LIST_PATH);
    // Positive — the removal-explanation comment is present so a
    // future reader knows what happened.  The comment spans 2 lines
    // in source; the regex tolerates the newline + comment prefix
    // between the two anchor phrases.
    expect(src).toMatch(/mount-only ``loadCounts\(\)``[\s\S]{0,80}was folded into/);
    // Negative — strip block comments + line comments from the
    // source before applying the shape regex so my own removal-
    // documentation comment (which quotes the pre-change useEffect
    // as a snippet) doesn't trip the guard.  Line-comment strip:
    // drop everything from ``//`` to end-of-line.  We don't need
    // block-comment stripping because CustomersList.jsx doesn't
    // use ``/* */`` in the mount-effect region.
    const stripped = src.replace(/\/\/.*$/gm, "");
    expect(stripped).not.toMatch(
      /useEffect\(\s*\(\)\s*=>\s*\{[\s\S]{0,240}loadCounts\(\);[\s\S]{0,120}\},\s*\[\]\);/,
    );
  });

  it("counts_by_status envelope read is preserved (vestigial per R5)", () => {
    const src = readSrc(LIST_PATH);
    // Per R5 — the FE still reads ``data.counts_by_status`` from
    // the paginated envelope for the deploy-order gap.  Follow-up
    // per FOLLOWUP_CUS_PERF_V3_ENVELOPE_DEPRECATION.md removes it.
    expect(src).toMatch(/const cbs = data\?\.counts_by_status;/);
    // The setCounts block that consumes ``cbs`` is still there.
    expect(src).toMatch(/setCounts\(\{[\s\S]{0,400}active:\s*Number\.isFinite\(cbs\.active\)/);
  });
});
