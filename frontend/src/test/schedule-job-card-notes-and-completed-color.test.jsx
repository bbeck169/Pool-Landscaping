/**
 * Phase 3 · Feb-2026 — Schedule job card: inline pool/landscape notes
 * + dramatic bold-red completed card color (frontend contract).
 *
 * Locks:
 *   (a) ``JobNotesCallout`` renders Customer / Pool / Landscape as
 *       three independent inline blocks when the source fields are
 *       populated — in that exact DOM order.
 *   (b) Empty / null / whitespace sources hide their respective
 *       block entirely (no "Pool note:" label with no body).
 *   (c) Each customer-sourced block truncates at 120 chars OR 3
 *       lines (``line-clamp-3`` + heuristic) with its OWN "Show
 *       more" / "Show less" toggle.  Clicking Pool's toggle MUST
 *       NOT expand Landscape (per-block state).
 *   (d) The legacy "Note" badge path (``<ServiceNotePill>``) is no
 *       longer rendered from ``TodaySchedule.jsx`` — regression
 *       guarded by a source-level grep so a merge that re-adds the
 *       pill fails this test.
 *   (e) ``jobStatusColor("completed")`` returns the new ``#DC2626``
 *       (Tailwind red-600) — not the legacy soft-pink ``#FDECEC``.
 *   (f) Non-completed statuses are untouched (regression lock).
 */
import React from "react";
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import fs from "node:fs";
import path from "node:path";

import JobNotesCallout from "@/components/schedule/JobNotesCallout";
import { jobStatusColor } from "@/lib/jobStatus";


const JOB_ID = "j-phase3";

afterEach(() => cleanup());


