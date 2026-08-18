/**
 * Feb-2026 · Mobile Schedule Select-All affordance + role widening.
 *
 * Source-inspection contract:
 *   1. isAdmin includes manager on mobile (parity with web).
 *   2. Select-all + Clear pills render only for admin+ and are wired
 *      to selectAllInView / clearSelection.
 *   3. selectAllInView drops the current visible ``jobs`` into
 *      ``checked``.
 */
import fs from "fs";
import path from "path";

const src = fs.readFileSync(
  path.resolve(__dirname, "../app/(app)/schedule/calendar.tsx"),
  "utf8",
);

describe("Mobile schedule · Select-All affordance", () => {
  it("isAdmin includes manager", () => {
    expect(src).toMatch(
      /isAdmin\s*=\s*role\s*===\s*["']admin["']\s*\|\|\s*role\s*===\s*["']super_admin["']\s*\|\|\s*role\s*===\s*["']manager["']/,
    );
  });

  it("selectAllInView bulk-picks the entire visible ``jobs`` list", () => {
    expect(src).toMatch(
      /selectAllInView\s*=\s*\(\)\s*=>\s*\{\s*setChecked\(new Set\(jobs\.map\(\(j\)\s*=>\s*j\.id\)\)\)/,
    );
  });

  it("Select-all pill renders when admin+ and jobs list is non-empty", () => {
    expect(src).toMatch(/testID=["']grid-bulk-select-all["']/);
    expect(src).toMatch(
      /isAdmin\s*&&\s*onSelectAllInView\s*\?[\s\S]{0,500}testID=["']grid-bulk-select-all["']/,
    );
    // Disabled state when zero visible jobs.
    expect(src).toMatch(/disabled=\{!jobs\.length\}/);
  });

  it("Clear pill renders only when admin+ AND checked.size > 0", () => {
    expect(src).toMatch(/testID=["']grid-bulk-clear-selection["']/);
    expect(src).toMatch(
      /isAdmin\s*&&\s*onClearSelection\s*&&\s*checked\.size\s*>\s*0/,
    );
  });

  it("plumbs onSelectAllInView + onClearSelection through GridView", () => {
    expect(src).toMatch(/onSelectAllInView=\{isAdmin\s*\?\s*selectAllInView\s*:\s*undefined\}/);
    expect(src).toMatch(/onClearSelection=\{isAdmin\s*\?\s*clearSelection\s*:\s*undefined\}/);
  });
});
