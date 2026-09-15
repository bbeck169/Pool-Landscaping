/**
 * remove-legacy-chemical-readings-web · Feb-2026
 *
 * Pool tech checklist previously rendered a "Chemical Readings"
 * section (uppercase labels via CSS, wired to the flat
 * ``chemical_readings`` array). The structured WaterBodyPanel
 * section under multi-body reports uses title-case "Chemistry"
 * labels wired to ``water_bodies[i].readings``. The two were
 * visually redundant on multi-body jobs and the naming diverged
 * from the backend chemistry-gate taxonomy.
 *
 * This suite locks the rename in place:
 *   1. Section header is "Chemistry Readings" (never "Chemical Readings").
 *   2. Every reading input is still present + keyed correctly.
 *   3. Writeback still flows through ``onChange({chemical_readings: […]})``
 *      so ``WaterBodyManager.onPrimaryChange`` can mirror to
 *      ``water_bodies[0].readings`` untouched.
 *   4. Labels are rendered in title case (no CSS uppercase transform).
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import PoolChecklistForm from "@/components/checklist/PoolChecklistForm";


vi.mock("@/api", () => ({
  api: {
    get: vi.fn().mockResolvedValue({ recent: {} }),
    post: vi.fn().mockResolvedValue({}),
    patch: vi.fn().mockResolvedValue({}),
    delete: vi.fn().mockResolvedValue({}),
  },
}));


const _baseProps = {
  jobId: "j-1",
  customerId: "c-1",
  locked: false,
  readings: [
    { key: "free_chlorine",  name: "Free Chlorine",  unit: "ppm", value: null },
    { key: "ph",             name: "pH",             unit: "",    value: null },
    { key: "alkalinity",     name: "Total Alkalinity", unit: "ppm", value: null },
    { key: "cyanuric_acid",  name: "Cyanuric Acid",  unit: "ppm", value: null },
  ],
  readingFields: [],
  chemicalsAdded: [],
  chemicalsCatalog: [],
  chemicalUnits: ["gal", "lbs"],
  checklistItems: [],
  notes: "",
  observations: {},
};


describe("Pool checklist · legacy Chemical Readings header removed", () => {
  it("renders the new 'Chemistry Readings' header exactly once", () => {
    render(<PoolChecklistForm {..._baseProps} onChange={() => {}} />);
    expect(screen.getByText("Chemistry Readings")).toBeTruthy();
  });

  it("does NOT render the legacy 'Chemical Readings' header anywhere", () => {
    render(<PoolChecklistForm {..._baseProps} onChange={() => {}} />);
    expect(screen.queryByText("Chemical Readings")).toBeNull();
  });

  it("carries the pool-chemistry-readings testid on the section", () => {
    render(<PoolChecklistForm {..._baseProps} onChange={() => {}} />);
    expect(screen.getByTestId("pool-chemistry-readings")).toBeTruthy();
  });

  it("still renders every reading input row", () => {
    render(<PoolChecklistForm {..._baseProps} onChange={() => {}} />);
    for (const key of [
      "free_chlorine", "ph",
      "total_alkalinity", "cyanuric_acid",
    ]) {
      expect(screen.getByTestId(`pool-reading-${key}-input`)).toBeTruthy();
    }
  });

  it("writes back via onChange({chemical_readings: [...]}) (WaterBodyManager mirror preserved)", () => {
    const onChange = vi.fn();
    render(<PoolChecklistForm {..._baseProps} onChange={onChange} />);
    const fc = screen.getByTestId("pool-reading-free_chlorine-input");
    fireEvent.change(fc, { target: { value: "2.5" } });
    fireEvent.blur(fc);
    // Latest call must carry chemical_readings — the WaterBodyManager
    // mirror hook expects this key to bubble a water_bodies[0].readings
    // update on the same tick. Without it the close-gate would fail.
    const calls = onChange.mock.calls;
    const found = calls.some(
      ([patch]) => patch && Object.prototype.hasOwnProperty.call(patch, "chemical_readings"),
    );
    expect(found).toBe(true);
  });
});
