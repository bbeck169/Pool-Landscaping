/**
 * Feb-2026 · Mobile Schedule Edit sheet · assignable-user widen.
 * Parity with the web ``schedule-edit-assignable-widen`` vitest.
 */
import fs from "fs";
import path from "path";

const src = fs.readFileSync(
  path.resolve(__dirname, "../src/components/schedule/ScheduleJobEditSheet.tsx"),
  "utf8",
);

describe("ScheduleJobEditSheet · assignable-user widen", () => {
  it("suffixes admin / super_admin / manager chip labels", () => {
    expect(src).toMatch(/r\s*===\s*["']super_admin["'].*Super Admin/);
    expect(src).toMatch(/r\s*===\s*["']admin["'].*Admin/);
    expect(src).toMatch(/r\s*===\s*["']manager["'].*Manager/);
    expect(src).toMatch(/\{t\.name\}\{suffix\}/);
  });

  it("does not client-filter to role=technician (widen regression guard)", () => {
    expect(src).not.toMatch(/techs\.filter\([^)]*role\s*===\s*["']technician["']/);
  });
});
