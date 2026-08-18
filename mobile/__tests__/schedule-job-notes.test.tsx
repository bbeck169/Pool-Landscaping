/**
 * Mobile Schedule surface · job-level ``notes`` · Feb-2026.
 *
 * Source-inspection contract test — matches the sibling web
 * ``schedule-job-notes`` shape. Avoids the RN-testing-library
 * boot for a 1094-line calendar tree with 30+ mocks.
 */
import fs from "fs";
import path from "path";

const src = fs.readFileSync(
  path.resolve(__dirname, "../app/(app)/schedule/calendar.tsx"),
  "utf8",
);

describe("Mobile schedule · job-level notes", () => {
  it("renders a ``job-${id}-notes`` <Text> from ``job.notes`` with numberOfLines=2", () => {
    expect(src).toMatch(/testID=\{`job-\$\{job\.id\}-notes`\}/);
    // The block MUST use ``numberOfLines={2}`` for the RN native 2-line
    // ellipsis, mirroring the web ``line-clamp-2``.
    expect(src).toMatch(
      /testID=\{`job-\$\{job\.id\}-notes`\}[\s\S]{0,400}numberOfLines=\{2\}|numberOfLines=\{2\}[\s\S]{0,400}testID=\{`job-\$\{job\.id\}-notes`\}/,
    );
  });

  it("guards on non-empty ``job.notes`` — empty notes → row is not rendered", () => {
    expect(src).toMatch(
      /job\.notes\s*&&\s*String\(job\.notes\)\.trim\(\)\s*\?[\s\S]{0,600}testID=\{`job-\$\{job\.id\}-notes`\}/,
    );
  });

  it("appends the truncation ellipsis when ``notes_truncated`` is set", () => {
    expect(src).toMatch(/job\.notes_truncated\s*\?\s*"…"\s*:\s*""/);
  });
});
