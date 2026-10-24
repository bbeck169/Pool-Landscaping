/**
 * TD-pool-repair-completion-wizard-notes-photos-only · Feb-2026.
 *
 * Ticket H FE contract tests for ``<PoolChecklistWizard>``.
 *
 * Repair-tagged pool jobs skip the chemistry / chemicals / checklist
 * steps and land on step 4 (Photos).  Progress bar renders only
 * steps 4-6 ("Step 1 of 3"), Close Job is always valid (BE already
 * loosened the chemistry gate for ``work_class == "repair"``), and
 * the Required-Four hint never fires.  Service-tagged pool jobs
 * must be unaffected (full 6-step flow kept as a regression lock).
 *
 * A reclassified-mid-report case (persisted ``wizard_step == 2`` on
 * a now-``work_class == "repair"`` report) must emit a one-shot
 * ``onChange({ wizard_step: 4 })`` on mount so the DB cursor stays
 * fresh across remounts.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import "@/i18n";
import PoolChecklistWizard from "@/components/checklist/PoolChecklistWizard";

// Stub the heavy children — this suite only cares about the shell.
vi.mock("@/components/checklist/PoolChecklistForm", () => ({
  default: () => <div data-testid="pool-checklist-form-stub" />,
}));
vi.mock("@/components/checklist/PhotoUploader", () => ({
  default: () => <div data-testid="photo-uploader-stub" />,
}));
vi.mock("@/components/checklist/DirtyCloseConfirm", () => ({
  default: () => null,
}));


function _report({ work_class = null, step = null, readings = [] } = {}) {
  const r = {
    chemical_readings: readings,
    chemicals_added: [],
    checklist_items: [],
    photos: [],
    notes: "",
    internal_notes: "",
  };
  if (work_class !== null) r.work_class = work_class;
  if (step !== null) r.wizard_step = step;
  return r;
}


describe("Ticket H · PoolChecklistWizard · repair-mode step filter", () => {
  beforeEach(() => cleanup());

  // ─── Service job regression lock ──────────────────────────────
  it("service pool job: all 6 step dots render + 'Step 1 of 6' label", () => {
    const { getByTestId, queryByTestId } = render(
      <PoolChecklistWizard
        jobId="j-svc"
        customerId="c1"
        report={_report({ work_class: "service", step: 1 })}
        onChange={() => {}}
      />,
    );
    // All six progress-bar dots present.
    for (let n = 1; n <= 6; n++) {
      expect(getByTestId(`wizard-step-dot-${n}`)).toBeTruthy();
    }
    expect(getByTestId("wizard-progress").textContent).toContain("Step 1 of 6");
    // Body renders the delegated PoolChecklistForm (step 1 = Readings).
    expect(queryByTestId("pool-checklist-form-stub")).toBeTruthy();
  });

  it("service pool job: hint fires when Required Four incomplete", () => {
    const { getByTestId } = render(
      <PoolChecklistWizard
        jobId="j-svc"
        customerId="c1"
        report={_report({
          work_class: "service", step: 1,
          readings: [{ key: "free_chlorine", value: 2.5 }],
        })}
        onChange={() => {}}
      />,
    );
    expect(getByTestId("wizard-readings-hint")).toBeTruthy();
  });

  it("service pool job: Close Job stays data-close-valid='false' with no readings", () => {
    const { getByTestId } = render(
      <PoolChecklistWizard
        jobId="j-svc"
        customerId="c1"
        report={_report({
          work_class: "service", step: 6,
          readings: [{ key: "free_chlorine", value: 2.5 }],
        })}
        onChange={() => {}}
      />,
    );
    const btn = getByTestId("wizard-close-job");
    expect(btn.getAttribute("data-close-valid")).toBe("false");
  });

  // ─── Repair job filter ────────────────────────────────────────
  it("repair pool job: only steps 4/5/6 render + 'Step 1 of 3' label", () => {
    const { getByTestId, queryByTestId } = render(
      <PoolChecklistWizard
        jobId="j-rep"
        customerId="c1"
        report={_report({ work_class: "repair", step: 4 })}
        onChange={() => {}}
      />,
    );
    // Dots 1/2/3 are gone.
    for (const n of [1, 2, 3]) {
      expect(queryByTestId(`wizard-step-dot-${n}`)).toBeNull();
    }
    // Dots 4/5/6 remain.
    for (const n of [4, 5, 6]) {
      expect(getByTestId(`wizard-step-dot-${n}`)).toBeTruthy();
    }
    expect(getByTestId("wizard-progress").textContent).toContain("Step 1 of 3");
    // Landing step is 4 (Photos) — the wizard shell renders the
    // PhotoUploader directly, not the form stub.
    expect(getByTestId("wizard-step-body-4")).toBeTruthy();
    expect(queryByTestId("photo-uploader-stub")).toBeTruthy();
    expect(queryByTestId("pool-checklist-form-stub")).toBeNull();
  });

  it("repair pool job: Close Job always data-close-valid='true' (no chemistry)", () => {
    const { getByTestId } = render(
      <PoolChecklistWizard
        jobId="j-rep"
        customerId="c1"
        // Step 6 (last visible for repair) + readings deliberately
        // empty.  Service mode would gate on this; repair must not.
        report={_report({ work_class: "repair", step: 6 })}
        onChange={() => {}}
      />,
    );
    const btn = getByTestId("wizard-close-job");
    expect(btn.getAttribute("data-close-valid")).toBe("true");
  });

  it("repair pool job: Required-Four hint NEVER fires (chemistry step hidden)", () => {
    const { queryByTestId } = render(
      <PoolChecklistWizard
        jobId="j-rep"
        customerId="c1"
        // The hint is step-1 only, but just to be belt-and-braces
        // we also seed step=4 which is where repair jobs land.
        report={_report({
          work_class: "repair", step: 4,
          readings: [{ key: "free_chlorine", value: null }],
        })}
        onChange={() => {}}
      />,
    );
    expect(queryByTestId("wizard-readings-hint")).toBeNull();
  });

  // ─── Stale-cursor auto-advance ───────────────────────────────
  it("repair job with persisted wizard_step=2 fires one-shot onChange(wizard_step=4) on mount", () => {
    const onChange = vi.fn();
    render(
      <PoolChecklistWizard
        jobId="j-rep-stale"
        customerId="c1"
        report={_report({ work_class: "repair", step: 2 })}
        onChange={onChange}
      />,
    );
    // Called exactly once with the clamped cursor.
    const clampCalls = onChange.mock.calls.filter(
      (c) => c[0] && c[0].wizard_step === 4,
    );
    expect(clampCalls.length).toBe(1);
  });

  it("repair job with persisted wizard_step=1 clamps to 4 (not left at 1)", () => {
    const onChange = vi.fn();
    const { getByTestId } = render(
      <PoolChecklistWizard
        jobId="j-rep-stale-1"
        customerId="c1"
        report={_report({ work_class: "repair", step: 1 })}
        onChange={onChange}
      />,
    );
    expect(getByTestId("wizard-step-body-4")).toBeTruthy();
    const clampCalls = onChange.mock.calls.filter(
      (c) => c[0] && c[0].wizard_step === 4,
    );
    expect(clampCalls.length).toBe(1);
  });

  it("service job with persisted wizard_step=2 does NOT clamp (stays on step 2)", () => {
    const onChange = vi.fn();
    const { getByTestId } = render(
      <PoolChecklistWizard
        jobId="j-svc-ok"
        customerId="c1"
        report={_report({ work_class: "service", step: 2 })}
        onChange={onChange}
      />,
    );
    expect(getByTestId("wizard-step-body-2")).toBeTruthy();
    // No clamp fired — the service flow keeps all 6 steps.
    const clampCalls = onChange.mock.calls.filter(
      (c) => c[0] && typeof c[0].wizard_step === "number",
    );
    expect(clampCalls.length).toBe(0);
  });

  // ─── Predicate shape — defensive fallback to job.work_class ──
  it("picks up work_class from report.job.work_class when report.work_class is unset", () => {
    const r = _report({ step: 4 });
    delete r.work_class;
    r.job = { work_class: "repair" };
    const { queryByTestId } = render(
      <PoolChecklistWizard
        jobId="j-rep-jobwc"
        customerId="c1"
        report={r}
        onChange={() => {}}
      />,
    );
    // Dot 1 absent → repair filter engaged via the job fallback.
    expect(queryByTestId("wizard-step-dot-1")).toBeNull();
    expect(queryByTestId("wizard-step-dot-4")).toBeTruthy();
  });

  it("defaults to service flow when neither report.work_class nor job.work_class is set", () => {
    const r = _report({ step: 1 });
    delete r.work_class;
    const { queryByTestId } = render(
      <PoolChecklistWizard
        jobId="j-unknown"
        customerId="c1"
        report={r}
        onChange={() => {}}
      />,
    );
    // Full 6-step flow — defensive default.
    expect(queryByTestId("wizard-step-dot-1")).toBeTruthy();
    expect(queryByTestId("wizard-step-dot-6")).toBeTruthy();
  });
});
