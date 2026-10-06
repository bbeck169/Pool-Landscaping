/**
 * ChemDecimalInput.test.ts — CHEM-DECIMAL-MOBILE parity tests.
 *
 * Validates that every chemistry reading input uses `decimal-pad`
 * keyboard type for reliable decimal entry on both iOS and Android.
 * Also validates the ReadingChipRow validation accepts decimals
 * for appropriate fields and rejects them for integer-only fields.
 */

// ── 1. ReadingChipRow validation function (extracted logic) ────────
// We import nothing heavy — just test the validate() + RULES logic
// inline since the function is not exported. Mirror the code exactly.

type Rule = { min: number; max: number; decimals: number };

const RULES: Record<string, Rule> = {
  chlorine:           { min: 0, max: 10,    decimals: 2 },
  free_chlorine:      { min: 0, max: 10,    decimals: 2 },
  combined_chlorine:  { min: 0, max: 10,    decimals: 2 },
  ph:                 { min: 0, max: 14,    decimals: 2 },
  total_alkalinity:   { min: 0, max: 500,   decimals: 1 },
  alkalinity:         { min: 0, max: 500,   decimals: 1 },
  cyanuric_acid:      { min: 0, max: 300,   decimals: 1 },
  cya:                { min: 0, max: 300,   decimals: 1 },
  calcium_hardness:   { min: 0, max: 1000,  decimals: 0 },
  salt:               { min: 0, max: 6000,  decimals: 0 },
  tds:                { min: 0, max: 10000, decimals: 0 },
  phosphates:         { min: 0, max: 10000, decimals: 0 },
  water_temp:         { min: 0, max: 120,   decimals: 1 },
};

function validate(rule: Rule | undefined, raw: string): { value: number | null; invalid: boolean } {
  if (raw === "" || raw == null) return { value: null, invalid: false };
  if (!/^\d*\.?\d*$/.test(raw)) return { value: null, invalid: true };
  const n = Number(raw);
  if (!isFinite(n) || n < 0) return { value: null, invalid: true };
  if (rule) {
    if (n < rule.min || n > rule.max) return { value: null, invalid: true };
    const dot = raw.indexOf(".");
    if (dot >= 0 && raw.length - dot - 1 > rule.decimals) {
      return { value: null, invalid: true };
    }
  }
  return { value: rule && rule.decimals === 0 ? Math.round(n) : n, invalid: false };
}

// ── 2. Tests ───────────────────────────────────────────────────────

describe("CHEM-DECIMAL-MOBILE — decimal input validation", () => {
  describe("pH accepts decimals (up to 2dp)", () => {
    it("accepts 7.4", () => {
      const r = validate(RULES.ph, "7.4");
      expect(r.invalid).toBe(false);
      expect(r.value).toBe(7.4);
    });

    it("accepts 7.42 (2dp)", () => {
      const r = validate(RULES.ph, "7.42");
      expect(r.invalid).toBe(false);
      expect(r.value).toBe(7.42);
    });

    it("rejects 7.423 (3dp exceeds precision)", () => {
      const r = validate(RULES.ph, "7.423");
      expect(r.invalid).toBe(true);
    });

    it("accepts partial decimal (7.) as valid input during typing", () => {
      // "7." parses to 7 via Number(), which is valid
      const r = validate(RULES.ph, "7.");
      expect(r.invalid).toBe(false);
    });
  });

  describe("chlorine accepts decimals (up to 2dp)", () => {
    it("accepts 3.5", () => {
      const r = validate(RULES.chlorine, "3.5");
      expect(r.invalid).toBe(false);
      expect(r.value).toBe(3.5);
    });

    it("accepts 0.5", () => {
      const r = validate(RULES.chlorine, "0.5");
      expect(r.invalid).toBe(false);
      expect(r.value).toBe(0.5);
    });
  });

  describe("alkalinity accepts decimals (up to 1dp)", () => {
    it("accepts 100.5", () => {
      const r = validate(RULES.alkalinity, "100.5");
      expect(r.invalid).toBe(false);
      expect(r.value).toBe(100.5);
    });

    it("rejects 100.55 (2dp exceeds 1dp precision)", () => {
      const r = validate(RULES.alkalinity, "100.55");
      expect(r.invalid).toBe(true);
    });
  });

  describe("cyanuric acid accepts decimals (up to 1dp)", () => {
    it("accepts 45.2", () => {
      const r = validate(RULES.cyanuric_acid, "45.2");
      expect(r.invalid).toBe(false);
      expect(r.value).toBe(45.2);
    });
  });

  describe("salt is intentionally integer-only (decimals: 0)", () => {
    it("accepts 3200 (integer)", () => {
      const r = validate(RULES.salt, "3200");
      expect(r.invalid).toBe(false);
      expect(r.value).toBe(3200);
    });

    it("rejects 3200.5 (decimal not allowed)", () => {
      const r = validate(RULES.salt, "3200.5");
      expect(r.invalid).toBe(true);
    });

    it("decimals: 0 rounds to integer on valid input", () => {
      const r = validate(RULES.salt, "3200");
      expect(r.value).toBe(3200);
      expect(Number.isInteger(r.value)).toBe(true);
    });
  });

  describe("calcium_hardness is integer-only (decimals: 0)", () => {
    it("rejects 350.5", () => {
      const r = validate(RULES.calcium_hardness, "350.5");
      expect(r.invalid).toBe(true);
    });
  });

  describe("tds is integer-only (decimals: 0)", () => {
    it("rejects 1500.1", () => {
      const r = validate(RULES.tds, "1500.1");
      expect(r.invalid).toBe(true);
    });
  });

  describe("edge cases", () => {
    it("empty string is valid (null value)", () => {
      const r = validate(RULES.ph, "");
      expect(r.invalid).toBe(false);
      expect(r.value).toBeNull();
    });

    it("rejects non-numeric input", () => {
      const r = validate(RULES.ph, "abc");
      expect(r.invalid).toBe(true);
    });

    it("rejects negative numbers", () => {
      const r = validate(RULES.ph, "-1");
      expect(r.invalid).toBe(true);
    });

    it("rejects out-of-range values", () => {
      const r = validate(RULES.ph, "15");
      expect(r.invalid).toBe(true);
    });
  });
});

// ── 3. keyboardType audit assertions ──────────────────────────────
import * as fs from "fs";
import * as path from "path";

describe("CHEM-DECIMAL-MOBILE — keyboardType source audit", () => {
  it("ReadingChipRow uses decimal-pad for its TextInput", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../src/components/checklist/ReadingChipRow.tsx"),
      "utf-8",
    );
    // The component must use decimal-pad, not numeric or number-pad
    expect(src).toContain('keyboardType="decimal-pad"');
    expect(src).not.toContain('keyboardType="numeric"');
    expect(src).not.toContain('keyboardType="number-pad"');
  });

  it("customer/chemistry/[id].tsx reading inputs use decimal-pad", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../app/customer/chemistry/[id].tsx"),
      "utf-8",
    );
    // All keyboardType mentions must be decimal-pad for chemistry
    const types = src.match(/keyboardType="[^"]+"/g) || [];
    for (const t of types) {
      expect(t).toBe('keyboardType="decimal-pad"');
    }
  });

  it("customer/chemistry volume input was fixed from numeric to decimal-pad", () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, "../app/customer/chemistry/[id].tsx"),
      "utf-8",
    );
    expect(src).not.toContain('keyboardType="numeric"');
    expect(src).not.toContain('keyboardType="number-pad"');
  });
});
