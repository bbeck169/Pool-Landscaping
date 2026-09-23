/**
 * Phase P37 · Feb-2026 — CustomerDetail jobs history pagination +
 * virtualization contract tests.
 *
 * Source-lint style — the same pattern used by
 * ``customer-detail-action-row.test.jsx`` — because a full
 * ``<CustomerDetail />`` mount pulls in ~25 dependency components
 * (equipment, tasks, timeline, portal-access, subscriptions, …)
 * that don't need to be exercised to lock the P37 contract. The
 * assertions target the exact P37 source landmarks so a future
 * refactor that regresses ANY of the four contract points fails
 * loudly:
 *
 *   1. ``_P37_JOBS_PAGE = 50`` — initial page size (was 10 in the
 *      pre-P37 brief; refined to 50 for the 900-job scale).
 *   2. ``react-window`` ``<List>`` wraps the jobs history render
 *      (windowing).
 *   3. ``JobHistoryRow`` is a memoized component with an explicit
 *      equality function on ``id`` / ``status`` / ``updated_at`` /
 *      ``title`` / ``technician_name`` / ``scheduled_date``.
 *   4. Server-side pagination — fetches use
 *      ``limit=50&offset=<jobs.length>&sort=scheduled_date_desc``.
 *
 * Test IDs preserved: ``cd-jobs-list``, ``cd-job-{id}``,
 * ``cd-reopen-{id}``, ``cd-jobs-load-more``. A new
 * ``cd-job-row-{id}`` wrapper is added for row-level DOM
 * addressability under the windowed layout.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";


const PAGE_PATH = resolve(
  __dirname,
  "../pages/customers/CustomerDetail.jsx",
);
const pageSrc = readFileSync(PAGE_PATH, "utf8");


describe("P37 · CustomerDetail · jobs history contract", () => {
  it("1) initial page size is 50 (bumped from 10 per the refinement)", () => {
    expect(pageSrc).toMatch(/const\s+_P37_JOBS_PAGE\s*=\s*50\b/);
  });

  it("2) uses react-window <List> for windowing", () => {
    expect(pageSrc).toMatch(/from\s+["']react-window["']/);
    expect(pageSrc).toMatch(/import\s+\{\s*List\s*\}\s+from\s+["']react-window["']/);
    expect(pageSrc).toMatch(/<List\b[\s\S]*?rowComponent=\{JobHistoryRow\}/);
    // Overscan + row height + row key are all set.
    expect(pageSrc).toMatch(/overscanCount=\{8\}/);
    expect(pageSrc).toMatch(/rowHeight=\{_P37_JOB_ROW_HEIGHT\}/);
  });

  it("3) JobHistoryRow is React.memo'd with an explicit equality fn", () => {
    // Component is memoized.
    expect(pageSrc).toMatch(/const\s+JobHistoryRow\s*=\s*React\.memo\(/);
    // Equality function inspects id + status + updated_at + title +
    // technician_name + scheduled_date. This is the exact contract
    // the P37 refinement asked for.
    expect(pageSrc).toMatch(/pj\.id\s*===\s*nj\.id/);
    expect(pageSrc).toMatch(/pj\.status\s*===\s*nj\.status/);
    expect(pageSrc).toMatch(/pj\.updated_at\s*===\s*nj\.updated_at/);
    expect(pageSrc).toMatch(/pj\.title\s*===\s*nj\.title/);
    expect(pageSrc).toMatch(/pj\.technician_name\s*===\s*nj\.technician_name/);
    expect(pageSrc).toMatch(/pj\.scheduled_date\s*===\s*nj\.scheduled_date/);
    // reopenJob handler stability is part of the equality check
    // (parent wraps with useCallback so the identity is stable).
    expect(pageSrc).toMatch(/prev\.reopenJob\s*===\s*next\.reopenJob/);
    // Parent wraps ``reopenJob`` with useCallback.
    expect(pageSrc).toMatch(
      /const\s+reopenJob\s*=\s*useCallback\(async\s*\(jid\)\s*=>/,
    );
  });

  it("4) server-side pagination — initial fetch uses limit=50 offset=0 sort=desc", () => {
    // Initial fetch (inside ``load``).
    expect(pageSrc).toMatch(
      /\/jobs\?customer_id=\$\{encodeURIComponent\(id\)\}[\s\S]*?limit=\$\{_P37_JOBS_PAGE\}&offset=0[\s\S]*?sort=scheduled_date_desc/,
    );
    // Load-more fetch uses offset = jobs.length.
    expect(pageSrc).toMatch(
      /limit=\$\{_P37_JOBS_PAGE\}&offset=\$\{jobs\.length\}/,
    );
  });

  it("5) row wrapper testid preserved + Load-more button testid preserved", () => {
    expect(pageSrc).toMatch(/data-testid=\{`cd-job-row-\$\{j\.id\}`\}/);
    expect(pageSrc).toMatch(/data-testid=\{`cd-job-\$\{j\.id\}`\}/);
    expect(pageSrc).toMatch(/data-testid=\{`cd-reopen-\$\{j\.id\}`\}/);
    expect(pageSrc).toMatch(/data-testid="cd-jobs-load-more"/);
  });

  it("6) load-more state — busy flag + hasMore flag exist", () => {
    expect(pageSrc).toMatch(/const\s+\[jobsLoadingMore,\s*setJobsLoadingMore\]/);
    expect(pageSrc).toMatch(/const\s+\[jobsHasMore,\s*setJobsHasMore\]/);
    expect(pageSrc).toMatch(/setJobsHasMore\(firstPage\.length\s*>=\s*_P37_JOBS_PAGE\)/);
    expect(pageSrc).toMatch(/setJobsHasMore\(chunk\.length\s*>=\s*_P37_JOBS_PAGE\)/);
  });

  it("7) container height bounded — max-h 60vh so windowing has a viewport", () => {
    expect(pageSrc).toMatch(/maxHeight:\s*["']60vh["']/);
  });

  it("8) row height constant is a fixed pixel value (fixed-size windowing)", () => {
    expect(pageSrc).toMatch(/const\s+_P37_JOB_ROW_HEIGHT\s*=\s*\d+;/);
  });
});
