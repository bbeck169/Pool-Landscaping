/**
 * Phase CW1 · Feb-2026 — PoolChecklistWizard `readingsAllAnswered`
 * gate is loosened to enforce only the Required Four (Free Chlorine,
 * pH, Alkalinity, Cyanuric Acid). Other readings — Hardness, Salt,
 * Phosphates, TDS, tenant extras — may be truly blank.
 *
 * These tests drive the wizard through a synthetic report and assert:
 *   1. Only the Required Four block the Close Job button.
 *   2. Canonicalisation (``alkalinity``/``total_alkalinity``,
 *      ``cya``/``cyanuric_acid``) mirrors the CHEM1 rule.
 *   3. ``0`` in Free Chlorine counts as answered.
 *   4. ``""`` / ``null`` / whitespace-only do NOT count as answered.
 *   5. Existing ``data-testid`` attributes preserved for E2E parity.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import "@/i18n";
import PoolChecklistWizard from "@/components/checklist/PoolChecklistWizard";

// The wizard mounts PoolChecklistForm on step 1 — that renders a
// complex readings surface with API calls. Stub it out; we only care
// about the gate + hint here.
vi.mock("@/components/checklist/PoolChecklistForm", () => ({
  default: () => <div data-testid="pool-checklist-form-stub" />,
}));
vi.mock("@/components/checklist/PhotoUploader", () => ({
  default: () => <div data-testid="photo-uploader-stub" />,
}));
vi.mock("@/components/checklist/DirtyCloseConfirm", () => ({
  default: () => null,
}));

function _report({ readings = [], step = 1, photos = [] } = {}) {
  return {
    wizard_step: step,
    chemical_readings: readings,
    photos,
    checklist_items: [],
    notes: "",
    internal_notes: "",
  };
}

function _row(key, value, extras = {}) {
  return { key, value, ...extras };
}

const REQ_FILLED_ROWS = [
  _row("free_chlorine", 2.5),
  _row("ph", 7.4),
  _row("alkalinity", 90),
  _row("cyanuric_acid", 45),
];

describe("PoolChecklistWizard · CW1 Required-Four gate", () => {
  beforeEach(() => cleanup());

  it("enables Close Job when only the Required Four are filled", () => {
    const { getByTestId, queryByTestId } = render(
      <PoolChecklistWizard
        jobId="j1"
        customerId="c1"
        report={_report({
          step: 6,
          readings: [
            ...REQ_FILLED_ROWS,
            _row("hardness", ""),
            _row("salt", null),
            _row("phosphates", "   "),
            _row("tds", ""),
          ],
        })}
        onChange={() => {}}
        onSaveExit={() => {}}
        onCloseJob={() => {}}
      />,
    );
    const btn = getByTestId("wizard-close-job");
    // Gate state exposed via ``data-close-valid`` — the button is
    // never DOM-disabled (the click handler nudges the tech back to
    // step 1 with an alert instead of silently swallowing).
    expect(btn.getAttribute("data-close-valid")).toBe("true");
    // No blocking hint shown on step 6.
    expect(queryByTestId("wizard-readings-hint")).toBeNull();
  });

  it("disables Close Job when Free Chlorine is missing", () => {
    const rows = [
      _row("free_chlorine", ""),           // MISSING
      _row("ph", 7.4),
      _row("alkalinity", 90),
      _row("cyanuric_acid", 45),
    ];
    const { getByTestId } = render(
      <PoolChecklistWizard jobId="j" customerId="c"
        report={_report({ step: 6, readings: rows })}
        onChange={() => {}} onSaveExit={() => {}} onCloseJob={() => {}} />,
    );
    // The Close Job button is never DOM-``disabled`` — the click
    // handler routes the tech back to step 1 with an alert instead.
    // The gate state is exposed via ``data-close-valid`` for test
    // + E2E observation.
    expect(getByTestId("wizard-close-job")
      .getAttribute("data-close-valid")).toBe("false");
  });

  it("`total_alkalinity` filled satisfies the `alkalinity` requirement (canonicalisation)", () => {
    const rows = [
      _row("free_chlorine", 2.5),
      _row("ph", 7.4),
      _row("total_alkalinity", 90),         // aliased to alkalinity
      _row("cyanuric_acid", 45),
    ];
    const { getByTestId } = render(
      <PoolChecklistWizard jobId="j" customerId="c"
        report={_report({ step: 6, readings: rows })}
        onChange={() => {}} onSaveExit={() => {}} onCloseJob={() => {}} />,
    );
    expect(getByTestId("wizard-close-job")
      .getAttribute("data-close-valid")).toBe("true");
  });

  it("`cya` filled satisfies the `cyanuric_acid` requirement (canonicalisation)", () => {
    const rows = [
      _row("free_chlorine", 2.5),
      _row("ph", 7.4),
      _row("alkalinity", 90),
      _row("cya", 45),                       // aliased to cyanuric_acid
    ];
    const { getByTestId } = render(
      <PoolChecklistWizard jobId="j" customerId="c"
        report={_report({ step: 6, readings: rows })}
        onChange={() => {}} onSaveExit={() => {}} onCloseJob={() => {}} />,
    );
    expect(getByTestId("wizard-close-job")
      .getAttribute("data-close-valid")).toBe("true");
  });

  it("`0` in Free Chlorine counts as a valid answered reading", () => {
    const rows = [
      _row("free_chlorine", 0),              // Zero is a REAL reading
      _row("ph", 7.4),
      _row("alkalinity", 90),
      _row("cyanuric_acid", 45),
    ];
    const { getByTestId } = render(
      <PoolChecklistWizard jobId="j" customerId="c"
        report={_report({ step: 6, readings: rows })}
        onChange={() => {}} onSaveExit={() => {}} onCloseJob={() => {}} />,
    );
    expect(getByTestId("wizard-close-job")
      .getAttribute("data-close-valid")).toBe("true");
  });

  it("whitespace-only / null / \"\" do NOT count as answered for the Required Four", () => {
    for (const blankValue of ["", null, "   "]) {
      cleanup();
      const rows = [
        _row("free_chlorine", 2.5),
        _row("ph", blankValue),              // MISSING per CHEM1 rule
        _row("alkalinity", 90),
        _row("cyanuric_acid", 45),
      ];
      const { getByTestId } = render(
        <PoolChecklistWizard jobId="j" customerId="c"
          report={_report({ step: 6, readings: rows })}
          onChange={() => {}} onSaveExit={() => {}} onCloseJob={() => {}} />,
      );
      // Same rationale as above — check the CW1 data attribute.
      expect(getByTestId("wizard-close-job")
        .getAttribute("data-close-valid")).toBe("false");
    }
  });

  it("the loosened hint text is shown on step 1 when a Required-Four row is blank", () => {
    const rows = [
      _row("free_chlorine", ""),             // blank → hint fires
      _row("ph", 7.4),
      _row("alkalinity", 90),
      _row("cyanuric_acid", 45),
    ];
    const { getByTestId } = render(
      <PoolChecklistWizard jobId="j" customerId="c"
        report={_report({ step: 1, readings: rows })}
        onChange={() => {}} onSaveExit={() => {}} onCloseJob={() => {}} />,
    );
    const hint = getByTestId("wizard-readings-hint");
    // Loosened wording — mentions the Required Four, not "each row".
    expect(hint.textContent).toMatch(/Free Chlorine/i);
    expect(hint.textContent).toMatch(/pH/);
    expect(hint.textContent).toMatch(/Alkalinity/i);
    expect(hint.textContent).toMatch(/Cyanuric Acid/i);
    // The pre-CW1 "each row before closing" wording is gone.
    expect(hint.textContent).not.toMatch(/each row/i);
  });

  it("no hint shown on step 1 when the Required Four are all filled — even if optional rows are blank", () => {
    const rows = [
      ...REQ_FILLED_ROWS,
      _row("hardness", ""),                   // optional blanks OK
      _row("salt", null),
    ];
    const { queryByTestId } = render(
      <PoolChecklistWizard jobId="j" customerId="c"
        report={_report({ step: 1, readings: rows })}
        onChange={() => {}} onSaveExit={() => {}} onCloseJob={() => {}} />,
    );
    // Hint anchor is unconditionally rendered but with empty text
    // — assert the text is empty, not that the node is missing.
    const hint = queryByTestId("wizard-readings-hint");
    expect(hint?.textContent || "").toBe("");
  });

  it("empty readings list passes (no rows to enforce)", () => {
    const { getByTestId } = render(
      <PoolChecklistWizard jobId="j" customerId="c"
        report={_report({ step: 6, readings: [] })}
        onChange={() => {}} onSaveExit={() => {}} onCloseJob={() => {}} />,
    );
    expect(getByTestId("wizard-close-job")
      .getAttribute("data-close-valid")).toBe("true");
  });

  it("preserves the wizard-close-job data-testid for E2E parity", () => {
    const { getByTestId } = render(
      <PoolChecklistWizard jobId="j" customerId="c"
        report={_report({ step: 6, readings: REQ_FILLED_ROWS })}
        onChange={() => {}} onSaveExit={() => {}} onCloseJob={() => {}} />,
    );
    expect(getByTestId("wizard-close-job")).toBeTruthy();
    expect(getByTestId("pool-checklist-wizard")).toBeTruthy();
  });
});
