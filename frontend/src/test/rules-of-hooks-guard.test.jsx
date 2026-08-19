/**
 * Feb-2026 · Regression guard for BUG 1 (P0 build-breaker).
 *
 * The AdminTopBar component regressed twice with a rules-of-hooks
 * violation where a null-guard was placed BEFORE the `useState` /
 * `useEffect` hook calls. Under strict eslint (react-scripts /
 * `eslint-plugin-react-hooks`) this crashes the mobile build with:
 *
 *   Line 328:23  React Hook "React.useState" is called conditionally
 *   Line 330:3   React Hook "React.useEffect" is called conditionally
 *
 * This suite shells out to `npx eslint` (the same binary the build
 * uses) rather than loading the flat config via the ESLint API in
 * a jsdom env — the flat config imports `eslint-plugin-unused-imports`
 * which requires a real file URL and breaks under vitest jsdom.
 */
import { describe, it, expect } from "vitest";
import path from "path";
import { spawnSync } from "child_process";


const ROOT = path.resolve(__dirname, "../..");
const FILES = [
  "src/layouts/AdminTopBar.jsx",
  "src/layouts/AppLayout.jsx",
];


describe("Rules-of-hooks regression guard — layout files", () => {
  it("AdminTopBar.jsx + AppLayout.jsx have zero eslint errors", () => {
    const r = spawnSync(
      "npx",
      ["--yes", "eslint", "--max-warnings=0", ...FILES],
      { cwd: ROOT, encoding: "utf8" },
    );
    if (r.status !== 0) {
      throw new Error(
        `eslint exit=${r.status}\nstdout:\n${r.stdout}\nstderr:\n${r.stderr}`,
      );
    }
    expect(r.status).toBe(0);
  }, 60000);
});
