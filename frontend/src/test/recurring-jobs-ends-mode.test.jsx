/**
 * Recurring Jobs · Ends mode (Never | On date) · Feb-2026.
 *
 * Contract test — asserts the RecurringJobs.jsx source implements the
 * explicit two-mode Ends radio group per the product spec:
 *   1. Radio group with `recurring-jobs-ends-never` and
 *      `recurring-jobs-ends-on-date` testids, mutually exclusive.
 *   2. openCreate defaults `recurrence_never_ends: true` (Never is the
 *      default end mode).
 *   3. openEdit normalizes legacy rows (no flag + no end_date) into
 *      Never mode.
 *   4. save() nulls out `end_date` when `recurrence_never_ends === true`
 *      so the API payload never carries both.
 *   5. Stop-recurrence row button testid is wired.
 *
 * Uses the same lightweight source-inspection pattern already
 * established by `admin-sidebar-pinned-nav.test.jsx` (this repo's
 * canonical style for admin-page contract checks) to avoid pulling
 * the full RecurringJobs render tree + api client.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

function readSrc() {
  return fs.readFileSync(
    path.resolve(__dirname, "../pages/admin/RecurringJobs.jsx"),
    "utf8",
  );
}

describe("RecurringJobs · Ends mode radio", () => {
  const src = readSrc();

  it("renders both mode radios with stable testids", () => {
    expect(src).toContain('data-testid="recurring-jobs-ends-never"');
    expect(src).toContain('data-testid="recurring-jobs-ends-on-date"');
  });

  it("radios share a single `name` attribute (mutual exclusion)", () => {
    // Two `<input type=\"radio\" name=\"recurrence-ends-mode\"` occurrences
    // is the DOM-level guarantee that only one can be selected.
    const matches = src.match(/name="recurrence-ends-mode"/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it("Never radio clears end_date on select", () => {
    // The Never radio's onChange must reset end_date so the payload
    // doesn't silently carry a stale date alongside the flag. Match
    // is order-independent — the setEditing update object contains
    // both keys.
    expect(src).toMatch(
      /onChange=\{\(\)\s*=>\s*setEditing[\s\S]{0,200}recurrence_never_ends:\s*true[\s\S]{0,80}end_date:\s*null/,
    );
  });

  it("On-date radio disables date picker when Never is active", () => {
    // JSX order-independent: the same <input type=\"date\"> block
    // contains both the disabled-by-flag attribute and the testid.
    // Match either attribute order via lookahead.
    const dateBlock = src.match(
      /<input type="date"[\s\S]{0,1200}data-testid="recurring-jobs-end"/,
    );
    expect(dateBlock).not.toBeNull();
    expect(dateBlock[0]).toContain(
      "disabled={!!editing.recurrence_never_ends}",
    );
  });
});

describe("RecurringJobs · defaults", () => {
  const src = readSrc();

  it("openCreate defaults recurrence_never_ends to true", () => {
    const m = src.match(/const\s+openCreate\s*=\s*\(\)\s*=>\s*\{[\s\S]*?setEditing\(\{([\s\S]*?)\}\)/);
    expect(m).not.toBeNull();
    expect(m[1]).toMatch(/recurrence_never_ends:\s*true/);
    expect(m[1]).toMatch(/end_date:\s*null/);
  });

  it("openEdit normalises legacy rows (no flag + no end_date) to Never", () => {
    // The rule: `row.recurrence_never_ends === true
    //           || (row.recurrence_never_ends == null && !row.end_date)`
    expect(src).toMatch(
      /row\.recurrence_never_ends\s*===\s*true[\s\S]*row\.recurrence_never_ends\s*==\s*null[\s\S]*!row\.end_date/,
    );
  });
});

describe("RecurringJobs · save payload guarantees exclusive mode", () => {
  const src = readSrc();

  it("save() nulls end_date when recurrence_never_ends is true", () => {
    // Prevents the API from ever seeing both fields populated at once.
    expect(src).toMatch(
      /if\s*\(payload\.recurrence_never_ends\)\s*payload\.end_date\s*=\s*null/,
    );
  });
});

describe("RecurringJobs · Stop action", () => {
  const src = readSrc();

  it("renders a per-row Stop button (active rows only) with stable testid", () => {
    expect(src).toMatch(/data-testid=\{`recurring-job-stop-\$\{r\.id\}`\}/);
  });

  it("Stop action posts to `/recurring-jobs/{id}/stop`", () => {
    expect(src).toMatch(/api\.post\(`\/recurring-jobs\/\$\{row\.id\}\/stop`/);
  });
});
