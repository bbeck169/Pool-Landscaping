/**
 * Phase CW1 · Feb-2026 — hint-copy i18n parity guard.
 *
 * The wizard's Required-Four hint routes through the shared
 * ``checklist.required_four_hint`` key. Confirms every locale ships
 * a translation for the key AND that the wording preserves the four
 * required nutrients (Chlorine, pH, Alkalinity, Cyanuric Acid) in
 * the target language so translators cannot silently drop one.
 */
import { describe, it, expect } from "vitest";

import en from "@/i18n/locales/en/checklist.json";
import es from "@/i18n/locales/es/checklist.json";
import fr from "@/i18n/locales/fr/checklist.json";

describe("Phase CW1 · required_four_hint i18n parity", () => {
  it("every locale ships a required_four_hint value", () => {
    expect(en.required_four_hint).toBeTruthy();
    expect(es.required_four_hint).toBeTruthy();
    expect(fr.required_four_hint).toBeTruthy();
  });

  it("English wording matches the ship copy verbatim", () => {
    expect(en.required_four_hint).toBe(
      "Free Chlorine, pH, Alkalinity, and Cyanuric Acid are required to close the job. Other readings are optional.",
    );
  });

  it("Spanish wording preserves all four nutrient labels + uses formal `usted` register", () => {
    const s = es.required_four_hint;
    expect(s).toMatch(/Cloro Libre/i);
    expect(s).toMatch(/pH/);
    expect(s).toMatch(/Alcalinidad/i);
    expect(s).toMatch(/Ácido Cianúrico/i);
    // No `tú`/`tus` — must stay formal register per D5 tone guidance.
    expect(s).not.toMatch(/\btú\b/i);
    expect(s).not.toMatch(/\btus\b/i);
  });

  it("French wording preserves all four nutrient labels + uses formal `vous` register", () => {
    const s = fr.required_four_hint;
    expect(s).toMatch(/Chlore libre/i);
    expect(s).toMatch(/pH/);
    expect(s).toMatch(/alcalinité/i);
    expect(s).toMatch(/acide cyanurique/i);
    // No `tu`/`tes` — must stay formal register per D5 tone guidance.
    expect(s).not.toMatch(/\btu\b/i);
    expect(s).not.toMatch(/\btes\b/i);
  });

  it("no locale mentions the pre-CW1 `each row` phrasing", () => {
    // Pre-CW1 the hint said "toggle Not Tested for each row" —
    // a leftover of the strict-gate era. Guard against a translator
    // accidentally re-introducing it.
    for (const s of [en.required_four_hint, es.required_four_hint, fr.required_four_hint]) {
      expect(s).not.toMatch(/each row/i);
      expect(s).not.toMatch(/cada fila/i);
      expect(s).not.toMatch(/chaque ligne/i);
    }
  });

  it("no locale localises the `{placeholder}` merge-var tokens (there are none — sanity check)", () => {
    for (const s of [en.required_four_hint, es.required_four_hint, fr.required_four_hint]) {
      expect(s).not.toMatch(/\{[a-z_]+\}/);
    }
  });
});
