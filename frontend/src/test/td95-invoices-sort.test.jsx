/**
 * TD-95 · Feb-2026 — Invoices list column header sort · Vitest.
 *
 * Locks the FE-side contract shipped by `td95b-fe`:
 *
 *   1. All 7 operator-listed columns are mounted as
 *      `<_SortableTh>` with the correct `col` value:
 *      `invoice_number`, `title`, `customer_name`, `due_date`,
 *      `total`, `viewed`, `status`.
 *   2. The dormant 3-state cycle is now the 2-state operator-
 *      spec cycle: `inactive → asc → desc → asc → desc → ...`.
 *      No 3rd-click clear.
 *   3. `_STATUS_RANK` constant exists at the module scope with
 *      the operator-approved 7-value priority chain:
 *      `draft(0) → sent(1) → viewed(2) → accepted(3) →
 *      partial(4) → paid(5) → past_due(6)`.
 *   4. `_viewedSortValue` resolver keys on
 *      `last_viewed_at || first_viewed_at || ""` (operator
 *      decision #1 — recency, not `view_count`).
 *   5. `getVal` dispatches on each of the 7 new/retained
 *      columns + preserves the legacy `has_payment_method`
 *      bulk-pay sort col.
 *   6. Sort state hydrates from URL params `?sort=` /
 *      `?sort_dir=`; invalid or incomplete pair falls back to
 *      inactive.
 *   7. `setSort` writes to URL params with `replace: true`;
 *      omits both params when the active sort is cleared.
 *
 * Pattern: source-grep guard, matching sibling
 * `test/InvoicesList.defaultUnpaidFilter.test.jsx` + the TD-93
 * `InvoicesList.td93DateRange.test.jsx`.  jsdom full mount of
 * `InvoicesList` hangs (documented in sibling vitest); source
 * assertions give O(1) coverage of the TD-95 contract.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const read = (relative) =>
  fs.readFileSync(path.resolve(process.cwd(), relative), "utf-8");

const INVOICES = read("src/pages/invoices/InvoicesList.jsx");


describe("TD-95 · InvoicesList column header sort", () => {
  // ─── 1 · <_SortableTh> mount for each of 7 columns ────────────
  it.each([
    ["Invoice #",  "invoice_number"],
    ["Invoice",    "title"],
    ["Customer",   "customer_name"],
    ["Due",        "due_date"],
    ["Amount",     "total"],
    ["Viewed",     "viewed"],
    ["Status",     "status"],
  ])("<_SortableTh> is mounted for label=%s / col=%s", (label, col) => {
    const pattern = new RegExp(
      `<_SortableTh\\s+label="${label}"\\s+col="${col}"\\s+sort=\\{sort\\}\\s+setSort=\\{setSort\\}`,
    );
    expect(INVOICES).toMatch(pattern);
  });

  // ─── 2 · 2-state cycle (operator decision #5) ─────────────────
  it("cycle is 2-state (inactive → asc → desc → asc → ...), no 3rd-click clear", () => {
    expect(INVOICES).toMatch(/if \(!active\) setSort\(\{ col, dir: "asc" \}\)/);
    expect(INVOICES).toMatch(
      /else if \(dir === "asc"\) setSort\(\{ col, dir: "desc" \}\)/,
    );
    // The resetting-to-null 3rd-click branch must be gone.
    expect(INVOICES).toMatch(/else setSort\(\{ col, dir: "asc" \}\)/);
    expect(INVOICES).not.toMatch(/setSort\(\{\s*col:\s*null,\s*dir:\s*null\s*\}\)/);
  });

  // ─── 3 · _STATUS_RANK priority chain ──────────────────────────
  it("_STATUS_RANK carries the operator-approved 7-value priority chain", () => {
    const expectedPairs = [
      ["draft",    0],
      ["sent",     1],
      ["viewed",   2],
      ["accepted", 3],
      ["partial",  4],
      ["paid",     5],
      ["past_due", 6],
    ];
    for (const [status, rank] of expectedPairs) {
      // Allow optional padding whitespace between key and colon.
      const pattern = new RegExp(`${status}:\\s*${rank}`);
      expect(INVOICES).toMatch(pattern);
    }
    // Must be `Object.freeze`-wrapped so a future caller doesn't
    // mutate the ranks mid-sort.
    expect(INVOICES).toMatch(
      /const _STATUS_RANK = Object\.freeze\(\{/,
    );
  });

  it("past_due is terminal rank — desc click surfaces it first", () => {
    // Narrow guard against a future reorder that would hide
    // past_due inside the chain.
    const m = INVOICES.match(/const _STATUS_RANK = Object\.freeze\(\{([\s\S]*?)\}\)/);
    expect(m).not.toBeNull();
    const body = (m && m[1]) || "";
    // Capture every "key: N" row and sort by rank.
    const rows = [...body.matchAll(/(\w+):\s*(\d+)/g)]
      .map(([, k, v]) => [k, Number(v)])
      .sort((a, b) => a[1] - b[1]);
    expect(rows.at(-1)?.[0]).toBe("past_due");
  });

  // ─── 4 · _viewedSortValue resolver ────────────────────────────
  it("_viewedSortValue keys on last_viewed_at || first_viewed_at || ''", () => {
    expect(INVOICES).toMatch(
      /function _viewedSortValue\(r\)\s*\{[\s\S]*?return r\.last_viewed_at \|\| r\.first_viewed_at \|\| ""/,
    );
    // view_count must NOT be the primary sort key (operator
    // decision #1).  Regression guard: the resolver body does not
    // reference view_count at all.
    const m = INVOICES.match(
      /function _viewedSortValue\(r\)\s*\{([\s\S]*?)\n\}/,
    );
    expect(m).not.toBeNull();
    expect((m && m[1]) || "").not.toMatch(/view_count/);
  });

  // ─── 5 · getVal dispatches on all 7 cols + legacy ──────────────
  it("getVal switch dispatches on all 7 operator cols + legacy has_payment_method", () => {
    const expected = [
      /case "invoice_number":\s*return Number\(r\.invoice_number \|\| 0\)/,
      /case "title":\s*return String\(r\.title \|\| ""\)\.toLowerCase\(\)/,
      /case "customer_name":\s*return String\(r\.customer_name \|\| ""\)\.toLowerCase\(\)/,
      /case "due_date":\s*return r\.due_date \|\| ""/,
      /case "total":\s*return Number\(r\.total \|\| 0\)/,
      /case "viewed":\s*return _viewedSortValue\(r\)/,
      /case "status":\s*return _STATUS_RANK\[r\.status\] \?\? 999/,
      /case "has_payment_method":\s*return r\.has_payment_method \? 1 : 0/,
    ];
    for (const p of expected) {
      expect(INVOICES).toMatch(p);
    }
  });

  // ─── 6 · URL hydrate on mount ─────────────────────────────────
  it("sort hydrates from URL params ?sort= and ?sort_dir= on mount", () => {
    expect(INVOICES).toMatch(
      /const \[sort,\s*_setSortState\]\s*=\s*useState\(\(\)\s*=>\s*\{[\s\S]*?params\.get\("sort"\)[\s\S]*?params\.get\("sort_dir"\)/,
    );
    // Invalid or incomplete pair → inactive fallback.
    expect(INVOICES).toMatch(
      /if \(!col \|\| \(dir !== "asc" && dir !== "desc"\)\) \{\s*return \{ col: null, dir: null \}/,
    );
  });

  // ─── 7 · setSort writes to URL with replace:true ──────────────
  it("setSort writes ?sort= and ?sort_dir= via setParams(_, { replace: true })", () => {
    const m = INVOICES.match(
      /const setSort = \(nextSort\) => \{([\s\S]*?)\n  \};/,
    );
    expect(m).not.toBeNull();
    const body = (m && m[1]) || "";
    expect(body).toMatch(/_setSortState\(nextSort\)/);
    expect(body).toMatch(/s\.set\("sort", nextSort\.col\)/);
    expect(body).toMatch(/s\.set\("sort_dir", nextSort\.dir\)/);
    expect(body).toMatch(/s\.delete\("sort"\)/);
    expect(body).toMatch(/s\.delete\("sort_dir"\)/);
    expect(body).toMatch(/setParams\(s,\s*\{ replace: true \}\)/);
  });

  // ─── 8 · Legacy regression — bulk-pay sort col preserved ──────
  it("legacy has_payment_method bulk-pay sort col branch still present", () => {
    expect(INVOICES).toMatch(
      /case "has_payment_method":\s*return r\.has_payment_method \? 1 : 0/,
    );
  });
});
