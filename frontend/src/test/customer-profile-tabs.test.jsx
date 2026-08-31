/**
 * Phase F3.5 · Feb-2026 — Customer profile perf: the detail load
 * fetches ONE customer's jobs via `?customer_id=` (not tenant-wide),
 * and does not run a client-side `.filter` over the full tenant list.
 *
 * This is a source-shape test: we assert against the CustomerDetail.jsx
 * file body so any future regression that reintroduces the tenant-wide
 * `api.get("/jobs")` fetch fails loudly. Structurally the F3 pipeline
 * has ~5 similar file-body tests (phase22-mobile-schedule-gates.test.jsx,
 * schedule-inline-edit.test.jsx, phase41-2-admin-list-page-primitive.test.jsx).
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/customers/CustomerDetail.jsx"),
  "utf-8",
);

describe("CustomerDetail · F3.5 perf contract", () => {
  it("fetches only THIS customer's jobs via `?customer_id=…`", () => {
    // The customer-scoped call MUST be present.
    expect(SRC).toMatch(
      /api\.get\(`\/jobs\?customer_id=\$\{encodeURIComponent\(id\)\}`\)/,
    );
  });

  it("must NOT re-introduce the tenant-wide `api.get(\"/jobs\")` load",
     () => {
    // Bare tenant-wide fetch — the F3.5 regression trap.
    expect(SRC).not.toMatch(/api\.get\("\/jobs"\)/);
  });

  it("does not client-filter jobs by customer_id after transport", () => {
    // The old pattern was:
    //   (allJobs || []).filter((j) => j.customer_id === id)
    // Match against the specific ``(allJobs || []).filter`` idiom used
    // in the pre-F3.5 loader — a comment mentioning the pattern is OK.
    expect(SRC).not.toMatch(/\(allJobs\s*\|\|\s*\[\]\)\.filter/);
  });
});
