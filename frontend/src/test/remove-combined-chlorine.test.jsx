/**
 * Feb-2026 · Remove-combined-chlorine (web).
 *
 * After the "hide entire Chemical Readings section" dispatch was
 * reverted, the ONLY chemistry-related field removed on web is the
 * Combined Chlorine input. This test locks in the post-revert +
 * post-removal contract:
 *
 *   1. The "Chemical Readings" section renders (regression guard
 *      for the revert).
 *   2. Free Chlorine, Total Chlorine, pH, Total Alkalinity, and
 *      Cyanuric Acid inputs render.
 *   3. Combined Chlorine input DOES NOT render, even when the
 *      backend template supplies it AND a saved value is present.
 *   4. onChange payload for `chemical_readings` does NOT include a
 *      combined_chlorine row when the user edits another field —
 *      option (a) drop-from-payload semantics.
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

const READING_FIELDS = [
  { key: "free_chlorine",     name: "Free Chlorine",     unit: "ppm" },
  { key: "total_chlorine",    name: "Total Chlorine",    unit: "ppm" },
  { key: "combined_chlorine", name: "Combined Chlorine", unit: "ppm" },
  { key: "ph",                name: "pH",                unit: "pH"  },
  { key: "total_alkalinity",  name: "Total Alkalinity",  unit: "ppm" },
  { key: "cyanuric_acid",     name: "Cyanuric Acid",     unit: "ppm" },
];

// A saved reading with a real combined_chlorine value — simulates
// a historic record. The form MUST NOT render the input, and the
// value MUST NOT surface in a subsequent onChange payload.
const SAVED_READINGS = [
  { key: "free_chlorine",     name: "Free Chlorine",     unit: "ppm", value: 3   },
  { key: "combined_chlorine", name: "Combined Chlorine", unit: "ppm", value: 0.7 },
];

const baseProps = {
  jobId: "job-1",
  customerId: "cust-1",
  locked: false,
  readingFields: READING_FIELDS,
  readings: SAVED_READINGS,
  chemicalsAdded: [],
  chemicalsCatalog: [],
  chemicalUnits: ["gal", "lbs", "oz", "tabs"],
  checklistItems: [],
  notes: "",
  observations: {},
};

describe("Job Checklist · Combined Chlorine removed (web)", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("renders the 'Chemistry Readings' heading (post-Feb-2026 rename)", () => {
    // Feb-2026 · Legacy "Chemical Readings" header was renamed to
    // "Chemistry Readings" to match the structured WaterBodyPanel
    // section. Regression guard: the LEGACY uppercase header must
    // NOT appear anywhere on the primary body render.
    render(<PoolChecklistForm {...baseProps} onChange={() => {}} />);
    expect(screen.getByText("Chemistry Readings")).toBeTruthy();
    expect(screen.queryByText("Chemical Readings")).toBeNull();
  });

  it("renders the five remaining chem inputs", () => {
    render(<PoolChecklistForm {...baseProps} onChange={() => {}} />);
    for (const k of ["free_chlorine", "total_chlorine", "ph",
                     "total_alkalinity", "cyanuric_acid"]) {
      expect(screen.getByTestId(`pool-reading-${k}-input`)).toBeTruthy();
    }
  });

  it("does NOT render the Combined Chlorine input even when supplied by backend + saved value", () => {
    render(<PoolChecklistForm {...baseProps} onChange={() => {}} />);
    expect(screen.queryByTestId("pool-reading-combined_chlorine-input")).toBeNull();
    expect(screen.queryByTestId("pool-reading-combined_chlorine-slider")).toBeNull();
    expect(screen.queryByText("Combined Chlorine")).toBeNull();
  });

  it("onChange payload omits combined_chlorine when another reading is edited", () => {
    const onChange = vi.fn();
    render(<PoolChecklistForm {...baseProps} onChange={onChange} />);
    const fc = screen.getByTestId("pool-reading-free_chlorine-input");
    fireEvent.change(fc, { target: { value: "2.5" } });
    fireEvent.blur(fc);
    expect(onChange).toHaveBeenCalled();
    const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect(lastCall).toHaveProperty("chemical_readings");
    const keys = (lastCall.chemical_readings || []).map(
      (r) => String(r.key || r.name || "").toLowerCase(),
    );
    expect(keys.includes("combined_chlorine")).toBe(false);
    expect(keys.includes("combined chlorine")).toBe(false);
    // Other core readings still round-trip through the payload.
    expect(keys.includes("free_chlorine")).toBe(true);
    expect(keys.includes("total_chlorine")).toBe(true);
    expect(keys.includes("ph")).toBe(true);
  });
});
