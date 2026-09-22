/**
 * Phase P17 · Feb-2026 · P0 HOTFIX — Chemistry Gate Key Unification.
 * Phase P17.1 · Feb-2026 — canonical rename: `free_chlorine` →
 * `chlorine`.  Legacy spellings (`free_chlorine`, `free_cl`, `freecl`,
 * `fc`) remain as SOURCE aliases pointing at the new canonical
 * `chlorine`; the mobile helper's normalize output now keys on
 * `chlorine` end-to-end.
 *
 * Mobile mirror of backend/tests/test_p17_chemistry_gate_aliases.py
 * and frontend/src/test/p17-chemistry-gate.test.js.  Locks in the
 * unified ALIAS_MAP + real-beats-empty dedupe + zero-carve-out
 * behavior in the mobile helper.
 */
import {
  ALIAS_MAP,
  CORE_KEYS,
  DISPLAY_LABELS,
  missingCoreReadings,
  normalizeReadings,
  isChemistryGateSatisfied,
} from "@/utils/chemistryGate";

// ═════════════════════════════════════════════════════════════════════
// Item 1 · ALIAS_MAP resolution matrix.
// ═════════════════════════════════════════════════════════════════════
const ALIAS_MATRIX: Array<[string, string]> = [
  // ph
  ["ph",              "ph"],
  ["pH",              "ph"],
  ["PH",              "ph"],
  ["Ph",              "ph"],
  ["p_h",             "ph"],
  ["p-h",             "ph"],
  // chlorine — new P17.1 canonical (was free_chlorine under P17)
  ["chlorine",        "chlorine"],
  ["Chlorine",        "chlorine"],
  ["free_chlorine",   "chlorine"],
  ["Free Chlorine",   "chlorine"],
  ["free_cl",         "chlorine"],
  ["Free Cl",         "chlorine"],
  ["FreeCl",          "chlorine"],
  ["FC",              "chlorine"],
  // alkalinity
  ["alkalinity",      "alkalinity"],
  ["Alkalinity",      "alkalinity"],
  ["total_alkalinity","alkalinity"],
  ["Total Alkalinity","alkalinity"],
  ["TA",              "alkalinity"],
  ["ta",              "alkalinity"],
  ["alk",             "alkalinity"],
  // cyanuric_acid
  ["cyanuric_acid",   "cyanuric_acid"],
  ["Cyanuric Acid",   "cyanuric_acid"],
  ["cyanuric",        "cyanuric_acid"],
  ["Cyanuric",        "cyanuric_acid"],
  ["cya",             "cyanuric_acid"],
  ["CYA",             "cyanuric_acid"],
];

describe("P17 · ALIAS_MAP resolution", () => {
  test.each(ALIAS_MATRIX)("resolves %s → %s", (rawKey, canonical) => {
    expect(normalizeReadings({ [rawKey]: 1.5 })).toEqual({
      [canonical]: 1.5,
    });
  });

  test("every alias in the matrix is present in ALIAS_MAP", () => {
    for (const [rawKey] of ALIAS_MATRIX) {
      const norm = rawKey
        .trim()
        .toLowerCase()
        .replace(/ /g, "_")
        .replace(/-/g, "_");
      expect(ALIAS_MAP).toHaveProperty(norm);
    }
  });

  test("all canonical values are in CORE_KEYS", () => {
    for (const canonical of Object.values(ALIAS_MAP)) {
      expect(CORE_KEYS).toContain(canonical);
    }
  });
});

