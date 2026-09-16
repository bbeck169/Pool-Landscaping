/**
 * Phase M5 — VisitRecapModal removed from checklist screen.
 *
 * Tests:
 *  1. VisitRecapModal import is removed from checklist.tsx.
 *  2. recapOpen state is removed from checklist.tsx.
 *  3. recapCustomer state is removed from checklist.tsx.
 *  4. doCloseJob success branch shows "Job closed" Alert directly.
 *  5. doCloseJob success navigates to /(app)/schedule/calendar.
 *  6. Dirty guard is cleared before navigation (dirtyRef.current = false).
 *  7. VisitRecapModal shared file still exists (not deleted).
 */
import * as fs from "fs";
import * as path from "path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../app/job/[id]/checklist.tsx"),
  "utf-8",
);

describe("Phase M5 — VisitRecapModal removed from checklist", () => {
  it("VisitRecapModal import is removed", () => {
    // Only a comment reference should remain, no actual import
    expect(SRC).not.toMatch(/^import .* from .*VisitRecapModal/m);
  });

  it("recapOpen state is removed", () => {
    expect(SRC).not.toContain("recapOpen");
  });

  it("recapCustomer state is removed", () => {
    expect(SRC).not.toContain("recapCustomer");
  });

  it('doCloseJob success shows "Job closed" Alert directly', () => {
    // The Alert.alert("Job closed", ...) call should exist in doCloseJob
    expect(SRC).toContain('Alert.alert("Job closed"');
    // Should include "Report submitted" text in the alert body
    expect(SRC).toContain("Report submitted${invId}");
  });

  it("doCloseJob success navigates to schedule", () => {
    expect(SRC).toContain('router.replace("/(app)/schedule/calendar")');
  });

  it("dirty guard is cleared before navigation on success", () => {
    // dirtyRef.current = false is set before the Alert
    const successBlock = SRC.slice(
      SRC.indexOf("recap dialog removed (Phase M5)"),
      SRC.indexOf("recap dialog removed (Phase M5)") + 500,
    );
    expect(successBlock).toContain("dirtyRef.current = false");
    expect(successBlock).toContain("setIsDirtyForGuard(false)");
  });

  it("VisitRecapModal shared file still exists", () => {
    const sharedPath = path.resolve(
      __dirname,
      "../src/components/checklist/VisitRecapModal.tsx",
    );
    expect(fs.existsSync(sharedPath)).toBe(true);
  });

  it("usePreventRemove no longer references recapOpen", () => {
    // The guard condition should just be isDirtyForGuard, not && !recapOpen
    expect(SRC).not.toContain("!recapOpen");
    expect(SRC).toContain("usePreventRemove(isDirtyForGuard,");
  });
});
