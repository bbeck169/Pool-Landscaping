/**
 * Mobile Schedule surface · job-level ``notes`` · Feb-2026.
 *
 * Source-inspection contract test — matches the sibling web
 * ``schedule-job-notes`` shape. Avoids the RN-testing-library
 * boot for a 1094-line calendar tree with 30+ mocks.
 *
 * Phase Hygiene B · Feb-2026 — the render of the notes row was
 * extracted from ``calendar.tsx`` into a shared
 * ``JobNotesCallout`` component. The testIDs the contract locks
 * against (``job-${id}-notes``, numberOfLines=2, empty guard,
 * truncation ellipsis) now live inside that component. Retarget
 * the file we read + the parametrised testid variable name.
 */
import fs from "fs";
import path from "path";

const src = fs.readFileSync(
  path.resolve(
    __dirname,
    "../src/components/schedule/JobNotesCallout.tsx",
  ),
  "utf8",
);

describe("Mobile schedule · job-level notes", () => {
  it("renders a ``job-${id}-notes`` <Text> from the note prop with numberOfLines=2", () => {
    expect(src).toMatch(/testID=\{`job-\$\{jobId\}-notes`\}/);
    // The block MUST use ``numberOfLines={clampLines}`` where clampLines
    // is set to 2 in the non-expanded branch — the RN native
    // 2-line ellipsis, mirroring the web ``line-clamp-2``.
    expect(src).toMatch(/clampLines\s*=\s*expanded\s*\?\s*undefined\s*:\s*2/);
    // In the current implementation numberOfLines is emitted BEFORE
    // the testID on the same <Text>. Match either ordering to keep
    // the contract robust across future re-arrangements.
    expect(src).toMatch(
      /numberOfLines=\{clampLines\}[\s\S]{0,120}testID=\{`job-\$\{jobId\}-notes`\}|testID=\{`job-\$\{jobId\}-notes`\}[\s\S]{0,120}numberOfLines=\{clampLines\}/,
    );
  });

  it("guards on non-empty ``note`` — empty notes → row is not rendered", () => {
    // JobNotesCallout early-returns when neither ``note`` nor
    // ``customerNote`` is set. The guard uses local ``jobNote`` /
    // ``custNote`` bindings (normalized-and-trimmed versions of the
    // ``note`` / ``customerNote`` props) — assert the normalized
    // guard shape.
    expect(src).toMatch(/if\s*\(!jobNote\s*&&\s*!custNote\s*&&\s*!pool\s*&&\s*!landscape\)\s*return\s+null;/);
  });

  it("appends the truncation ellipsis when ``truncated`` prop is set", () => {
    expect(src).toMatch(/truncated\s*\?\s*"…"\s*:\s*""/);
  });
});
