/**
 * Phase K4 · Feb-2026 — Bug fix: Schedule-created recurring jobs
 * (weekly / biweekly / same-day-monthly cadences) were never
 * appearing on the Recurring Jobs page because the JobNew submit
 * flow only pre-materialized N one-off ``POST /jobs`` inserts and
 * never wrote a template to ``db.recurring_job_templates``.
 *
 * Contract locked here — source-inspection form (the runtime path
 * involves a customer picker + technician list + recurrence preview
 * roundtrip that's already covered by the sibling suites; here we
 * lock the wire shape so a regression can't silently disable the
 * template insert).
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";


const jobNewSrc = fs.readFileSync(
  path.resolve(__dirname, "../pages/jobs/JobNew.jsx"),
  "utf8",
);


describe("JobNew · K4 recurring template mirror wiring", () => {
  it("posts to /recurring-jobs alongside the pre-materialized /jobs loop", () => {
    // The K4 fix adds a second POST to /recurring-jobs AFTER the
    // preview-driven /jobs loop.  Both wires must be present in
    // the same submit branch.
    expect(jobNewSrc).toMatch(/api\.post\(\s*"\/jobs"\s*,/);
    // The K4 template mirror.
    expect(jobNewSrc).toMatch(/api\.post\(\s*"\/recurring-jobs"\s*,\s*tplPayload/);
  });

  it("gates the template mirror behind the recurring-cadence check", () => {
    // The mirror MUST NOT fire for one-time cadences — the guard is
    // ``cadenceIsRecurring`` derived from ``preview.dates.length > 1
    // && form.cadence !== "one_time"``.
    expect(jobNewSrc).toMatch(
      /const\s+cadenceIsRecurring\s*=\s*preview\s*&&\s*Array\.isArray\(\s*preview\.dates\s*\)/,
    );
    expect(jobNewSrc).toMatch(
      /preview\.dates\.length\s*>\s*1/,
    );
    expect(jobNewSrc).toMatch(
      /form\.cadence\s*!==\s*"one_time"/,
    );
    // The template post is inside a second ``if (cadenceIsRecurring)``
    // block so the one-off happy path is untouched.
    const gateRe =
      /if\s*\(\s*cadenceIsRecurring\s*\)\s*\{[\s\S]*?api\.post\(\s*"\/recurring-jobs"/;
    expect(jobNewSrc).toMatch(gateRe);
  });

  it("maps cadence → frequency for all three recurring cadences", () => {
    // Weekly / biweekly / monthly cadences map to the RecurringJobIn
    // ``frequency`` enum so the RJ listing groups them correctly.
    expect(jobNewSrc).toMatch(/cadenceToFreq\s*=\s*\{/);
    expect(jobNewSrc).toMatch(/weekly:\s*"weekly"/);
    expect(jobNewSrc).toMatch(/biweekly:\s*"biweekly"/);
    expect(jobNewSrc).toMatch(/monthly:\s*"monthly"/);
  });

  it("seeds the generator cursor to the last pre-materialized date", () => {
    // The K4 fix stamps ``last_generated_through`` on the template
    // so the H10 daily generator won't double-book any of the
    // pre-materialized occurrences.
    expect(jobNewSrc).toMatch(
      /tplPayload\.last_generated_through\s*=\s*lastMaterialisedDate/,
    );
  });

  it("passes property_id / assigned_tech_id / crew_id through to the template", () => {
    // The RecurringJobIn model accepts these — the fix passes them
    // conditionally so the template inherits the schedule pick.
    expect(jobNewSrc).toMatch(
      /if\s*\(\s*form\.property_id\s*\)\s*tplPayload\.property_id\s*=\s*form\.property_id/,
    );
    expect(jobNewSrc).toMatch(
      /if\s*\(\s*form\.technician_id\s*\)\s*tplPayload\.assigned_tech_id\s*=\s*form\.technician_id/,
    );
    expect(jobNewSrc).toMatch(
      /if\s*\(\s*form\.crew_id\s*\)\s*tplPayload\.crew_id\s*=\s*form\.crew_id/,
    );
  });

  it("wraps the template post in try/catch so a template failure never rolls back the /jobs inserts", () => {
    // The pre-materialized /jobs rows are the source of truth for
    // scheduling; a template-mirror failure MUST surface a soft
    // warning but keep the created jobs intact.  The K4 branch is
    // uniquely identifiable by the fallback toast copy — grab the
    // window around it.
    const marker = "Recurring Jobs entry may need manual creation";
    const markerIdx = jobNewSrc.indexOf(marker);
    expect(markerIdx).toBeGreaterThan(0);
    const window = jobNewSrc.slice(
      Math.max(0, markerIdx - 900), markerIdx + 200,
    );
    expect(window).toMatch(
      /try\s*\{[\s\S]*?await\s+api\.post\(\s*"\/recurring-jobs"\s*,\s*tplPayload/,
    );
    expect(window).toMatch(/catch\s*\(\s*_te\s*\)/);
  });
});
