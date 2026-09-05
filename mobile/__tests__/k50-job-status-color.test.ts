/**
 * Phase K50 · Feb-2026 — Mobile Schedule job-card status background.
 *
 * MOBILE mirror of ``frontend/src/test/k50-theming.test.js``.
 * Locks in the ``status → hex`` contract on the mobile side so the
 * two surfaces never drift.
 */
import {
  jobStatusColor,
  K50_JOB_STATUS_BG,
} from "@/src/lib/jobStatus";

describe("K50 · Slice B — Mobile Schedule card status background", () => {
  it("returns the exact hex for the K50 five statuses (parity with web)", () => {
    expect(jobStatusColor("open")).toBe("#D6F5EE");
    expect(jobStatusColor("scheduled")).toBe("#D6F5EE");
    expect(jobStatusColor("in_progress")).toBe("#FEF3C7");
    expect(jobStatusColor("completed")).toBe("#FDECEC");
    expect(jobStatusColor("cancelled")).toBe("#FECACA");
    expect(jobStatusColor("skipped")).toBe("#FED7AA");
  });

  it("resolves legacy aliases (active / closed / canceled)", () => {
    expect(jobStatusColor("active")).toBe("#FEF3C7");
    expect(jobStatusColor("closed")).toBe("#FDECEC");
    expect(jobStatusColor("done")).toBe("#FDECEC");
    expect(jobStatusColor("canceled")).toBe("#FECACA");
  });

  it("K57 · Feb-2026 — ``pending`` resolves to the ``open`` bucket (#D6F5EE)", () => {
    // Parity with the web helper — see
    // ``frontend/src/test/k50-theming.test.js`` for the field-report
    // context.  Mobile is the surface where the bug was reported, so
    // this assertion is the primary regression gate.
    expect(jobStatusColor("pending")).toBe("#D6F5EE");
    // Case-insensitivity — helper lowercases + trims input.
    expect(jobStatusColor("Pending")).toBe("#D6F5EE");
    expect(jobStatusColor("PENDING")).toBe("#D6F5EE");
  });

  it("is case + whitespace insensitive", () => {
    expect(jobStatusColor("  In_Progress ")).toBe("#FEF3C7");
    expect(jobStatusColor("COMPLETED")).toBe("#FDECEC");
  });

  it("returns null for statuses outside the K50 map (caller falls back)", () => {
    expect(jobStatusColor("on_hold")).toBeNull();
    expect(jobStatusColor("requested")).toBeNull();
    expect(jobStatusColor("reopened")).toBeNull();
    expect(jobStatusColor("")).toBeNull();
    expect(jobStatusColor(null)).toBeNull();
    expect(jobStatusColor(undefined)).toBeNull();
  });

  it("K50_JOB_STATUS_BG is frozen (parity with the web helper)", () => {
    expect(Object.isFrozen(K50_JOB_STATUS_BG)).toBe(true);
  });

  it("mirrors the web helper hex values byte-for-byte", () => {
    // If the mobile hex ever drifts from the web hex the two
    // Schedule surfaces would render inconsistently — this test is
    // the parity gate.  The web values are hard-coded here as
    // literals to keep the mobile suite free of a web-app import.
    expect(K50_JOB_STATUS_BG).toEqual({
      open: "#D6F5EE",
      scheduled: "#D6F5EE",
      in_progress: "#FEF3C7",
      completed: "#FDECEC",
      cancelled: "#FECACA",
      skipped: "#FED7AA",
    });
  });
});
