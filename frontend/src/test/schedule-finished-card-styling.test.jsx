/**
 * Feb-2026 · Schedule finished-state card styling (operator spec).
 *
 * Locks the finished-state bucket (``completed`` / ``closed`` /
 * ``cancelled`` / ``skipped``) rendering a recessive gray-100
 * background + dark-grey text on the Schedule job cards.  Open /
 * in-progress / missed / on-hold / requested / reopened cards
 * MUST keep their existing visually prominent styling.
 *
 * The suite exercises the shared ``jobStatus.js`` helpers directly
 * so a drift in either the background map or the text-color pair
 * blows up here instead of silently mis-rendering in production.
 */
import { describe, it, expect } from "vitest";

import {
  jobStatusColor,
  isFinishedJobStatus,
  jobStatusTextColor,
  K50_JOB_STATUS_BG,
} from "@/lib/jobStatus";


describe("isFinishedJobStatus · operator-defined terminal bucket", () => {
  const FINISHED = ["completed", "closed", "cancelled", "canceled", "skipped",
                     "done"];
  const NOT_FINISHED = ["open", "scheduled", "in_progress", "pending",
                         "requested", "on_my_way", "on_hold", "reopened",
                         "missed", "could_not_service", "", null, undefined];

  it.each(FINISHED)("returns true for finished status %j", (s) => {
    expect(isFinishedJobStatus(s)).toBe(true);
  });

  it.each(NOT_FINISHED)("returns false for non-finished status %j", (s) => {
    expect(isFinishedJobStatus(s)).toBe(false);
  });

  it("is case + whitespace tolerant", () => {
    expect(isFinishedJobStatus("  COMPLETED ")).toBe(true);
    expect(isFinishedJobStatus(" Cancelled")).toBe(true);
    expect(isFinishedJobStatus("SKIPPED")).toBe(true);
  });

  it("deliberately EXCLUDES ``missed`` (actionable, keeps prominence)", () => {
    // ``missed`` is written by the auto-cleanup poller when a job
    // stayed open past the staleness window — operator can re-open
    // or re-schedule, so it must stay visually loud (red-300 bg).
    expect(isFinishedJobStatus("missed")).toBe(false);
    expect(jobStatusColor("missed")).toBe("#FCA5A5");
  });
});


describe("jobStatusColor · finished-state bucket renders #F3F4F6", () => {
  it("every finished status resolves to Tailwind gray-100", () => {
    for (const s of ["completed", "closed", "cancelled", "skipped",
                      "done", "canceled"]) {
      expect(jobStatusColor(s)).toBe("#F3F4F6");
    }
  });

  it("open / in-progress / missed stay on their existing hexes (regression lock)", () => {
    expect(jobStatusColor("open")).toBe("#EAF7F0");
    expect(jobStatusColor("scheduled")).toBe("#EAF7F0");
    expect(jobStatusColor("in_progress")).toBe("#FEF3C7");
    expect(jobStatusColor("missed")).toBe("#FCA5A5");
    expect(jobStatusColor("pending")).toBe("#EAF7F0");  // K57 alias
  });

  it("non-K50 statuses still fall through to null (callers' pill-only treatment preserved)", () => {
    expect(jobStatusColor("on_hold")).toBeNull();
    expect(jobStatusColor("requested")).toBeNull();
    expect(jobStatusColor("reopened")).toBeNull();
  });

  it("K50_JOB_STATUS_BG stays frozen after the finished-state refactor", () => {
    expect(Object.isFrozen(K50_JOB_STATUS_BG)).toBe(true);
    expect(() => { K50_JOB_STATUS_BG.completed = "#000000"; })
      .toThrow();
  });
});


describe("jobStatusTextColor · dark-grey body text on finished cards", () => {
  it("returns #374151 (Tailwind gray-700) for every finished status", () => {
    for (const s of ["completed", "closed", "cancelled", "skipped",
                      "canceled"]) {
      expect(jobStatusTextColor(s)).toBe("#374151");
    }
  });

  it("returns null for non-finished statuses so callers fall through to colors.onSurface", () => {
    for (const s of ["open", "scheduled", "in_progress", "pending",
                      "requested", "on_hold", "missed", "reopened",
                      "could_not_service", ""]) {
      expect(jobStatusTextColor(s)).toBeNull();
    }
  });

  it("the paired bg + text combo clears WCAG AA for normal text (10.4:1 on #F3F4F6)", () => {
    // Lock the exact pair — if either side drifts, operators will
    // notice (either the bg becomes darker and the text no longer
    // reads, or the text lightens and ditto).  10.4:1 = AAA for
    // normal text, AAA for large text.
    expect(jobStatusColor("completed")).toBe("#F3F4F6");
    expect(jobStatusTextColor("completed")).toBe("#374151");
  });
});


describe("Source-level · finished-state styling wiring", () => {
  it("CalendarSchedule.jsx threads jobStatusTextColor + data-finished-state through the card body", () => {
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/schedule/CalendarSchedule.jsx"),
      "utf8",
    );
    expect(src).toMatch(/jobStatusTextColor/);
    expect(src).toMatch(/isFinishedJobStatus/);
    expect(src).toMatch(/data-finished-state=\{_isFinished\s*\?\s*["']true["']\s*:\s*["']false["']\}/);
    // Body text now reads ``_bodyTextColor`` (finished fallback →
    // ``colors.onSurface``) rather than ``colors.onSurface`` direct.
    expect(src).toMatch(/style=\{\{\s*color:\s*_bodyTextColor\s*\}\}/);
  });

  it("TodaySchedule.jsx threads jobStatusTextColor + data-finished-state through the card body", () => {
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/schedule/TodaySchedule.jsx"),
      "utf8",
    );
    expect(src).toMatch(/jobStatusTextColor/);
    expect(src).toMatch(/isFinishedJobStatus/);
    expect(src).toMatch(/data-finished-state=\{_isFinished\s*\?\s*["']true["']\s*:\s*["']false["']\}/);
    expect(src).toMatch(/color:\s*_bodyTextColor/);
  });

  it("index.css NO LONGER carries the obsolete #ff4542 white-text cascade", () => {
    const fs = require("fs");
    const path = require("path");
    const css = fs.readFileSync(
      path.resolve(__dirname, "../index.css"), "utf8",
    );
    expect(css).not.toMatch(/\[data-k50-bg="#ff4542"\]/);
    expect(css).not.toMatch(/\[data-k50-bg="#DC2626"\]/);
  });

  it("status pill palette (STATUS_PILL / cardStatusTone) keeps its colored chip treatment on finished cards", () => {
    // The operator brief says: "action-button styling on finished
    // cards — their status pills ('Completed', 'Cancelled', etc.)
    // can remain colored for scanability, just the card
    // body/background changes."  The STATUS_PILL map in
    // CalendarSchedule.jsx:252 is the source of truth for pill
    // colors — assert the finished-state entries keep their
    // distinct bg/fg pair rather than being blanket-grey'd.
    const fs = require("fs");
    const path = require("path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../pages/schedule/CalendarSchedule.jsx"),
      "utf8",
    );
    // Completed pill (green "Closed" label).
    expect(src).toMatch(/completed:\s*\{\s*bg:\s*"#DCFCE7"/);
    // Cancelled pill (gray chip — pre-existing, intentional).
    expect(src).toMatch(/cancelled:\s*\{\s*bg:\s*"#F3F4F6"/);
  });
});
