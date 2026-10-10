/**
 * Schedule surface · job-level ``notes`` · Feb-2026.
 *
 * Source-inspection contract test — matches the sibling
 * ``routes-enriched-names`` style (avoids booting the 1700-line
 * ``CalendarSchedule`` tree). Asserts the shared
 * ``<JobNotesCallout>`` (rendered by ``CalendarSchedule`` +
 * ``TodaySchedule`` + mobile) still emits the expected
 * ``job-{id}-notes`` testid, the 2-line clamp class, and the
 * truncation ellipsis behaviour.
 *
 * Feb-2026 · Notes visibility polish moved the render block out of
 * ``CalendarSchedule.jsx`` into a shared component so web + mobile
 * stay visually consistent. The contract lives with the component now.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const src = fs.readFileSync(
  path.resolve(__dirname, "../components/schedule/JobNotesCallout.jsx"),
  "utf8",
);
const calendarSrc = fs.readFileSync(
  path.resolve(__dirname, "../pages/schedule/CalendarSchedule.jsx"),
  "utf8",
);

describe("Schedule · job-level notes", () => {
  it("renders a ``job-{id}-notes`` row from the note prop (2-line clamp)", () => {
    // Must render with the exact testid contract, and ``line-clamp-2``
    // for the 2-line ellipsis when not expanded.
    expect(src).toMatch(/data-testid=\{`job-\$\{jobId\}-notes`\}/);
    expect(src).toMatch(/line-clamp-2/);
  });

  it("guards on non-empty ``note`` (no empty row rendered)", () => {
    // The render block MUST live inside a truthy-guard so empty / null /
    // whitespace-only values skip the row entirely. Component itself
    // returns ``null`` when both notes are empty.
    expect(src).toMatch(
      /const\s+jobNote\s*=\s*\(note\s*&&\s*String\(note\)\.trim\(\)\)\s*\?/,
    );
    expect(src).toMatch(/if\s*\(!jobNote\s*&&\s*!custNote(?:\s*&&[^)]*)?\)\s*return\s+null/);
  });

  it("surfaces the truncation ellipsis when the server flags ``notes_truncated``", () => {
    // Server caps at 500 chars and sends ``notes_truncated=true`` when
    // the original was longer — UI must append "…" only in that case.
    expect(src).toMatch(/truncated\s*\?\s*"…"\s*:\s*""/);
  });

  it("CalendarSchedule wires JobNotesCallout instead of the old inline block", () => {
    // Guard: ensure the shared component is actually used on the
    // primary schedule surface after the Feb-2026 visibility polish.
    expect(calendarSrc).toMatch(/JobNotesCallout/);
  });
});
