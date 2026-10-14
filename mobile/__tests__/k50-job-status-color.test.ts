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
    expect(jobStatusColor("open")).toBe("#EAF7F0");
    expect(jobStatusColor("scheduled")).toBe("#EAF7F0");
    expect(jobStatusColor("in_progress")).toBe("#FEF3C7");
    // Oct-2026 mobile hotfix — completed recedes to soft green emerald-50 (web keeps #ff4542).
    expect(jobStatusColor("completed")).toBe("#ECFDF5");
    expect(jobStatusColor("cancelled")).toBe("#FECACA");
    expect(jobStatusColor("skipped")).toBe("#FED7AA");
  });

  it("resolves legacy aliases (active / closed / canceled)", () => {
    expect(jobStatusColor("active")).toBe("#FEF3C7");
    expect(jobStatusColor("closed")).toBe("#ECFDF5");
    expect(jobStatusColor("done")).toBe("#ECFDF5");
    expect(jobStatusColor("canceled")).toBe("#FECACA");
  });

  it("K57 · Feb-2026 — ``pending`` resolves to the ``open`` bucket (#EAF7F0)", () => {
    // Parity with the web helper — see
    // ``frontend/src/test/k50-theming.test.js`` for the field-report
    // context.  Mobile is the surface where the bug was reported, so
    // this assertion is the primary regression gate.
    expect(jobStatusColor("pending")).toBe("#EAF7F0");
    // Case-insensitivity — helper lowercases + trims input.
    expect(jobStatusColor("Pending")).toBe("#EAF7F0");
    expect(jobStatusColor("PENDING")).toBe("#EAF7F0");
  });

  it("is case + whitespace insensitive", () => {
    expect(jobStatusColor("  In_Progress ")).toBe("#FEF3C7");
    expect(jobStatusColor("COMPLETED")).toBe("#ECFDF5");
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

  it("mirrors the web helper hex values byte-for-byte — EXCEPT completed", () => {
    // Parity gate with ``frontend/src/lib/jobStatus.js``. One deliberate
    // divergence: Oct-2026 mobile hotfix recedes ``completed`` to
    // soft green #ECFDF5 (web stays coral-red #ff4542). Every other key
    // must still match web byte-for-byte.
    expect(K50_JOB_STATUS_BG).toEqual({
      open: "#EAF7F0",
      scheduled: "#EAF7F0",
      in_progress: "#FEF3C7",
      completed: "#ECFDF5",
      cancelled: "#FECACA",
      skipped: "#FED7AA",
    });
  });
});
