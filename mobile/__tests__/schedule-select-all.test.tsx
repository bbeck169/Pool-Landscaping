/**
 * Feb-2026 · Mobile Schedule Select-All affordance + role widening.
 * Updated Phase P18: bulk actions moved into dropdown menu.
 *
 * Source-inspection contract:
 *   1. isAdmin includes manager on mobile (parity with web).
 *   2. Select-all + Clear render for admin+ and are wired
 *      to selectAllInView / clearSelection.
 *   3. selectAllInView drops the current visible ``jobs`` into
 *      ``checked``.
 *   4. All 6 actions are inside the dropdown with correct testIDs.
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

  it("Select-all is wired in the Actions dropdown with disabled state", () => {
    // select-all action key present in dropdown config
    expect(src).toMatch(/key:\s*["']select-all["']/);
    // disabled when no jobs
    expect(src).toMatch(/disabled:\s*!jobs\.length/);
  });

  it("Clear button renders when checked.size > 0", () => {
    expect(src).toMatch(/testID=["']grid-bulk-clear-selection["']/);
    expect(src).toMatch(/checked\.size\s*>\s*0/);
  });

  it("plumbs onSelectAllInView + onClearSelection through GridView", () => {
    expect(src).toMatch(/onSelectAllInView=\{isAdmin\s*\?\s*selectAllInView\s*:\s*undefined\}/);
    expect(src).toMatch(/onClearSelection=\{isAdmin\s*\?\s*clearSelection\s*:\s*undefined\}/);
  });

  it("Actions trigger button gated to canWrite users", () => {
    expect(src).toMatch(/testID=["']grid-actions-trigger["']/);
    expect(src).toMatch(/canWrite\s*\?/);
  });

  it("all 6 actions present in the dropdown", () => {
    // Actions defined via key array — verify keys exist
    expect(src).toMatch(/key:\s*["']select-all["']/);
    expect(src).toMatch(/key:\s*["']complete["']/);
    expect(src).toMatch(/key:\s*["']move["']/);
    expect(src).toMatch(/key:\s*["']delete["']/);
    expect(src).toMatch(/key:\s*["']assign["']/);
    expect(src).toMatch(/key:\s*["']rearrange["']/);
    // Dynamic testID from key
    expect(src).toMatch(/testID=\{`grid-action-\$\{act\.key\}`\}/);
  });
});
