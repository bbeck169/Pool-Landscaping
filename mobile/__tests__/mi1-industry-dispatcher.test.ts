/**
 * Phase MI1.1-mobile — Multi-industry checklist dispatcher parity tests.
 *
 * Tests:
 *   1. deriveIndustryForJob: HVAC job.
 *   2. deriveIndustryForJob: Pest Control job.
 *   3. deriveIndustryForJob: Cleaning job.
 *   4. deriveIndustryForJob: Solar job.
 *   5. deriveIndustryForJob: Handyman job.
 *   6. deriveIndustryForJob: Landscaping job.
 *   7. deriveIndustryForJob: Pool job.
 *   8. "Solar Panel Cleaning" resolves to solar (solar wins vs clean).
 *   9. Explicit job.industry override beats keyword match.
 *  10. Empty job → pool fallback.
 *  11. Tenant primary industry backfills when job has no signal.
 *  12. Modal source contains deriveIndustryForJob invocation in generic branch.
 *  13. Modal source references all 5 new industry slugs in NEW_INDUSTRIES.
 *  14. Modal source still has clientType === "pool" branch (regression pin).
 *  15. Modal source still has clientType === "landscaping" branch (regression pin).
 */
import { deriveIndustryForJob, INDUSTRY_SLUGS } from "../src/lib/deriveIndustry";
import * as fs from "fs";
import * as path from "path";

const CHECKLIST_SRC = fs.readFileSync(
  path.resolve(__dirname, "../app/job/[id]/checklist.tsx"),
  "utf-8",
);

describe("deriveIndustryForJob — keyword resolution", () => {
  it("returns hvac for an HVAC job", () => {
    expect(deriveIndustryForJob({ service_type: "HVAC Maintenance" })).toBe("hvac");
  });

  it("returns pest_control for a pest job", () => {
    expect(deriveIndustryForJob({ service_type: "Pest Control" })).toBe("pest_control");
  });

  it("returns cleaning for a cleaning job", () => {
    expect(deriveIndustryForJob({ service_type: "House Cleaning" })).toBe("cleaning");
  });

  it("returns solar for a solar job", () => {
    expect(deriveIndustryForJob({ service_type: "Solar Install" })).toBe("solar");
  });

  it("returns handyman for a handyman job", () => {
    expect(deriveIndustryForJob({ service_type: "Handyman Service" })).toBe("handyman");
  });

  it("returns landscaping for a landscaping job", () => {
    expect(deriveIndustryForJob({ service_type: "Landscape Maintenance" })).toBe("landscaping");
  });

  it("returns pool for a pool job", () => {
    expect(deriveIndustryForJob({ service_type: "Pool Cleaning" })).toBe("pool");
  });

  it('solar wins vs clean: "Solar Panel Cleaning" → solar', () => {
    expect(deriveIndustryForJob({ service_type: "Solar Panel Cleaning" })).toBe("solar");
  });

  it("explicit job.industry override beats keyword match", () => {
    expect(
      deriveIndustryForJob({ industry: "pest_control", service_type: "Pool Service" }),
    ).toBe("pest_control");
  });

  it("empty job → pool fallback", () => {
    expect(deriveIndustryForJob({})).toBe("pool");
    expect(deriveIndustryForJob(undefined)).toBe("pool");
    expect(deriveIndustryForJob(null)).toBe("pool");
  });

  it("tenant primary industry backfills when job has no signal", () => {
    expect(deriveIndustryForJob({}, { industries: ["hvac"] })).toBe("hvac");
    expect(deriveIndustryForJob({}, { industry: "solar" })).toBe("solar");
    // Alias: "pools" → "pool"
    expect(deriveIndustryForJob({}, { industries: ["pools"] })).toBe("pool");
  });

  it("INDUSTRY_SLUGS contains all 7 canonical slugs", () => {
    expect(INDUSTRY_SLUGS).toEqual(
      expect.arrayContaining([
        "pool", "landscaping", "hvac", "pest_control",
        "cleaning", "solar", "handyman",
      ]),
    );
  });
});

describe("MI1.1-mobile — checklist.tsx dispatcher (source assertions)", () => {
  it("contains deriveIndustryForJob invocation inside generic branch", () => {
    // The generic branch should call deriveIndustryForJob(job)
    const genericBranch = CHECKLIST_SRC.slice(
      CHECKLIST_SRC.indexOf('clientType === "generic"'),
    );
    expect(genericBranch).toContain("deriveIndustryForJob(job)");
  });

  it("references all 5 new industry slugs in NEW_INDUSTRIES set", () => {
    expect(CHECKLIST_SRC).toContain('"hvac"');
    expect(CHECKLIST_SRC).toContain('"pest_control"');
    expect(CHECKLIST_SRC).toContain('"cleaning"');
    expect(CHECKLIST_SRC).toContain('"solar"');
    expect(CHECKLIST_SRC).toContain('"handyman"');
    expect(CHECKLIST_SRC).toContain("NEW_INDUSTRIES");
  });

  it('still has clientType === "pool" branch (regression pin)', () => {
    expect(CHECKLIST_SRC).toContain('clientType === "pool"');
  });

  it('still has clientType === "landscaping" branch (regression pin)', () => {
    expect(CHECKLIST_SRC).toContain('clientType === "landscaping"');
  });

  it("contains [MI1.1-mobile] console.warn tag for handyman fallback", () => {
    expect(CHECKLIST_SRC).toContain("[MI1.1-mobile]");
    expect(CHECKLIST_SRC).toContain("falling back to Handyman template");
  });

  it("IndustryChecklistForm is imported", () => {
    expect(CHECKLIST_SRC).toMatch(
      /import\s+IndustryChecklistForm\s+from/,
    );
  });

  it("deriveIndustryForJob is imported", () => {
    expect(CHECKLIST_SRC).toMatch(
      /import\s+\{[^}]*deriveIndustryForJob[^}]*\}\s+from/,
    );
  });
});
