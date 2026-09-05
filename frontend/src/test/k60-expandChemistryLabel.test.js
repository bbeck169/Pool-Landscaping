/**
 * K60 · Feb-2026 — Chemistry-label expander assertions (web parity).
 *
 * Web mirror of ``mobile/__tests__/k60-expandChemistryLabel.test.ts``.
 * The two helpers must stay in lockstep; if this suite diverges from
 * the mobile suite the parity contract is broken.
 *
 * See /app/memory/PHASE_K60_CHEMISTRY_LABELS.md.
 */
import { describe, it, expect } from "vitest";
import { expandChemistryLabel } from "../lib/expandChemistryLabel";

describe("K60 · expandChemistryLabel (web) — full mapping (case-insensitive)", () => {
  const cases = [
    ["FC", "Free Chlorine"],
    ["TC", "Total Chlorine"],
    ["pH", "pH"],
    ["TA", "Total Alkalinity"],
    ["CYA", "Cyanuric Acid"],
    ["CH", "Calcium Hardness"],
    ["Salt", "Salt"],
    ["TDS", "Total Dissolved Solids"],
    ["PO4", "Phosphates"],
  ];
  for (const [input, expected] of cases) {
    it(`${input} → ${expected}`, () => {
      expect(expandChemistryLabel(input)).toBe(expected);
    });
    it(`${input.toLowerCase()} → ${expected} (case-insensitive)`, () => {
      expect(expandChemistryLabel(input.toLowerCase())).toBe(expected);
    });
  }
});

describe("K60 · expandChemistryLabel (web) — tenant customisations pass through", () => {
  it("custom label unchanged", () => {
    expect(expandChemistryLabel("Free Cl (deep end)")).toBe("Free Cl (deep end)");
  });
  it("unknown short-form unchanged", () => {
    expect(expandChemistryLabel("ORP")).toBe("ORP");
  });
  it("already-expanded name unchanged (idempotent)", () => {
    expect(expandChemistryLabel("Free Chlorine")).toBe("Free Chlorine");
  });
});

describe("K60 · expandChemistryLabel (web) — whitespace + edge inputs", () => {
  it("trims whitespace before lookup", () => {
    expect(expandChemistryLabel(" FC ")).toBe("Free Chlorine");
  });
  it("empty inputs → empty string", () => {
    expect(expandChemistryLabel(null)).toBe("");
    expect(expandChemistryLabel(undefined)).toBe("");
    expect(expandChemistryLabel("")).toBe("");
  });
});
