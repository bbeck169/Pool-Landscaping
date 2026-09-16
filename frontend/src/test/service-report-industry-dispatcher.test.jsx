/**
 * Phase MI1.1 · Feb 2026 — ServiceReport tech page industry dispatcher.
 *
 * The real dispatcher lives in ``components/checklist/ChecklistModal.jsx``
 * (the ServiceReport tech page renders the ``<ChecklistModal>`` — the
 * MI1 brief called it "ServiceReport" but the code path threads
 * through the modal). Grep against the source pinning the branches
 * so a future accidental drop of an industry surfaces here.
 *
 * Also exercises ``deriveIndustryForJob`` at runtime to guarantee
 * the keyword ordering (e.g. "Solar Panel Cleaning" resolves to
 * ``solar`` even though it also contains "clean").
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

import deriveIndustryForJob from "../lib/deriveIndustry";

const MODAL = fs.readFileSync(
  path.resolve(__dirname, "../components/checklist/ChecklistModal.jsx"),
  "utf-8",
);


describe("ChecklistModal · MI1.1 industry dispatcher", () => {
  it("routes pool jobs to PoolChecklistForm (untouched)", () => {
    expect(MODAL).toMatch(
      /clientType === "pool"[\s\S]{0,80}<PoolChecklistForm/,
    );
  });

  it("routes landscaping jobs to LandscapingChecklistForm (untouched)", () => {
    expect(MODAL).toMatch(
      /clientType === "landscaping"[\s\S]{0,80}<LandscapingChecklistForm/,
    );
  });

  it("routes the 5+ new industries through IndustryChecklistForm", () => {
    // Phase D2 · the ``NEW_INDUSTRIES`` set is now derived from
    // ``CANONICAL_INDUSTRIES`` (single source of truth). Pool +
    // Landscaping are filtered out because they have their own
    // dispatch branches upstream.
    expect(MODAL).toMatch(
      /clientType === "generic"[\s\S]{0,600}deriveIndustryForJob\(job\)/,
    );
    expect(MODAL).toMatch(
      /new Set\(\s*CANONICAL_INDUSTRIES\.filter\(\s*\(s\)\s*=>\s*s !== "pool" && s !== "landscaping"/,
    );
    expect(MODAL).toMatch(
      /industry=\{derived\}[\s\S]{0,200}<\/IndustryChecklistForm>|industry=\{derived\}[\s\S]{0,80}checklistItems=/,
    );
  });

  it("fallback branch renders IndustryChecklistForm with industry=handyman", () => {
    // Unknown-industry job → Handyman template + console.warn.
    expect(MODAL).toMatch(
      /industry="handyman"[\s\S]{0,200}checklistItems=\{report\.checklist_items/,
    );
  });

  it("fallback branch emits a console.warn tagged [MI1.1]", () => {
    expect(MODAL).toMatch(
      /console\.warn\(\s*"\[MI1\.1\]/,
    );
  });

  it("props threaded to IndustryChecklistForm mirror the modal contract", () => {
    // ``locked``, ``checklistItems``, ``notes``, ``onChange`` all
    // pass through so tech state stays in sync with report state.
    expect(MODAL).toMatch(
      /<IndustryChecklistForm[\s\S]{0,400}locked=\{locked\}[\s\S]{0,400}checklistItems=\{report\.checklist_items[\s\S]{0,400}notes=\{report\.notes[\s\S]{0,80}onChange=\{patchReport\}/,
    );
  });
});


describe("deriveIndustryForJob · runtime keyword ordering", () => {
  it("HVAC service_type → hvac", () => {
    expect(deriveIndustryForJob({ service_type: "HVAC Tune-Up" })).toBe("hvac");
  });

  it("Pest Control service_type → pest_control", () => {
    expect(deriveIndustryForJob({ service_type: "Pest control quarterly" }))
      .toBe("pest_control");
  });

  it("Cleaning service_type → cleaning", () => {
    expect(deriveIndustryForJob({ service_type: "Deep house cleaning" }))
      .toBe("cleaning");
  });

  it("Solar service_type → solar (wins vs 'cleaning' keyword)", () => {
    // "Solar Panel Cleaning" contains both "solar" and "clean" —
    // the narrower ``solar`` match must win.
    expect(deriveIndustryForJob({ service_type: "Solar Panel Cleaning" }))
      .toBe("solar");
  });

  it("Handyman service_type → handyman", () => {
    expect(deriveIndustryForJob({ service_type: "Handyman fence repair" }))
      .toBe("handyman");
  });

  it("Landscape service_type → landscaping", () => {
    expect(deriveIndustryForJob({ service_type: "Landscape maintenance" }))
      .toBe("landscaping");
  });

  it("Pool service_type → pool", () => {
    expect(deriveIndustryForJob({ service_type: "Weekly pool service" }))
      .toBe("pool");
  });

  it("Explicit industry override wins over keyword match", () => {
    expect(deriveIndustryForJob({
      industry: "cleaning", service_type: "Solar Panel Job",
    })).toBe("cleaning");
  });

  it("Empty job + no tenant industries → pool fallback", () => {
    expect(deriveIndustryForJob({}, null)).toBe("pool");
  });

  it("Tenant primary industry backfills when the job has no signal", () => {
    expect(deriveIndustryForJob({}, { industries: ["hvac"] })).toBe("hvac");
    // Legacy "pools" plural alias normalises to canonical "pool".
    expect(deriveIndustryForJob({}, { industry: "pools" })).toBe("pool");
  });
});
