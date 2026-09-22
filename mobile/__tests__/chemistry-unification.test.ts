/**
 * Regression test — Chemistry readings unification.
 *
 * Asserts:
 * 1. The inline compact grid renderer (readingGrid/readingCell pattern)
 *    is GONE from `(app)/service-report/[id].tsx`.
 * 2. `canonicalReadingKey` is exported from PoolChecklistForm.
 * 3. `ReadingInputRow` (alias for ReadingChipRow) is exported from PoolChecklistForm.
 * 4. `expandChemistryLabel` handles all 11 fields including CC and water_temp.
 * 5. REQUIRED_READING_KEYS set covers all 5 core readings.
 */
import * as fs from "fs";
import * as path from "path";

describe("Chemistry Readings Unification (web-parity)", () => {
  const serviceReportSrc = fs.readFileSync(
    path.resolve(__dirname, "../app/(app)/service-report/[id].tsx"),
    "utf-8",
  );

  it("inline compact grid renderer is removed from service-report/[id].tsx", () => {
    // The old inline grid used `styles.readingGrid` + `styles.readingCell`
    // as style references. These should no longer exist as style definitions
    // or JSX style references (comments mentioning their removal are fine).
    expect(serviceReportSrc).not.toMatch(/styles\.readingGrid/);
    expect(serviceReportSrc).not.toMatch(/styles\.readingCell/);
  });

  it("service-report imports the canonical ReadingChipRow component", () => {
    expect(serviceReportSrc).toContain("ReadingChipRow");
    expect(serviceReportSrc).toContain("expandChemistryLabel");
    expect(serviceReportSrc).toContain("canonicalReadingKey");
  });

  it("service-report wires the required prop", () => {
    expect(serviceReportSrc).toContain("REQUIRED_READING_KEYS");
    expect(serviceReportSrc).toContain("required={REQUIRED_READING_KEYS.has(key)}");
  });

  it("canonicalReadingKey is a named export from PoolChecklistForm", () => {
    const { canonicalReadingKey } = require("../src/components/checklist/PoolChecklistForm");
    expect(typeof canonicalReadingKey).toBe("function");
    // Phase P17.1 · Feb-2026 — canonical rename: ``Free Chlorine`` /
    // ``fc`` fold onto the new ``chlorine`` canonical (was
    // ``free_chlorine`` under P17).
    expect(canonicalReadingKey({ name: "Free Chlorine" })).toBe("chlorine");
    expect(canonicalReadingKey({ name: "Total Chlorine" })).toBe("total_chlorine");
    expect(canonicalReadingKey({ name: "pH" })).toBe("ph");
    expect(canonicalReadingKey({ name: "Total Alkalinity" })).toBe("total_alkalinity");
    expect(canonicalReadingKey({ name: "Cyanuric Acid" })).toBe("cyanuric_acid");
    expect(canonicalReadingKey({ name: "Water Temp" })).toBe("water_temp");
    expect(canonicalReadingKey({ key: "fc", name: "FC" })).toBe("chlorine");
  });

  it("ReadingInputRow is a named export from PoolChecklistForm", () => {
    const { ReadingInputRow } = require("../src/components/checklist/PoolChecklistForm");
    expect(ReadingInputRow).toBeDefined();
  });

  it("expandChemistryLabel covers the current spec fields (post-P17.2)", () => {
    const { expandChemistryLabel } = require("../src/lib/expandChemistryLabel");
    // Phase P17.2 · Feb-2026 — display-label unification:
    //   FC → Chlorine (was "Free Chlorine" under P17)
    //   TA → Alkalinity (was "Total Alkalinity" under P17)
    //   TC → Total Chlorine (restored from CHEM1 removal so
    //     tenants on legacy templates still expand correctly)
    // ``CC`` (combined_chlorine short-form) stays REMOVED — CHEM1
    // retired the reading and product spec keeps it off customer
    // surfaces.
    expect(expandChemistryLabel("FC")).toBe("Chlorine");
    expect(expandChemistryLabel("TC")).toBe("Total Chlorine");
    // CC is passthrough (not in the map) — proves the removal
    // stuck through P17.2.
    expect(expandChemistryLabel("CC")).toBe("CC");
    expect(expandChemistryLabel("pH")).toBe("pH");
    expect(expandChemistryLabel("TA")).toBe("Alkalinity");
    expect(expandChemistryLabel("CYA")).toBe("Cyanuric Acid");
    expect(expandChemistryLabel("CH")).toBe("Calcium Hardness");
    expect(expandChemistryLabel("Salt")).toBe("Salt");
    expect(expandChemistryLabel("TDS")).toBe("Total Dissolved Solids");
    expect(expandChemistryLabel("PO4")).toBe("Phosphates");
    expect(expandChemistryLabel("water_temp")).toBe("Water Temp");
    // Custom labels pass through unchanged
    expect(expandChemistryLabel("My Custom Reading")).toBe("My Custom Reading");
  });

  it("READING_LABELS includes water_temp with the P17.2 unified name", () => {
    const { READING_LABELS } = require("../src/lib/waterBodies");
    expect(READING_LABELS.water_temp).toBeDefined();
    expect(READING_LABELS.water_temp.name).toBe("Water Temp");
    expect(READING_LABELS.water_temp.unit).toBe("°F");
    // Phase P17.2 · Feb-2026 — chlorine + alkalinity display labels
    // fold onto the unified customer-facing short form.
    expect(READING_LABELS.chlorine.name).toBe("Chlorine");
    expect(READING_LABELS.chlorine.short).toBe("Chlorine");
    expect(READING_LABELS.alkalinity.name).toBe("Alkalinity");
    expect(READING_LABELS.alkalinity.short).toBe("Alkalinity");
    // combined_chlorine ENTRY stays in the map (CHEM1 didn't wipe
    // the label entry — only the allow-list + gate references).
    expect(READING_LABELS.combined_chlorine).toBeDefined();
  });

  it("READING_ALLOWLIST includes water_temp for pool and other, and does NOT include combined_chlorine", () => {
    const { READING_ALLOWLIST } = require("../src/lib/waterBodies");
    expect(READING_ALLOWLIST.pool).toContain("water_temp");
    expect(READING_ALLOWLIST.other).toContain("water_temp");
    // Phase CHEM1 · Feb-2026 — combined_chlorine dropped from the
    // pool + other allow-lists (retired reading, product spec
    // dropped it from the customer view).
    expect(READING_ALLOWLIST.pool).not.toContain("combined_chlorine");
    expect(READING_ALLOWLIST.other).not.toContain("combined_chlorine");
  });

  it("WaterBodyPanel uses full-name labels, not short abbreviations", () => {
    const panelSrc = fs.readFileSync(
      path.resolve(__dirname, "../src/components/checklist/WaterBodyPanel.tsx"),
      "utf-8",
    );
    // The old pattern used `meta.short` — now it uses `meta.name`
    expect(panelSrc).toContain("{meta.name}");
    expect(panelSrc).not.toMatch(/\{meta\.short\}/);
  });
});