// ═════════════════════════════════════════════════════════════════════
// Item 2a · Real-beats-empty.
// ═════════════════════════════════════════════════════════════════════
describe("P17 · real-beats-empty dedupe", () => {
  test("real pH beats empty string under any alias", () => {
    expect(normalizeReadings({ ph: "", pH: 7.4 })).toEqual({ ph: 7.4 });
  });

  test("real pH beats null under any alias", () => {
    expect(normalizeReadings({ ph: null, pH: 7.4 })).toEqual({ ph: 7.4 });
  });

  test("real pH beats undefined under any alias", () => {
    expect(normalizeReadings({ ph: undefined, pH: 7.4 })).toEqual({
      ph: 7.4,
    });
  });

  test("real pH beats string \"null\" literal", () => {
    expect(normalizeReadings({ ph: "null", pH: 7.4 })).toEqual({ ph: 7.4 });
  });

  test("real pH beats string \"None\" literal (case-insensitive)", () => {
    expect(normalizeReadings({ ph: "None", pH: 7.4 })).toEqual({ ph: 7.4 });
    expect(normalizeReadings({ ph: "NONE", pH: 7.4 })).toEqual({ ph: 7.4 });
  });

  test("real alkalinity beats blank under Total Alkalinity alias", () => {
    expect(
      normalizeReadings({ alkalinity: "", "Total Alkalinity": 90 }),
    ).toEqual({ alkalinity: 90 });
  });

  test("real chlorine beats blank under legacy free_chlorine alias", () => {
    expect(
      normalizeReadings({ chlorine: null, free_chlorine: 3.0 }),
    ).toEqual({ chlorine: 3.0 });
  });

  test("real cyanuric beats blank under Cyanuric Acid alias", () => {
    expect(
      normalizeReadings({ cyanuric_acid: null, "Cyanuric Acid": 40 }),
    ).toEqual({ cyanuric_acid: 40 });
  });
});

// ═════════════════════════════════════════════════════════════════════
// Item 2b · Zero-carve-out.
// ═════════════════════════════════════════════════════════════════════
describe("P17 · zero-carve-out", () => {
  test("0 is empty for pH when a real pH value is present", () => {
    expect(normalizeReadings({ ph: 0, pH: 7.4 })).toEqual({ ph: 7.4 });
  });

  test("0 is empty for alkalinity when a real value is present", () => {
    expect(
      normalizeReadings({ alkalinity: 0, "Total Alkalinity": 90 }),
    ).toEqual({ alkalinity: 90 });
  });

  test("0 is empty for cyanuric_acid when a real value is present", () => {
    expect(normalizeReadings({ cyanuric_acid: 0, CYA: 40 })).toEqual({
      cyanuric_acid: 40,
    });
  });

  test("0 is a real reading for chlorine (new P17.1 canonical)", () => {
    expect(normalizeReadings({ chlorine: 0 })).toEqual({
      chlorine: 0,
    });
  });

  test("0 chlorine beats null under legacy free_chlorine alias", () => {
    expect(
      normalizeReadings({ chlorine: 0, free_chlorine: null }),
    ).toEqual({ chlorine: 0 });
  });

  test("0 chlorine under legacy free_chlorine alias still folds onto chlorine", () => {
    expect(normalizeReadings({ free_chlorine: 0 })).toEqual({
      chlorine: 0,
    });
  });

  test("stringified \"0\" pH is still treated as empty", () => {
    expect(normalizeReadings({ ph: "0", pH: 7.4 })).toEqual({ ph: 7.4 });
  });

  test("missingCoreReadings flags a single {ph: 0} payload", () => {
    const missing = missingCoreReadings({ ph: 0 });
    expect(missing).toContain(DISPLAY_LABELS.ph);
  });

  test("missingCoreReadings accepts a {chlorine: 0, ...} payload", () => {
    const missing = missingCoreReadings({
      chlorine: 0,
      ph: 7.4,
      alkalinity: 90,
      cyanuric_acid: 40,
    });
    expect(missing).toEqual([]);
  });

  test("missingCoreReadings accepts a legacy {free_chlorine: 0, ...} payload", () => {
    // P17.1 alias-preservation guard: a legacy write carrying
    // ``free_chlorine: 0`` still folds onto ``chlorine`` without
    // tripping the gate.
    const missing = missingCoreReadings({
      free_chlorine: 0,
      ph: 7.4,
      alkalinity: 90,
      cyanuric_acid: 40,
    });
    expect(missing).toEqual([]);
  });
});

