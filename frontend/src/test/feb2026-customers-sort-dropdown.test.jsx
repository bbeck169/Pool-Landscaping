/**
 * Feb-2026 · Customers list — Sort dropdown.
 *
 * SUPERSEDED BY K49 (Feb-2026).
 *
 * The original file asserted the pre-K49 contract:
 *   • Default sort = ``created_desc`` (Newest → Oldest).
 *   • Sort choice persisted to
 *     ``localStorage['customers.sortBy']`` and read back on next
 *     mount.
 *
 * K49 explicitly retired both behaviours:
 *   • New default sort = ``last_name_asc`` (Last Name A-Z).
 *   • ``localStorage`` persistence dropped so the dropdown obeys the
 *     K40 "reset filter state on every mount" rule for the
 *     Customers page. Explicit ``?sort=`` URL params still win
 *     (bookmark exception).
 *
 * The live contract is now covered by
 * ``src/test/k49-customers-filter-defaults.test.jsx``. This file is
 * kept as a stub so the historical filename shows up in `git blame`
 * with the supersession pointer.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

describe("Feb-2026 sort dropdown suite · SUPERSEDED BY K49", () => {
  it("points at the K49 replacement test file", () => {
    const p = path.resolve(
      process.cwd(),
      "src/test/k49-customers-filter-defaults.test.jsx",
    );
    expect(fs.existsSync(p)).toBe(true);
  });
});
