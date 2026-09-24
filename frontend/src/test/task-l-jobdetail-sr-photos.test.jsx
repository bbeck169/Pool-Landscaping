/**
 * Task L+P · Commit 5 · Feb-2026 — JobDetail SR photos section.
 *
 * Pins the source-body contract on
 * ``frontend/src/pages/jobs/JobDetail.jsx``:
 *   • New "Service Report Photos" section rendered from
 *     ``detail.service_report_photos`` (from Commit-5 backend
 *     aggregator).
 *   • Section suppressed entirely when the array is empty.
 *   • Grid layout matches the legacy Photos section
 *     (grid-cols-3 md:grid-cols-4).
 *   • New independent lightbox with its own testid
 *     ``job-detail-sr-photos-lightbox`` — does NOT reuse the
 *     legacy ``jd-lightbox`` because the two grids index
 *     independent arrays (``job.photos`` vs
 *     ``detail.service_report_photos``).
 *   • Legacy Photos + Lightbox contracts preserved verbatim.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/jobs/JobDetail.jsx"),
  "utf-8",
);

describe("Task L+P · Commit 5 — JobDetail SR photos section", () => {
  it("declares an independent srLightbox state hook", () => {
    // Separate from the pre-existing ``lightbox`` state so the
    // two grids can be opened/closed independently.
    expect(SRC).toMatch(
      /const\s+\[srLightbox,\s*setSrLightbox\]\s*=\s*useState\(null\)/
    );
  });

  it("renders the SR section only when detail.service_report_photos has items", () => {
    // Conditional guard suppresses the entire section (not just
    // an empty header) when the array is empty.
    expect(SRC).toMatch(
      /\(detail\?\.service_report_photos\s*\|\|\s*\[\]\)\.length\s*\?\s*\(/
    );
    expect(SRC).toMatch(/data-testid="job-detail-sr-photos"/);
    // Section header copy exactly.
    expect(SRC).toMatch(/Service Report Photos/);
  });

  it("uses the same grid layout as the legacy Photos section", () => {
    // The SR grid uses ``grid-cols-3 md:grid-cols-4`` — same as
    // the legacy Photos section above it.  We assert both grids
    // exist in the file so the styles stay in lock-step.
    const gridPattern = /grid\s+grid-cols-3\s+md:grid-cols-4\s+gap-2/g;
    const matches = SRC.match(gridPattern) || [];
    // Two grids: legacy Photos + new SR Photos.
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it("emits job-detail-sr-photo-{i} testid on every tile", () => {
    expect(SRC).toMatch(/data-testid=\{`job-detail-sr-photo-\$\{i\}`\}/);
  });

  it("SR tile click sets srLightbox to the tile's index", () => {
    // Click-to-lightbox: tile onClick sets the new independent
    // srLightbox state (NOT the legacy setLightbox).
    expect(SRC).toMatch(
      /onClick=\{\(\)\s*=>\s*setSrLightbox\(i\)\}/
    );
  });

  it("renders the SR lightbox independently from jd-lightbox", () => {
    // Own testid so tester scripts can target it independently.
    expect(SRC).toMatch(/data-testid="job-detail-sr-photos-lightbox"/);
    // Conditional guard uses srLightbox + service_report_photos.
    expect(SRC).toMatch(
      /srLightbox\s*!==\s*null\s*&&\s*\(detail\?\.service_report_photos/
    );
    // Lightbox img resolves from detail.service_report_photos[srLightbox].
    expect(SRC).toMatch(
      /detail\.service_report_photos\[srLightbox\]/
    );
  });

  it("preserves the legacy Photos section testids verbatim", () => {
    // These testids are pre-Task-L+P; any drift is a regression.
    expect(SRC).toMatch(/data-testid="jd-photos"/);
    expect(SRC).toMatch(/data-testid=\{`jd-photo-\$\{i\}`\}/);
    expect(SRC).toMatch(/data-testid="jd-lightbox"/);
  });

  it("preserves other JobDetail testids that surrounded the edit site", () => {
    // Representative sample — protects against unrelated
    // testid drift when editing this file.  Note: some elements
    // use the shadcn ``testid=`` prop (no ``data-`` prefix);
    // regex accepts both shapes.
    expect(SRC).toMatch(/testid="jd-confirm-delete"/);
    expect(SRC).toMatch(/data-testid="jd-new-scheduled-job-modal"/);
  });
});
