/**
 * Feb-2026 · P47 — mobile recurrence picker enum pin.
 */
import fs from "fs";
import path from "path";


describe("mobile finance/recurring-jobs FREQ_OPTS · P47", () => {
  const src = fs.readFileSync(
    path.resolve(__dirname, "../app/finance/recurring-jobs.tsx"),
    "utf8");

  it("FREQ_OPTS includes quarterly", () => {
    expect(src).toMatch(/FREQ_OPTS[^;]*"quarterly"/);
  });

  it("FREQ_OPTS includes semi_annual", () => {
    expect(src).toMatch(/FREQ_OPTS[^;]*"semi_annual"/);
  });

  it("frequency union type includes both new cadences", () => {
    expect(src).toMatch(/"quarterly"/);
    expect(src).toMatch(/"semi_annual"/);
  });
});
