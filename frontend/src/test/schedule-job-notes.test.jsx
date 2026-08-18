/**
 * Schedule surface · job-level ``notes`` · Feb-2026.
 *
 * Source-inspection contract test — matches the sibling
 * ``routes-enriched-names`` style (avoids booting the 1700-line
 * ``CalendarSchedule`` tree). Asserts the JobCard grid renders a
 * ``job-{id}-notes`` row when ``j.notes`` is non-empty, and that the
 * render is guarded so an empty ``notes`` value skips the row entirely.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const src = fs.readFileSync(
  path.resolve(__dirname, "../pages/schedule/CalendarSchedule.jsx"),
  "utf8",
);

describe("Schedule · job-level notes", () => {
  it("renders a ``job-{id}-notes`` row from ``j.notes`` (2-line clamp)", () => {
    // Must render with the exact testid contract, muted color, and
    // ``line-clamp-2`` for the 2-line ellipsis.
    expect(src).toMatch(/data-testid=\{`job-\$\{j\.id\}-notes`\}/);
    expect(src).toMatch(/line-clamp-2/);
  });

  it("guards on non-empty ``j.notes`` (no empty row rendered)", () => {
    // The render block MUST live inside a ``(j.notes && ...)`` guard so
    // empty / null / whitespace-only values skip the row entirely.
    expect(src).toMatch(
      /\(j\.notes\s*&&\s*String\(j\.notes\)\.trim\(\)\)\s*\?[\s\S]{0,600}data-testid=\{`job-\$\{j\.id\}-notes`\}/,
    );
  });

  it("surfaces the truncation ellipsis when the server flags ``notes_truncated``", () => {
    // Server caps at 500 chars and sends ``notes_truncated=true`` when
    // the original was longer — UI must append "…" only in that case.
    expect(src).toMatch(/j\.notes_truncated\s*\?\s*"…"\s*:\s*""/);
  });
});
