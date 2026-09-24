/**
 * Task L+P · Commit 6 · Feb-2026 — JobsList Photos column +
 * JobPhotoThumbs unit tests.
 *
 * Coverage:
 *   • JobPhotoThumbs component (0 / 1 / 2 / 3 / 5-photo scenarios,
 *     +N badge count, empty state em-dash, onError placeholder
 *     swap, testid contract).
 *   • JobsList integration (Photos column header exists, no
 *     source-body drift on the pre-existing testids).
 */
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { describe, it, expect } from "vitest";
import { render, fireEvent, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { JobPhotoThumbs } from "../components/jobs/JobPhotoThumbs";

const SRC_JOBSLIST = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/jobs/JobsList.jsx"),
  "utf-8",
);

const _urls = (n) =>
  Array.from({ length: n }, (_, i) => `/api/public/job-photo/j1/p${i}/thumb`);
const _ids = (n) => Array.from({ length: n }, (_, i) => `p${i}`);

// ═══════════════════════════════════════════════════════════════════
// JobPhotoThumbs — component unit tests
// ═══════════════════════════════════════════════════════════════════
describe("JobPhotoThumbs — empty state", () => {
  it("renders em-dash + scoped testid when no photos", () => {
    render(<JobPhotoThumbs jobId="j-empty" photoIds={[]} photoThumbUrls={[]} />);
    const empty = screen.getByTestId("job-photos-empty-j-empty");
    expect(empty).toBeInTheDocument();
    expect(empty).toHaveTextContent("—");
  });

  it("empty state also fires when both props are undefined", () => {
    render(<JobPhotoThumbs jobId="j-noprops" />);
    expect(screen.getByTestId("job-photos-empty-j-noprops")).toBeInTheDocument();
  });
});

