/**
 * Feb-2026 · Crew Phase A · New Job form crew overlay.
 *
 * Source-inspection contract test (matches the sibling
 * ``schedule-inline-edit`` shape). Asserts:
 *  - ``JobNew.jsx`` hydrates crews from ``GET /crews`` on mount.
 *  - Crew picker `<select>` is rendered behind a ``crews.length > 0``
 *    guard so tech-role sessions (which get [] from /crews) see no
 *    picker without a hard role gate in the component.
 *  - Testids ``jf-crew`` + ``jf-crew-item-{id}`` exposed.
 *  - Payload builder includes ``crew_id`` when populated on both the
 *    one-off ``/jobs`` and the recurring ``/recurring-jobs`` paths.
 *  - Initial form state seeds ``crew_id: ""`` so uncontrolled
 *    warnings never fire.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const jobNewSrc = fs.readFileSync(
  path.resolve(__dirname, "../pages/jobs/JobNew.jsx"),
  "utf8",
);

describe("JobNew · Crew overlay picker (Feb 2026 · Crew Phase A)", () => {
  it("hydrates crews from GET /crews on mount", () => {
    expect(jobNewSrc).toMatch(/api\.get\(["']\/crews["']\)/);
    // Silent failure → [] so tech-role sessions don't see errors.
    expect(jobNewSrc).toMatch(/\.catch\(\(\)\s*=>\s*setCrews\(\[\]\)\)/);
  });

  it("renders the picker behind a crews.length > 0 guard", () => {
    expect(jobNewSrc).toMatch(/crews\.length\s*>\s*0\s*\?/);
  });

  it("exposes stable testids on the picker + per-crew option", () => {
    expect(jobNewSrc).toMatch(/data-testid=["']jf-crew["']/);
    expect(jobNewSrc).toMatch(/data-testid=\{`jf-crew-item-\$\{c\.id\}`\}/);
  });

  it("seeds initial form state with crew_id: ''", () => {
    expect(jobNewSrc).toMatch(/crew_id:\s*["']["']/);
  });

  it("adds crew_id to /jobs payload only when populated", () => {
    // Uses the same guarded-add shape as property_id / technician_id
    // so back-compat with legacy callers is preserved.
    expect(jobNewSrc).toMatch(
      /if\s*\(form\.crew_id\)\s*payload\.crew_id\s*=\s*form\.crew_id/,
    );
  });

  it("adds crew_id to /recurring-jobs template payload when populated", () => {
    expect(jobNewSrc).toMatch(
      /if\s*\(form\.crew_id\)\s*tplPayload\.crew_id\s*=\s*form\.crew_id/,
    );
  });
});