// ═════════════════════════════════════════════════════════════════════
// Item 3 · Gate integration — mixed aliases pass.
// ═════════════════════════════════════════════════════════════════════
describe("P17 · gate integration", () => {
  test("normalizes the P17 acceptance-criteria payload onto the P17.1 canonical", () => {
    const out = normalizeReadings({
      pH: 7.4,
      "Total Alkalinity": 90,
      "Cyanuric Acid": 40,
      "Free Chlorine": 3.0,
    });
    expect(out).toEqual({
      ph: 7.4,
      alkalinity: 90,
      cyanuric_acid: 40,
      chlorine: 3.0,
    });
  });

  test("gate passes with mixed-alias payload", () => {
    expect(
      isChemistryGateSatisfied({
        pH: 7.4,
        "Total Alkalinity": 90,
        "Cyanuric Acid": 40,
        "Free Chlorine": 3.0,
      }),
    ).toBe(true);
  });

  test("gate fails when only pH is 0 (zero-carve-out)", () => {
    expect(
      isChemistryGateSatisfied({
        ph: 0,
        chlorine: 3.0,
        alkalinity: 90,
        cyanuric_acid: 40,
      }),
    ).toBe(false);
  });
});

// ═════════════════════════════════════════════════════════════════════
// Ordering safety — two-pass dedupe is order-independent.
// ═════════════════════════════════════════════════════════════════════
describe("P17 · order-independent dedupe", () => {
  test("ph zero-first vs zero-last produce identical output", () => {
    const forward = normalizeReadings({ ph: 0, pH: 7.4 });
    const reverse = normalizeReadings({ pH: 7.4, ph: 0 });
    expect(forward).toEqual({ ph: 7.4 });
    expect(reverse).toEqual({ ph: 7.4 });
  });

  test("alkalinity blank-first vs blank-last produce identical output", () => {
    const forward = normalizeReadings({
      alkalinity: "",
      total_alkalinity: 90,
    });
    const reverse = normalizeReadings({
      total_alkalinity: 90,
      alkalinity: "",
    });
    expect(forward).toEqual({ alkalinity: 90 });
    expect(reverse).toEqual({ alkalinity: 90 });
  });

  test("canonical spelling wins when both aliases carry real values", () => {
    const forward = normalizeReadings({ ta: 100, alkalinity: 90 });
    const reverse = normalizeReadings({ alkalinity: 90, ta: 100 });
    expect(forward).toEqual({ alkalinity: 90 });
    expect(reverse).toEqual({ alkalinity: 90 });
  });

  test("alphabetically-first alias wins when neither is canonical", () => {
    const forward = normalizeReadings({ total_alkalinity: 100, TA: 90 });
    const reverse = normalizeReadings({ TA: 90, total_alkalinity: 100 });
    expect(forward).toEqual({ alkalinity: 90 });
    expect(reverse).toEqual({ alkalinity: 90 });
  });

  test("chlorine canonical wins over legacy free_chlorine when both are real", () => {
    // P17.1 alias-preservation guard.
    const forward = normalizeReadings({
      chlorine: 2.5,
      free_chlorine: 3.0,
    });
    const reverse = normalizeReadings({
      free_chlorine: 3.0,
      chlorine: 2.5,
    });
    expect(forward).toEqual({ chlorine: 2.5 });
    expect(reverse).toEqual({ chlorine: 2.5 });
  });
});

// ═════════════════════════════════════════════════════════════════════
// List-of-dicts payload shape (matches service_reports.chemical_readings).
// ═════════════════════════════════════════════════════════════════════
describe("P17 · list-of-dicts payload shape", () => {
  test("normalises and dedupes a list payload onto the P17.1 canonical", () => {
    const rows = [
      { key: "pH",               value: 7.4 },
      { key: "Total Alkalinity", value: 90 },
      { key: "Cyanuric Acid",    value: 40 },
      { key: "Free Chlorine",    value: 3.0 },
    ];
    expect(normalizeReadings(rows)).toEqual({
      ph: 7.4,
      alkalinity: 90,
      cyanuric_acid: 40,
      chlorine: 3.0,
    });
  });

  test("real beats empty in the list shape too", () => {
    const rows = [
      { key: "ph",  value: "" },
      { key: "pH",  value: 7.4 },
    ];
    expect(normalizeReadings(rows)).toEqual({ ph: 7.4 });
  });

  test("zero-carveout applies in the list shape too", () => {
    const rows = [
      { key: "ph",  value: 0 },
      { key: "pH",  value: 7.4 },
    ];
    expect(normalizeReadings(rows)).toEqual({ ph: 7.4 });
  });
});
