/**
 * Feb-2026 · Hide-web-chem-readings — verifies the Chemical Readings
 * section on the Job Checklist is hidden on the web while the
 * `SHOW_CHECKLIST_CHEMICAL_READINGS` feature flag defaults to `false`.
 *
 * Coverage:
 *   1. The "Chemical Readings" heading is NOT rendered.
 *   2. Chem input testids (total_chlorine, free_chlorine, ph,
 *      total_alkalinity, cyanuric_acid) are NOT rendered.
 *   3. The related "Visible algae on walls" card and the reclassify
 *      picker (which live inside the same wizard-section) are NOT
 *      rendered.
 *   4. The parent `PoolChecklistWizard` can submit via "Close Job"
 *      with an empty `chemical_readings` payload — the readings
 *      validation must not block submission when the section is
 *      hidden.
 *
 * Backend schema + endpoints are unchanged; this is a client-side
 * hide only. Flip the flag in `config/featureFlags.js` to re-enable.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

vi.mock("@/api", () => ({
  api: {
    get: vi.fn(async () => ({ readings: {}, recent_readings: {} })),
    post: vi.fn(async () => ({ recommendations: [] })),
  },
}));

import PoolChecklistForm from "@/components/checklist/PoolChecklistForm";
import PoolChecklistWizard from "@/components/checklist/PoolChecklistWizard";

const baseFormProps = {
  jobId: "job-1",
  customerId: "cust-1",
  locked: false,
  readingFields: [
    { key: "free_chlorine",    name: "Free Chlorine",    unit: "ppm" },
    { key: "total_chlorine",   name: "Total Chlorine",   unit: "ppm" },
    { key: "ph",               name: "pH",               unit: "pH"  },
    { key: "total_alkalinity", name: "Total Alkalinity", unit: "ppm" },
    { key: "cyanuric_acid",    name: "Cyanuric Acid",    unit: "ppm" },
  ],
  readings: [],
  chemicalsAdded: [],
  chemicalsCatalog: [],
  chemicalUnits: ["gal", "lbs", "oz", "tabs"],
  checklistItems: [],
  notes: "",
  observations: {},
  onChange: () => {},
};

describe("Job Checklist · Chemical Readings hidden by feature flag", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("does not render the 'Chemical Readings' heading", () => {
    render(<PoolChecklistForm {...baseFormProps} />);
    expect(screen.queryByText("Chemical Readings")).toBeNull();
  });

  it("does not render the core chemical input rows or unit labels", () => {
    render(<PoolChecklistForm {...baseFormProps} />);
    for (const k of ["free_chlorine", "total_chlorine", "ph",
                     "total_alkalinity", "cyanuric_acid"]) {
      expect(screen.queryByTestId(`pool-reading-${k}-input`)).toBeNull();
      expect(screen.queryByTestId(`pool-reading-${k}-slider`)).toBeNull();
    }
  });

  it("does not render nested section elements (visible-algae, reclassify picker)", () => {
    render(
      <PoolChecklistForm
        {...baseFormProps}
        readingFields={[]}
        template="generic"
        canEditServiceType={true}
        onReclassify={() => {}}
      />,
    );
    expect(screen.queryByTestId("pool-visible-algae-card")).toBeNull();
    expect(screen.queryByTestId("pool-service-type-picker-block")).toBeNull();
  });

  it("wizard 'Close Job' fires with empty chemical_readings (validation not blocking)", () => {
    const onCloseJob = vi.fn();
    render(
      <PoolChecklistWizard
        jobId="job-1"
        customerId="cust-1"
        locked={false}
        report={{ wizard_step: 6, chemical_readings: [], photos: [] }}
        onChange={() => {}}
        onSaveExit={() => {}}
        onCloseJob={onCloseJob}
        submitting={false}
      />,
    );
    const btn = screen.getByTestId("wizard-close-job");
    // Should be enabled + green (closeJobValid === true).
    expect(btn.getAttribute("disabled")).toBeNull();
    fireEvent.click(btn);
    expect(onCloseJob).toHaveBeenCalledTimes(1);
    // No "readings-hint" surface either.
    expect(screen.queryByTestId("wizard-readings-hint")).toBeNull();
  });
});
