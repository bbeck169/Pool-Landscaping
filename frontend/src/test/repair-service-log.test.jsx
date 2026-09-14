/**
 * Feb-2026 · Repair-mode service log — source-inspection contract.
 *
 * Locks in the branching behavior across three surfaces so a
 * refactor can't silently regress the repair flow:
 *
 * * Tech-facing ``ServiceReport.jsx`` conditionally renders the
 *   repair form (photos + videos + internal + external notes) and
 *   HIDES chemistry + chemicals + checklist when
 *   ``report.work_class === "repair"``.
 * * Workstream ``ServiceLogPage.jsx`` shows the orange "Repair"
 *   chip.
 * * Portal ``PortalServiceReports.jsx`` shows the same chip AND
 *   omits chemistry AND renders inline ``<video controls>`` when
 *   the response carries a ``videos`` array. ``internal_notes``
 *   MUST NEVER appear in this file (redaction is backend, but the
 *   source doesn't reference the field at all → double-guard).
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";

const techSrc = fs.readFileSync(
  path.resolve(__dirname, "../pages/tech/ServiceReport.jsx"),
  "utf8",
);
const wsSrc = fs.readFileSync(
  path.resolve(__dirname, "../pages/workstream/ServiceLogPage.jsx"),
  "utf8",
);
const portalSrc = fs.readFileSync(
  path.resolve(__dirname, "../pages/portal/PortalServiceReports.jsx"),
  "utf8",
);


describe("Repair-mode service log — tech form (ServiceReport.jsx)", () => {
  it("computes isRepair from report.work_class", () => {
    expect(techSrc).toMatch(
      /const isRepair\s*=\s*\(report\.work_class \|\| ""\)\.toLowerCase\(\)\s*===\s*"repair"/,
    );
  });

  it("hides chemistry / chemicals sections under !isRepair", () => {
    // Feb-2026 · Section header renamed "Chemical Readings" →
    // "Chemistry Readings" to align with the structured
    // WaterBodyPanel taxonomy. Regex updated in lockstep.
    expect(techSrc).toMatch(/isPool\s*&&\s*!isRepair\s*&&\s*\(\s*[\s\S]{0,400}Chemistry Readings/);
    expect(techSrc).toMatch(/isPool\s*&&\s*!isRepair\s*&&\s*\(\s*[\s\S]{0,400}Chemicals Added/);
  });

  it("hides checklist section under !isRepair", () => {
    expect(techSrc).toMatch(/!isRepair\s*&&\s*\([\s\S]{0,400}"Checklist"/);
  });

  it("renders repair videos + internal + external notes with stable testids", () => {
    expect(techSrc).toMatch(/data-testid="id-repair-log-videos"/);
    expect(techSrc).toMatch(/data-testid="id-repair-log-notes-internal"/);
    expect(techSrc).toMatch(/data-testid="id-repair-log-notes-external"/);
    // Repair submit uses a distinct testid so the pool testid doesn't
    // collide when both branches ship in the same suite.
    expect(techSrc).toMatch(/data-testid=\{isRepair \? "id-repair-log-submit" : "svc-report-submit"\}/);
  });

  it("skips the client chemistry gate on repair submit", () => {
    expect(techSrc).toMatch(
      /disabled=\{submitting \|\| \(!isRepair && coreMissingLive\.length > 0\)\}/,
    );
  });

  it("autosave patch includes internal_notes + customer_notes", () => {
    expect(techSrc).toMatch(/internal_notes: report\.internal_notes/);
    expect(techSrc).toMatch(/customer_notes: report\.customer_notes/);
  });

  it("uploads repair videos via the modern /service-reports/{id}/media endpoint", () => {
    expect(techSrc).toMatch(
      /\/api\/service-reports\/\$\{report\.id\}\/media/,
    );
    // Whitelisted video mime types match the Phase 27 backend policy.
    expect(techSrc).toMatch(/video\/mp4/);
    expect(techSrc).toMatch(/video\/quicktime/);
    expect(techSrc).toMatch(/video\/webm/);
  });

  it("enforces the 100 MB client-side cap with a helpful pre-network alert", () => {
    expect(techSrc).toMatch(/100\s*\*\s*1024\s*\*\s*1024/);
    expect(techSrc).toMatch(/100\s*MB/);
  });
});


describe("Repair-mode service log — workstream (ServiceLogPage.jsx)", () => {
  it("renders the orange Repair chip on log_details.work_class == repair", () => {
    expect(wsSrc).toMatch(
      /d\.log_details\?\.work_class \|\| ""[\s\S]{0,50}\.toLowerCase\(\)\s*===\s*"repair"/,
    );
    expect(wsSrc).toMatch(/data-testid="service-log-repair-chip"/);
    // Orange hue per the task spec.
    expect(wsSrc).toMatch(/#FED7AA/);
  });
});


describe("Repair-mode service log — customer portal (PortalServiceReports.jsx)", () => {
  it("shows the Repair chip when the redacted response carries work_class == repair", () => {
    expect(portalSrc).toMatch(
      /sr\.work_class \|\| ""[\s\S]{0,50}\.toLowerCase\(\)\s*!==\s*"repair"|sr\.work_class \|\| ""[\s\S]{0,50}\.toLowerCase\(\)\s*===\s*"repair"/,
    );
    expect(portalSrc).toMatch(/data-testid="portal-service-report-repair-chip"/);
  });

  it("hides the chemistry section on repair reports", () => {
    // The chemistry render guard combines kind==pool AND readings AND
    // work_class != "repair" — the exact conjunction the spec asks
    // for.
    expect(portalSrc).toMatch(
      /kind === "pool"[\s\S]{0,80}readings\.length > 0[\s\S]{0,180}work_class[\s\S]{0,50}!==\s*"repair"/,
    );
  });

  it("renders inline <video controls> when videos are present", () => {
    expect(portalSrc).toMatch(/sr\.videos[\s\S]{0,80}length > 0/);
    expect(portalSrc).toMatch(/<video[\s\S]{0,80}controls/);
    expect(portalSrc).toMatch(/data-testid=\{`portal-service-report-video-\$\{i\}`\}/);
  });

  it("NEVER references internal_notes as a JS expression in the portal component", () => {
    // Double-guard against a future refactor that might accidentally
    // start rendering internal_notes on the portal page. The backend
    // ``_redact_report_for_customer`` also strips it — belt +
    // suspenders. Comments referencing the field name are FINE
    // (they document the safety contract) — we only reject JS access
    // like ``sr.internal_notes`` or ``report.internal_notes``.
    expect(portalSrc).not.toMatch(/\b[a-zA-Z_$][\w$]*\.internal_notes\b/);
  });
});
