/**
 * Feb-2026 · "+ New Scheduled Job" quick-action on Job Detail (web).
 *
 * Source-inspection contract test — matches the sibling
 * ``schedule-job-notes`` / ``routes-enriched-names`` shape (avoids
 * mounting the 620-line JobDetail tree). Asserts:
 *   1. The button exists with the correct testid.
 *   2. The <JobNew> modal is mounted in ``renderMode="modal"``.
 *   3. Pre-fill defaults are derived from the current ``job`` — the
 *      customer_id, property_id, technician_id are copied through
 *      as-is, and scheduled_date defaults to today.
 *   4. The <JobNew> component itself now accepts ``initialValues``,
 *      ``renderMode``, ``onCreated`` and ``onCancel`` props.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const detailSrc = fs.readFileSync(
  path.resolve(__dirname, "../pages/jobs/JobDetail.jsx"),
  "utf8",
);
const jobNewSrc = fs.readFileSync(
  path.resolve(__dirname, "../pages/jobs/JobNew.jsx"),
  "utf8",
);

describe("JobDetail · '+ New Scheduled Job' quick-action", () => {
  it("renders the header button with data-testid=jd-new-scheduled-job", () => {
    expect(detailSrc).toMatch(/testid=["']jd-new-scheduled-job["']/);
    expect(detailSrc).toMatch(/New Scheduled Job/);
  });

  it("mounts <JobNew> in modal mode with pre-fill defaults", () => {
    // JobNew must be imported and rendered inside a Modal.
    expect(detailSrc).toMatch(/import\s+JobNew\s+from\s+["']@\/pages\/jobs\/JobNew["']/);
    // The mount site passes ``renderMode="modal"`` + initialValues
    // sourced from ``job.customer_id`` / ``job.property_id`` /
    // ``job.technician_id`` and defaults ``scheduled_date`` to today.
    expect(detailSrc).toMatch(/renderMode=["']modal["']/);
    expect(detailSrc).toMatch(/customer_id:\s*job\.customer_id/);
    expect(detailSrc).toMatch(/property_id:\s*job\.property_id/);
    expect(detailSrc).toMatch(/technician_id:\s*job\.technician_id/);
    expect(detailSrc).toMatch(
      /scheduled_date:\s*new Date\(\)\.toISOString\(\)\.slice\(0,\s*10\)/,
    );
    // Feb-2026 bug fix — service_type MUST arrive BLANK so the
    // admin re-picks it deliberately. Guard against a regression
    // that forwards ``job.service_type`` through initialValues.
    expect(detailSrc).toMatch(/service_type:\s*["']{2}\s*,/);
    expect(detailSrc).not.toMatch(/service_type:\s*job\.service_type/);
  });

  it("stays on JobDetail after create — success toast, no navigate", () => {
    // The onCreated handler must close the modal and set a toast
    // that surfaces the customer name + scheduled date. Any
    // ``navigate(`/jobs/`)`` inside onCreated would violate the
    // stay-on-page UX contract.
    const onCreatedBlock = detailSrc.match(
      /onCreated=\{[\s\S]{0,500}?\}\}/,
    );
    expect(onCreatedBlock).not.toBeNull();
    expect(onCreatedBlock[0]).toMatch(/setCreateOpen\(false\)/);
    expect(onCreatedBlock[0]).toMatch(/Job scheduled for/);
    expect(onCreatedBlock[0]).not.toMatch(/navigate\(`\/jobs\//);
  });
});

describe("JobNew · reusable modal-mode contract", () => {
  it("accepts initialValues + renderMode + onCreated + onCancel props", () => {
    // Props signature — the modal callers depend on all four.
    expect(jobNewSrc).toMatch(
      /export default function JobNew\(\s*\{[\s\S]{0,200}initialValues[\s\S]{0,200}renderMode[\s\S]{0,200}onCreated[\s\S]{0,200}onCancel/,
    );
  });

  it("prefers initialValues over URL query params", () => {
    // The ??-chain must consult props FIRST so a JobDetail modal
    // cannot be overridden by URL noise.
    expect(jobNewSrc).toMatch(
      /iv\.customer_id\s*\?\?\s*params\.get\(["']customer_id["']\)/,
    );
    expect(jobNewSrc).toMatch(
      /iv\.property_id\s*\?\?\s*params\.get\(["']property_id["']\)/,
    );
    expect(jobNewSrc).toMatch(
      /iv\.technician_id\s*\?\?\s*params\.get\(["']technician_id["']\)/,
    );
    expect(jobNewSrc).toMatch(
      /iv\.scheduled_date\s*\?\?\s*params\.get\(["']scheduled_date["']\)/,
    );
    // Feb-2026 · service_type must also honour ``initialValues``
    // (with ``??`` so an explicit ``""`` survives). The form seeds
    // its state from ``preselectedService`` — so passing
    // ``service_type: ""`` from JobDetail lands as blank.
    expect(jobNewSrc).toMatch(
      /iv\.service_type\s*\?\?\s*params\.get\(["']service_type["']\)/,
    );
    expect(jobNewSrc).toMatch(/service_type:\s*preselectedService,/);
  });

  it("calls onCreated instead of navigating when renderMode=modal", () => {
    // The success path must branch on ``renderMode === "modal"``.
    expect(jobNewSrc).toMatch(
      /renderMode\s*===\s*["']modal["'][\s\S]{0,200}onCreated\(first\)/,
    );
  });
});
