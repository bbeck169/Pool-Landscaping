/**
 * Feb-2026 · Mobile schedule tech screen — regression guard.
 *
 * User revert: the N/M SERVICES / N/M REPAIRS countdown pills were
 * added briefly to the mobile tech schedule and then removed at the
 * user's request. This test source-checks the schedule screen to
 * ensure the pills stay unmounted so a future refactor doesn't
 * silently re-add them. The shared classifier + ``<JobCountPill>``
 * component remain intact for potential future reuse.
 */
import fs from "fs";
import path from "path";


const CALENDAR_PATH = path.resolve(
  __dirname, "..", "app", "(app)", "schedule", "calendar.tsx",
);


describe("Mobile tech schedule · pills-removal regression guard", () => {
  const src = fs.readFileSync(CALENDAR_PATH, "utf-8");

  test("does NOT import JobCountPill", () => {
    expect(src).not.toMatch(/from ["']@\/components\/JobCountPill["']/);
    expect(src).not.toMatch(/import\s+JobCountPill\b/);
  });

  test("does NOT import computePillCounts from lib/jobCategory", () => {
    expect(src).not.toMatch(/computePillCounts/);
    expect(src).not.toMatch(/from ["']@\/lib\/jobCategory["']/);
  });

  test("does NOT render the schedule-count-pills container or the individual pill testIDs", () => {
    expect(src).not.toMatch(/schedule-count-pills/);
    expect(src).not.toMatch(/schedule-pill-services/);
    expect(src).not.toMatch(/schedule-pill-repairs/);
  });
});
