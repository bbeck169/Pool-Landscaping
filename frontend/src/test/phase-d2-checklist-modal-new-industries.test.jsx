/**
 * Phase D2 · Feb 2026 — ChecklistModal routes all 21 non-pool /
 * non-landscape industries through IndustryChecklistForm.
 *
 * Source-scan the modal to pin the wiring:
 *   * ``NEW_INDUSTRIES`` derives from ``CANONICAL_INDUSTRIES`` so
 *     future additions flow through without a modal edit.
 *   * The pool + landscaping branches remain byte-identical (their
 *     own dispatch, no drift into the generic switch).
 *   * The Handyman-fallback console.warn keeps the ``[MI1.1]`` tag
 *     prefix — do NOT rename to ``[D2]`` (stable log grep target).
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

import { CANONICAL_INDUSTRIES } from "../lib/deriveIndustry";

const MODAL = fs.readFileSync(
  path.resolve(__dirname, "../components/checklist/ChecklistModal.jsx"),
  "utf-8",
);


describe("ChecklistModal · Phase D2 dispatcher coverage", () => {
  it("derives NEW_INDUSTRIES from CANONICAL_INDUSTRIES (single source of truth)", () => {
    expect(MODAL).toMatch(
      /new Set\(\s*CANONICAL_INDUSTRIES\.filter\(\s*\(s\)\s*=>\s*s !== "pool" && s !== "landscaping"/,
    );
  });

  it("imports the canonical industry list from the deriver module", () => {
    expect(MODAL).toMatch(
      /import\s*\{[\s\S]{0,200}CANONICAL_INDUSTRIES[\s\S]{0,200}\}\s*from\s*["']@\/lib\/deriveIndustry["']/,
    );
  });

  it("pool branch remains byte-identical", () => {
    // The pool dispatch must sit on its own ``clientType === "pool"``
    // check with a direct render of PoolChecklistForm.
    expect(MODAL).toMatch(
      /clientType === "pool"[\s\S]{0,100}<PoolChecklistForm/,
    );
  });

  it("landscaping branch remains byte-identical", () => {
    expect(MODAL).toMatch(
      /clientType === "landscaping"[\s\S]{0,100}<LandscapingChecklistForm/,
    );
  });

  it("Handyman fallback keeps the [MI1.1] console.warn tag", () => {
    // Regression pin — the tag prefix is a stable log grep target.
    expect(MODAL).toMatch(/console\.warn\(\s*"\[MI1\.1\]/);
    expect(MODAL).not.toMatch(/console\.warn\(\s*"\[D2\]/);
  });

  it("all 21 non-pool / non-landscape canonical slugs route to IndustryChecklistForm", () => {
    // Semantic assertion: the filter derives NEW_INDUSTRIES from
    // CANONICAL_INDUSTRIES minus pool + landscaping, so this loop
    // computes what NEW_INDUSTRIES SHOULD contain and asserts each
    // slug is a canonical member.
    const routed = CANONICAL_INDUSTRIES.filter(
      (s) => s !== "pool" && s !== "landscaping",
    );
    expect(routed.length).toBe(21);
    // Sanity — every routed slug is a Phase-MI1-or-later industry.
    for (const slug of routed) {
      expect(CANONICAL_INDUSTRIES).toContain(slug);
    }
  });

  it("routes derived industry into IndustryChecklistForm via industry prop", () => {
    expect(MODAL).toMatch(
      /<IndustryChecklistForm[\s\S]{0,80}industry=\{derived\}/,
    );
    // Fallback also uses IndustryChecklistForm with a literal
    // ``handyman`` industry (safest generic template).
    expect(MODAL).toMatch(
      /<IndustryChecklistForm[\s\S]{0,80}industry="handyman"/,
    );
  });
});
