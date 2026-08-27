/**
 * Feb-2026 · Three-item ship — source-inspection contracts.
 *
 * Item 1 — Job Detail crew fallback in the Technician meta cell.
 * Item 2 — Marketing Templates admin channel picker (segmented).
 * Item 3 — Marketing Sequences trigger label + testid alias for
 *          ``job_scheduled_reminder_1d``.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const jobDetailSrc = fs.readFileSync(
  path.resolve(__dirname, "../pages/jobs/JobDetail.jsx"), "utf8",
);
const templatesAdminSrc = fs.readFileSync(
  path.resolve(__dirname, "../pages/marketing/MarketingTemplatesAdmin.jsx"),
  "utf8",
);
const sequencesPageSrc = fs.readFileSync(
  path.resolve(__dirname, "../pages/marketing/MarketingSequencesPage.jsx"),
  "utf8",
);


describe("Item 1 · JobDetail — Technician meta cell (crew fallback)", () => {
  it("prefers technician_name, falls back to Crew: <crew_name>, then Unassigned", () => {
    // Fallback chain — literal source-code shape.
    expect(jobDetailSrc).toMatch(
      /job\.technician_name\s*\|\|\s*[\s\S]{0,120}crew_name[\s\S]{0,120}"Unassigned"/,
    );
    // Crew label formatting.
    expect(jobDetailSrc).toMatch(/Crew:\s*\$\{job\.crew_name\}/);
  });
});


describe("Item 2 · Templates admin — channel picker", () => {
  it("locked-only label is gone", () => {
    // The legacy "(locked)" hint must be removed.
    expect(templatesAdminSrc).not.toMatch(/\(locked\)/);
  });

  it("segmented control renders both channels with stable testids", () => {
    // Testids are mapped through the button loop; assert both
    // string literals are present anywhere in the file.
    expect(templatesAdminSrc).toMatch(/"id-template-channel-email"/);
    expect(templatesAdminSrc).toMatch(/"id-template-channel-sms"/);
    // And they land on ``data-testid`` via the loop variable.
    expect(templatesAdminSrc).toMatch(/data-testid=\{testid\}/);
  });

  it("channel toggle patches the row via patchLocal({channel})", () => {
    // The onClick constructs a ``patch`` dict then calls patchLocal.
    expect(templatesAdminSrc).toMatch(/const patch = \{ channel: v \}/);
    expect(templatesAdminSrc).toMatch(/patchLocal\(patch\)/);
  });
});


describe("Item 3 · Sequences — job_scheduled_reminder_1d option", () => {
  it("registers a human label for the new trigger type", () => {
    expect(sequencesPageSrc).toMatch(
      /job_scheduled_reminder_1d:\s*"Job scheduled reminder \(1 day before\)"/,
    );
  });

  it("exposes both testid aliases on the trigger <select>", () => {
    // Legacy testid preserved so existing tests + tools keep working.
    expect(sequencesPageSrc).toMatch(/data-testid="sequence-trigger-select"/);
    // New alias per this ship's spec.
    expect(sequencesPageSrc).toMatch(
      /data-e2e-testid="id-sequence-trigger-select"/,
    );
  });
});
