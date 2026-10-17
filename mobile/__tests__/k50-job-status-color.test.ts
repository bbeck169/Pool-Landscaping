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
    // Feb-2026 finished-state styling (web e62babc5f) — finished → gray-100.
    expect(jobStatusColor("completed")).toBe("#F3F4F6");
    expect(jobStatusColor("cancelled")).toBe("#F3F4F6");
    expect(jobStatusColor("skipped")).toBe("#F3F4F6");
    expect(jobStatusColor("missed")).toBe("#FCA5A5");
  });

  it("resolves legacy aliases (active / closed / canceled)", () => {
    expect(jobStatusColor("active")).toBe("#FEF3C7");
    expect(jobStatusColor("closed")).toBe("#F3F4F6");
    expect(jobStatusColor("done")).toBe("#F3F4F6");
    expect(jobStatusColor("canceled")).toBe("#F3F4F6");
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
    expect(jobStatusColor("COMPLETED")).toBe("#F3F4F6");
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

  it("mirrors the web helper hex values byte-for-byte (web e62babc5f)", () => {
    // Parity gate with ``frontend/src/lib/jobStatus.js`` — no divergence.
    expect(K50_JOB_STATUS_BG).toEqual({
      open: "#EAF7F0",
      scheduled: "#EAF7F0",
      in_progress: "#FEF3C7",
      completed: "#F3F4F6",
      cancelled: "#F3F4F6",
      skipped: "#F3F4F6",
      missed: "#FCA5A5",
    });
    // Read the live web map so a future web edit fails this gate.
    const fs = require("fs");
    const path = require("path");
    const web = fs.readFileSync(path.resolve(__dirname, "../../frontend/src/lib/jobStatus.js"), "utf8");
    const block = web.slice(web.indexOf("K50_JOB_STATUS_BG = Object.freeze({"), web.indexOf("});", web.indexOf("K50_JOB_STATUS_BG = Object.freeze({")));
    const webMap: Record<string, string> = {};
    for (const m of block.matchAll(/^\s*([a-z_]+):\s*"(#[0-9A-Fa-f]{6})"/gm)) webMap[m[1]] = m[2];
    expect(webMap).toEqual({ ...K50_JOB_STATUS_BG });
  });
});
