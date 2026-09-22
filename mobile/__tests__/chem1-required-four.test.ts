/**
 * Phase CHEM1 — Remove total_chlorine + relax non-required chemistry.
 *
 * Tests:
 *   1. READING_ALLOWLIST for "pool" does NOT include total_chlorine
 *   2. READING_REQUIRED for "pool" only contains the Required Four
 *   3. READING_REQUIRED for "spa" also enforces the Required Four (per-body)
 *   4. missingRequiredReadings returns empty when only the Required Four are filled
 *   5. missingRequiredReadings does NOT flag optional fields left blank
 *   6. READING_LABELS does not contain total_chlorine
 */
import {
  READING_ALLOWLIST,
  READING_REQUIRED,
  READING_LABELS,
  missingRequiredReadings,
} from "../src/lib/waterBodies";

// Phase P17.1 · Feb-2026 — canonical rename: ``free_chlorine`` →
// ``chlorine``. Legacy source spellings remain in ALIAS_MAP for
// read-path compatibility; Required Four now emits ``chlorine``.
const REQUIRED_FOUR = ["chlorine", "ph", "alkalinity", "cyanuric_acid"];

describe("Phase CHEM1 — total_chlorine removed + Required Four only", () => {

  it("READING_ALLOWLIST for pool does NOT include total_chlorine", () => {
    expect(READING_ALLOWLIST.pool).not.toContain("total_chlorine");
  });

  it("READING_ALLOWLIST for other does NOT include total_chlorine", () => {
    expect(READING_ALLOWLIST.other).not.toContain("total_chlorine");
  });

  it("READING_REQUIRED for pool contains exactly the Required Four", () => {
    expect(READING_REQUIRED.pool).toHaveLength(4);
    expect([...READING_REQUIRED.pool].sort()).toEqual([...REQUIRED_FOUR].sort());
  });

  it("READING_REQUIRED for spa is empty (no gating)", () => {
    expect(READING_REQUIRED.spa).toEqual([]);
  });

  it("READING_REQUIRED for water_feature is empty", () => {
    expect(READING_REQUIRED.water_feature).toEqual([]);
  });

  it("READING_REQUIRED for fountain is empty", () => {
    expect(READING_REQUIRED.fountain).toEqual([]);
  });

  it("READING_REQUIRED for other is empty", () => {
    expect(READING_REQUIRED.other).toEqual([]);
  });

  it("READING_LABELS does not contain total_chlorine", () => {
    expect(READING_LABELS).not.toHaveProperty("total_chlorine");
  });

  it("missingRequiredReadings returns empty when Required Four are filled", () => {
    const body = {
      type: "pool",
      label: "Main Pool",
      readings: [
        // Phase P17.1 · Feb-2026 — canonical rename.
        { key: "chlorine", value: 3 },
        { key: "ph", value: 7.6 },
        { key: "alkalinity", value: 100 },
        { key: "cyanuric_acid", value: 70 },
      ],
    } as any;
    expect(missingRequiredReadings(body)).toEqual([]);
  });

  it("missingRequiredReadings does NOT flag optional fields left blank", () => {
    const body = {
      type: "pool",
      label: "Main Pool",
      readings: [
        // Phase P17.1 · Feb-2026 — canonical rename.
        { key: "chlorine", value: 3 },
        { key: "ph", value: 7.6 },
        { key: "alkalinity", value: 100 },
        { key: "cyanuric_acid", value: 70 },
        // calcium_hardness, salt, tds, phosphates, water_temp all missing
      ],
    } as any;
    const missing = missingRequiredReadings(body);
    expect(missing).toEqual([]);
    // Specifically should NOT contain any optional field
    expect(missing).not.toContain("calcium_hardness");
    expect(missing).not.toContain("salt");
    expect(missing).not.toContain("tds");
    expect(missing).not.toContain("phosphates");
    expect(missing).not.toContain("water_temp");
    expect(missing).not.toContain("total_chlorine");
  });

  it("missingRequiredReadings flags missing Required Four fields", () => {
    const body = {
      type: "pool",
      label: "Main Pool",
      readings: [
        // Phase P17.1 · Feb-2026 — canonical rename.
        { key: "chlorine", value: 3 },
        // ph, alkalinity, cyanuric_acid missing
      ],
    } as any;
    const missing = missingRequiredReadings(body);
    expect(missing).toContain("ph");
    expect(missing).toContain("alkalinity");
    expect(missing).toContain("cyanuric_acid");
    expect(missing).not.toContain("total_chlorine");
  });

  it("spa body with ALL readings blank triggers no required-field warning", () => {
    const body = { type: "spa", label: "Hot Tub", readings: [] } as any;
    expect(missingRequiredReadings(body)).toEqual([]);
  });

  it("other body with ALL readings blank triggers no required-field warning", () => {
    const body = { type: "other", label: "Pond", readings: [] } as any;
    expect(missingRequiredReadings(body)).toEqual([]);
  });
});