describe("JobPhotoThumbs — thumbnail rendering", () => {
  it("renders exactly 1 thumb for a 1-photo row + NO overflow badge", () => {
    render(
      <JobPhotoThumbs jobId="j1" photoIds={_ids(1)} photoThumbUrls={_urls(1)} />
    );
    expect(screen.getByTestId("job-photos-container-j1")).toBeInTheDocument();
    expect(screen.getByTestId("job-photos-thumb-j1-0")).toBeInTheDocument();
    expect(screen.queryByTestId("job-photos-thumb-j1-1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("job-photos-more-j1")).not.toBeInTheDocument();
  });

  it("renders exactly 2 thumbs for a 2-photo row + NO overflow badge", () => {
    render(
      <JobPhotoThumbs jobId="j2" photoIds={_ids(2)} photoThumbUrls={_urls(2)} />
    );
    expect(screen.getByTestId("job-photos-thumb-j2-0")).toBeInTheDocument();
    expect(screen.getByTestId("job-photos-thumb-j2-1")).toBeInTheDocument();
    expect(screen.queryByTestId("job-photos-more-j2")).not.toBeInTheDocument();
  });

  it("renders exactly 3 thumbs at max=3 + NO overflow when count===max", () => {
    render(
      <JobPhotoThumbs jobId="j3" photoIds={_ids(3)} photoThumbUrls={_urls(3)} />
    );
    expect(screen.getByTestId("job-photos-thumb-j3-0")).toBeInTheDocument();
    expect(screen.getByTestId("job-photos-thumb-j3-1")).toBeInTheDocument();
    expect(screen.getByTestId("job-photos-thumb-j3-2")).toBeInTheDocument();
    expect(screen.queryByTestId("job-photos-thumb-j3-3")).not.toBeInTheDocument();
    expect(screen.queryByTestId("job-photos-more-j3")).not.toBeInTheDocument();
  });

  it("renders 3 thumbs + '+2' badge for a 5-photo row", () => {
    render(
      <JobPhotoThumbs jobId="j5" photoIds={_ids(5)} photoThumbUrls={_urls(5)} />
    );
    expect(screen.getByTestId("job-photos-thumb-j5-0")).toBeInTheDocument();
    expect(screen.getByTestId("job-photos-thumb-j5-1")).toBeInTheDocument();
    expect(screen.getByTestId("job-photos-thumb-j5-2")).toBeInTheDocument();
    expect(screen.queryByTestId("job-photos-thumb-j5-3")).not.toBeInTheDocument();
    const more = screen.getByTestId("job-photos-more-j5");
    expect(more).toBeInTheDocument();
    expect(more).toHaveTextContent("+2");
  });

  it("honors a custom max prop (max=2 on a 5-photo row → '+3' badge)", () => {
    render(
      <JobPhotoThumbs
        jobId="jcap"
        photoIds={_ids(5)}
        photoThumbUrls={_urls(5)}
        max={2}
      />
    );
    expect(screen.getByTestId("job-photos-thumb-jcap-0")).toBeInTheDocument();
    expect(screen.getByTestId("job-photos-thumb-jcap-1")).toBeInTheDocument();
    expect(screen.queryByTestId("job-photos-thumb-jcap-2")).not.toBeInTheDocument();
    expect(screen.getByTestId("job-photos-more-jcap")).toHaveTextContent("+3");
  });

  it("honors a custom testidBase prop", () => {
    render(
      <JobPhotoThumbs
        jobId="jbase"
        photoIds={_ids(2)}
        photoThumbUrls={_urls(2)}
        testidBase="ws-photos"
      />
    );
    expect(screen.getByTestId("ws-photos-container-jbase")).toBeInTheDocument();
    expect(screen.getByTestId("ws-photos-thumb-jbase-0")).toBeInTheDocument();
    expect(screen.queryByTestId("job-photos-container-jbase")).not.toBeInTheDocument();
  });
});

describe("JobPhotoThumbs — image error handling", () => {
  it("onError swaps a broken thumb to the ImageOff placeholder", () => {
    render(
      <JobPhotoThumbs jobId="jerr" photoIds={_ids(1)} photoThumbUrls={_urls(1)} />
    );
    const tile = screen.getByTestId("job-photos-thumb-jerr-0");
    const img = tile.querySelector("img");
    expect(img).toBeInTheDocument();
    // Fire the onError callback.
    fireEvent.error(img);
    // <img> is unmounted; ImageOff SVG appears in its place.
    expect(tile.querySelector("img")).not.toBeInTheDocument();
    expect(tile.querySelector("svg")).toBeInTheDocument();
  });
});

// ═══════════════════════════════════════════════════════════════════
// JobsList integration — source-body pins (no ReactRouter mount)
// ═══════════════════════════════════════════════════════════════════
describe("JobsList — Photos column integration", () => {
  it("declares the new Photos column header with the jobs-col-photos testid", () => {
    expect(SRC_JOBSLIST).toMatch(/data-testid="jobs-col-photos"/);
    expect(SRC_JOBSLIST).toMatch(/>\s*Photos\s*</);
  });

  it("Photos column is hidden below md: breakpoint (matches Customer column)", () => {
    // Both the header cell + the row cell use the same responsive class.
    expect(SRC_JOBSLIST).toMatch(
      /hidden\s+md:table-cell[^>]*data-testid="jobs-col-photos"/
    );
  });

  it("row cell renders JobPhotoThumbs from precomputed row data", () => {
    expect(SRC_JOBSLIST).toMatch(/<JobPhotoThumbs\s/);
    expect(SRC_JOBSLIST).toMatch(/photoIds=\{r\.photo_ids\}/);
    expect(SRC_JOBSLIST).toMatch(/photoThumbUrls=\{r\.photo_thumb_urls\}/);
  });

  it("empty-state row colSpan bumped from 5 → 6 after column addition", () => {
    expect(SRC_JOBSLIST).toMatch(/colSpan=\{6\}/);
    expect(SRC_JOBSLIST).not.toMatch(/colSpan=\{5\}/);
  });

  it("preserves every pre-existing JobsList testid (regression guard)", () => {
    // Grep 3 (Task L+P plan) enumerated every testid on this page.
    // Any drift here surfaces as a test failure.
    expect(SRC_JOBSLIST).toMatch(/data-testid="jobs-page"/);
    expect(SRC_JOBSLIST).toMatch(/data-testid="jobs-refresh-btn"/);
    expect(SRC_JOBSLIST).toMatch(/data-testid="jobs-filter-status"/);
    expect(SRC_JOBSLIST).toMatch(/data-testid="jobs-table"/);
    expect(SRC_JOBSLIST).toMatch(/data-testid="jobs-empty"/);
    expect(SRC_JOBSLIST).toMatch(/data-testid=\{`job-row-\$\{r\.id\}`\}/);
    expect(SRC_JOBSLIST).toMatch(/data-testid=\{`job-row-customer-\$\{r\.id\}`\}/);
  });

  it("preserves every bulk-reschedule testid (regression guard)", () => {
    // Actual testids on the current file — enumerated at build
    // time so this assertion catches accidental drift on the
    // reschedule modal in a future edit.
    expect(SRC_JOBSLIST).toMatch(/data-testid="bulk-reschedule-mode-absolute"/);
    expect(SRC_JOBSLIST).toMatch(/data-testid="bulk-reschedule-mode-relative"/);
    expect(SRC_JOBSLIST).toMatch(/data-testid="bulk-reschedule-datepicker"/);
    expect(SRC_JOBSLIST).toMatch(/data-testid="bulk-reschedule-shift-direction"/);
    expect(SRC_JOBSLIST).toMatch(/data-testid="bulk-reschedule-shift-direction-minus"/);
    expect(SRC_JOBSLIST).toMatch(/data-testid="bulk-reschedule-shift-direction-plus"/);
    expect(SRC_JOBSLIST).toMatch(/data-testid="bulk-reschedule-shift-value"/);
    expect(SRC_JOBSLIST).toMatch(/data-testid="bulk-reschedule-shift-unit"/);
    expect(SRC_JOBSLIST).toMatch(/data-testid="bulk-reschedule-anchor-unscheduled"/);
    expect(SRC_JOBSLIST).toMatch(/data-testid="bulk-reschedule-open-confirm"/);
    expect(SRC_JOBSLIST).toMatch(/data-testid="bulk-reschedule-cancel"/);
    expect(SRC_JOBSLIST).toMatch(/testidRoot="bulk-reschedule-confirm"/);
  });

  it("imports the JobPhotoThumbs component from the shared components path", () => {
    expect(SRC_JOBSLIST).toMatch(
      /import\s+\{\s*JobPhotoThumbs\s*\}\s+from\s+["']@\/components\/jobs\/JobPhotoThumbs["']/
    );
  });
});