describe("Phase 3 · JobNotesCallout — inline customer / pool / landscape blocks", () => {
  it("renders all three customer-sourced blocks inline in the correct order", () => {
    render(
      <JobNotesCallout
        jobId={JOB_ID}
        customerNote="Customer file — leave gate open"
        poolNote="Pool pump squeals · check impeller"
        landscapeNote="HOA citations · trim mesquite below 7ft"
      />,
    );
    const cust = screen.getByTestId(`job-notes-preview-${JOB_ID}-text`);
    const pool = screen.getByTestId(`job-notes-pool-${JOB_ID}-text`);
    const land = screen.getByTestId(`job-notes-landscape-${JOB_ID}-text`);

    expect(cust.textContent).toContain("leave gate open");
    expect(pool.textContent).toContain("squeals");
    expect(land.textContent).toContain("trim mesquite");

    // Labels present in the exact brief-required order.
    expect(cust.textContent).toMatch(/^Customer note:/);
    expect(pool.textContent).toMatch(/^Pool note:/);
    expect(land.textContent).toMatch(/^Landscape note:/);

    // DOM ordering — Customer precedes Pool precedes Landscape.
    expect(cust.compareDocumentPosition(pool) & 4).toBe(4);
    expect(pool.compareDocumentPosition(land) & 4).toBe(4);
  });

  it("hides any block whose source is empty, null, or whitespace", () => {
    render(
      <JobNotesCallout
        jobId={JOB_ID}
        customerNote="Only customer note"
        poolNote={null}
        landscapeNote={"   "}
      />,
    );
    expect(screen.getByTestId(`job-notes-preview-${JOB_ID}-text`)
      .textContent).toContain("Only customer note");
    expect(screen.queryByTestId(`job-notes-pool-${JOB_ID}-text`)).toBeNull();
    expect(screen.queryByTestId(`job-notes-landscape-${JOB_ID}-text`))
      .toBeNull();
  });

  it("hides the entire callout when every source is empty", () => {
    const { container } = render(
      <JobNotesCallout
        jobId={JOB_ID}
        note=""
        customerNote=""
        poolNote={null}
        landscapeNote=""
      />,
    );
    expect(container.textContent).toBe("");
    expect(screen.queryByTestId(`job-notes-callout-${JOB_ID}`)).toBeNull();
  });

  it("applies line-clamp-3 and shows a per-block Show more toggle at >120 chars", () => {
    const LONG = "P".repeat(130) + " end";  // 134 chars > 120
    render(
      <JobNotesCallout
        jobId={JOB_ID}
        poolNote={LONG}
        landscapeNote="short landscape — no toggle"
      />,
    );
    const poolText = screen.getByTestId(`job-notes-pool-${JOB_ID}-text`);
    expect(poolText.className).toContain("line-clamp-3");

    const toggle = screen.getByTestId(`job-notes-pool-${JOB_ID}-toggle`);
    expect(toggle.textContent).toBe("Show more");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    // No toggle on the short landscape block (<=120 chars, no newline).
    expect(screen.queryByTestId(`job-notes-landscape-${JOB_ID}-toggle`))
      .toBeNull();

    // Click Pool's toggle → Pool expands only.
    fireEvent.click(toggle);
    expect(poolText.className).not.toContain("line-clamp-3");
    expect(screen.getByTestId(`job-notes-pool-${JOB_ID}-toggle`).textContent)
      .toBe("Show less");
  });

  it("per-block state — expanding Pool does NOT expand Landscape", () => {
    const LONG_POOL = "A".repeat(140);
    const LONG_LAND = "B".repeat(140);
    render(
      <JobNotesCallout
        jobId={JOB_ID}
        poolNote={LONG_POOL}
        landscapeNote={LONG_LAND}
      />,
    );
    const poolText = screen.getByTestId(`job-notes-pool-${JOB_ID}-text`);
    const landText = screen.getByTestId(`job-notes-landscape-${JOB_ID}-text`);
    expect(poolText.className).toContain("line-clamp-3");
    expect(landText.className).toContain("line-clamp-3");

    fireEvent.click(
      screen.getByTestId(`job-notes-pool-${JOB_ID}-toggle`),
    );

    // Pool expanded, Landscape still clamped.
    expect(poolText.className).not.toContain("line-clamp-3");
    expect(landText.className).toContain("line-clamp-3");
    expect(
      screen.getByTestId(`job-notes-landscape-${JOB_ID}-toggle`).textContent,
    ).toBe("Show more");
  });

  it("mirrors the customer-note visual treatment (label fontWeight 700, muted color prefix)", () => {
    render(
      <JobNotesCallout
        jobId={JOB_ID}
        customerNote="legacy visual anchor"
        poolNote="pool — same treatment"
        landscapeNote="landscape — same treatment"
      />,
    );
    const custLabel = screen.getByTestId(`job-notes-preview-${JOB_ID}-text`)
      .querySelector("span");
    const poolLabel = screen.getByTestId(`job-notes-pool-${JOB_ID}-text`)
      .querySelector("span");
    const landLabel = screen.getByTestId(`job-notes-landscape-${JOB_ID}-text`)
      .querySelector("span");

    for (const el of [custLabel, poolLabel, landLabel]) {
      expect(el).toBeTruthy();
      expect(el.style.fontWeight).toBe("700");
      // Muted label color — JSDOM normalises hex → rgb for computed style
      // reads via ``.style.color`` returning the raw inline string.
      expect(el.style.color).toMatch(/var\(--note-label-fg|#4B5563|rgb\(75,\s*85,\s*99\)/i);
    }
  });

  it("legacy job free-text note keeps its 2-line clamp (backward compat)", () => {
    const LONG = "Z".repeat(180);
    render(
      <JobNotesCallout
        jobId={JOB_ID}
        note={LONG}
      />,
    );
    const body = screen.getByTestId(`job-${JOB_ID}-notes`);
    expect(body.className).toContain("line-clamp-2");
    expect(body.className).not.toContain("line-clamp-3");
  });
});


describe("Phase 3 · completed-card dramatic red color", () => {
  it("jobStatusColor('completed') is Tailwind red-600 (#DC2626)", () => {
    expect(jobStatusColor("completed")).toBe("#DC2626");
    // Case + whitespace tolerant.
    expect(jobStatusColor("  Completed ")).toBe("#DC2626");
    expect(jobStatusColor("CLOSED")).toBe("#DC2626");
    expect(jobStatusColor("done")).toBe("#DC2626");
  });

  it("non-completed statuses are unchanged (regression lock)", () => {
    expect(jobStatusColor("open")).toBe("#EAF7F0");
    expect(jobStatusColor("scheduled")).toBe("#EAF7F0");
    expect(jobStatusColor("in_progress")).toBe("#FEF3C7");
    expect(jobStatusColor("cancelled")).toBe("#FECACA");
    expect(jobStatusColor("skipped")).toBe("#FED7AA");
    expect(jobStatusColor("missed")).toBe("#FCA5A5");
    expect(jobStatusColor("pending")).toBe("#EAF7F0");   // K57 alias
  });

  it("index.css carries a cascade that forces white text on the red completed card", () => {
    // Read the raw stylesheet — the cascade rule is static CSS, so
    // asserting its presence is the cheapest way to lock the rule in.
    const css = fs.readFileSync(
      path.resolve(__dirname, "../index.css"), "utf8",
    );
    // Rule exists AND targets the completed-card attribute selector.
    expect(css).toMatch(/\[data-k50-bg="#DC2626"\]/);
    expect(css).toMatch(/\[data-k50-bg="#DC2626"\]\s*\*\s*\{[^}]*color:\s*#FFFFFF/i);
  });

  it("ServiceNotePill is no longer imported inside TodaySchedule.jsx card body", () => {
    // Regression guard — the pill was removed from both schedule
    // views in Phase 3.  If a merge re-adds a ``<ServiceNotePill``
    // JSX tag inside TodaySchedule.jsx, this test fails loudly.
    // ``CalendarSchedule.jsx`` is covered by its own grep below.
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/schedule/TodaySchedule.jsx"),
      "utf8",
    );
    expect(src).not.toMatch(/<ServiceNotePill\b/);
  });

  it("ServiceNotePill is no longer imported inside CalendarSchedule.jsx card body", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/schedule/CalendarSchedule.jsx"),
      "utf8",
    );
    expect(src).not.toMatch(/<ServiceNotePill\b/);
  });
});
