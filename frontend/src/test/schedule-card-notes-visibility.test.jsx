/**
 * Feb-2026 · Schedule polish — Job Notes visibility bump (vitest).
 *
 * Covers 4 behavioural assertions of the shared <JobNotesCallout>:
 *   1. Job with notes → renders the accented note card with the correct text.
 *   2. Job without notes AND without customer_notes → renders nothing.
 *   3. Long notes → 2-line clamp visible + "Show more" toggle; click expands.
 *   4. Icon accessible label present (a11y) + the amber accent bar is applied.
 */
import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";

import JobNotesCallout from "@/components/schedule/JobNotesCallout";

const JOB_ID = "j-abc";

describe("JobNotesCallout — schedule card notes visibility polish", () => {
  it("renders the accented note card when job has notes", () => {
    render(
      <JobNotesCallout jobId={JOB_ID} note="Deep clean · check pump" />,
    );
    const chip = screen.getByTestId(`job-notes-callout-${JOB_ID}`);
    expect(chip).toBeTruthy();
    // Amber left-border accent bar applied via longhand props.
    expect(chip.style.borderLeftWidth).toBe("3px");
    expect(chip.style.borderLeftStyle).toBe("solid");
    // JSDOM normalizes named / hex colors to rgb().
    expect(chip.style.borderLeftColor.toLowerCase())
      .toMatch(/rgb\(245,\s*158,\s*11\)|#f59e0b/i);
    // Body renders the exact note text.
    expect(screen.getByTestId(`job-${JOB_ID}-notes`).textContent)
      .toBe("Deep clean · check pump");
    // No "Show more" for short notes.
    expect(screen.queryByTestId(`job-notes-toggle-${JOB_ID}`)).toBeNull();
    cleanup();
  });

  it("renders nothing when the job has no notes and no customer notes", () => {
    const { container } = render(<JobNotesCallout jobId={JOB_ID} />);
    // No chip in the DOM — the card stays clean.
    expect(container.textContent).toBe("");
    expect(screen.queryByTestId(`job-notes-callout-${JOB_ID}`)).toBeNull();
    // Same when the field is whitespace-only.
    cleanup();
    const { container: c2 } = render(
      <JobNotesCallout jobId={JOB_ID} note="   " customerNote="  " />,
    );
    expect(c2.textContent).toBe("");
    cleanup();
  });

  it("long notes → 2-line clamp + Show more toggle expands inline", () => {
    const longNote = "A".repeat(180) + " end";
    render(<JobNotesCallout jobId={JOB_ID} note={longNote} />);
    const body = screen.getByTestId(`job-${JOB_ID}-notes`);
    // Initially clamped.
    expect(body.className).toContain("line-clamp-2");
    // Show more affordance present.
    const toggle = screen.getByTestId(`job-notes-toggle-${JOB_ID}`);
    expect(toggle.textContent).toBe("Show more");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    // Click expands inline (no modal opens; no navigation).
    fireEvent.click(toggle);
    expect(body.className).not.toContain("line-clamp-2");
    expect(screen.getByTestId(`job-notes-toggle-${JOB_ID}`).textContent).toBe("Show less");
    expect(screen.getByTestId(`job-notes-toggle-${JOB_ID}`).getAttribute("aria-expanded")).toBe("true");
    cleanup();
  });

  it("icon renders with accessible label + WHITE fill / amber left-accent (Feb-2026 hotfix)", () => {
    render(<JobNotesCallout jobId={JOB_ID} note="Gate on right" />);
    const icon = screen.getByTestId(`job-notes-icon-${JOB_ID}`);
    expect(icon).toBeTruthy();
    // Lucide forwards ``aria-label`` to the svg — assert it surfaces.
    expect(icon.getAttribute("aria-label")).toBe("Job note");
    // Feb-2026 hotfix — chip is now WHITE background with an amber
    // left-border accent (no more amber-100 fill that competed with
    // the K74 mint card). The inline style references the semantic
    // ``--note-*`` tokens defined in ``index.css``.
    const chip = screen.getByTestId(`job-notes-callout-${JOB_ID}`);
    expect(chip.getAttribute("data-note-surface")).toBe("white");
    const styleStr = chip.getAttribute("style") || "";
    expect(styleStr).toMatch(/--note-bg-white/);
    expect(styleStr).toMatch(/--note-accent/);
    // Regression-guard the amber fill that we intentionally removed.
    expect(styleStr).not.toMatch(/#FEF3C7/i);
    cleanup();
  });
});
