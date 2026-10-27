/**
 * TD-xx mobile (web XX BE 6fec5af2c / FE c19b8daf3) — Schedule tech filter
 * unions crew membership. D1(a): `!technician_id` catch-all kept. D2(a):
 * auth-self tech branch widened too. calendar.tsx wiring is source-locked.
 */
import fs from "fs";
import path from "path";
import { buildTechCrewIds, jobMatchesTech, filterMonthJobs } from "@/src/lib/monthGrid";

const CREWS = [
  { id: "crewA", tech_ids: ["t1", "t2"] },
  { id: "crewB", tech_ids: ["t1", "t3"] },
  { id: "crewC", tech_ids: ["t4"] },
];
const direct = { id: "d", technician_id: "t1", status: "scheduled" };
const crewA_ledByT2 = { id: "a", technician_id: "t2", crew_id: "crewA", status: "scheduled" };
const crewB_ledByT3 = { id: "b", technician_id: "t3", crew_id: "crewB", status: "scheduled" };
const crewC_ledByT4 = { id: "c", technician_id: "t4", crew_id: "crewC", status: "scheduled" };
const crewOnly = { id: "o", technician_id: null, crew_id: "crewC", status: "scheduled" };
const otherTech = { id: "x", technician_id: "t9", status: "scheduled" };
const ALL = [direct, crewA_ledByT2, crewB_ledByT3, crewC_ledByT4, crewOnly, otherTech];
const ids = (arr: any[]) => arr.map((j) => j.id).sort();

describe("buildTechCrewIds", () => {
  it("collects ALL crews containing the tech (plural)", () => {
    expect([...buildTechCrewIds(CREWS, "t1")!].sort()).toEqual(["crewA", "crewB"]);
  });
  it("no tech → null; non-member → empty set", () => {
    expect(buildTechCrewIds(CREWS, null)).toBeNull();
    expect(buildTechCrewIds(CREWS, undefined)).toBeNull();
    expect(buildTechCrewIds(CREWS, "t9")!.size).toBe(0);
    expect(buildTechCrewIds(undefined, "t1")!.size).toBe(0);
  });
});

describe("jobMatchesTech", () => {
  const t1Crews = buildTechCrewIds(CREWS, "t1");
  it("direct technician_id match (regression lock)", () => {
    expect(jobMatchesTech(direct, "t1", t1Crews)).toBe(true);
    expect(jobMatchesTech(direct, "t1", null)).toBe(true);
  });
  it("crew job led by another tech matches a member (fix)", () => {
    expect(jobMatchesTech(crewA_ledByT2, "t1", t1Crews)).toBe(true);
  });
  it("multi-crew tech matches jobs from any of their crews (plural)", () => {
    expect(jobMatchesTech(crewA_ledByT2, "t1", t1Crews)).toBe(true);
    expect(jobMatchesTech(crewB_ledByT3, "t1", t1Crews)).toBe(true);
  });
  it("non-member does NOT match a crew job led by someone else (negative)", () => {
    expect(jobMatchesTech(crewC_ledByT4, "t1", t1Crews)).toBe(false);
    expect(jobMatchesTech(otherTech, "t1", t1Crews)).toBe(false);
  });
  it("D1(a) — non-member still matches crew-only job with no technician_id", () => {
    expect(jobMatchesTech(crewOnly, "t1", t1Crews)).toBe(true);
  });
  it("null/undefined techCrewIds → direct match only (backward compat)", () => {
    expect(jobMatchesTech(crewA_ledByT2, "t1", null)).toBe(false);
    expect(jobMatchesTech(crewA_ledByT2, "t1", undefined)).toBe(false);
    expect(jobMatchesTech(crewOnly, "t1", undefined)).toBe(true);
  });
});

describe("filterMonthJobs mirror", () => {
  const base = { showCancelled: true };
  it("admin filter t1 + crews → direct + both crews + crew-only catch-all", () => {
    const out = filterMonthJobs(ALL, { ...base, isTech: false, techFilter: "t1", techCrewIds: buildTechCrewIds(CREWS, "t1") });
    expect(ids(out)).toEqual(["a", "b", "d", "o"]);
  });
  it("admin filter, no techCrewIds → legacy direct + catch-all only", () => {
    expect(ids(filterMonthJobs(ALL, { ...base, isTech: false, techFilter: "t1" }))).toEqual(["d", "o"]);
    expect(ids(filterMonthJobs(ALL, { ...base, isTech: false, techFilter: "t1", techCrewIds: null }))).toEqual(["d", "o"]);
  });
  it("admin 'all' → unfiltered", () => {
    expect(filterMonthJobs(ALL, { ...base, isTech: false, techFilter: "all", techCrewIds: null })).toHaveLength(ALL.length);
  });
  it("D2(a) — auth-self tech sees crew jobs led by someone else", () => {
    const out = filterMonthJobs(ALL, { ...base, isTech: true, techFilter: "all", resolvedTechId: "t1", techCrewIds: buildTechCrewIds(CREWS, "t1") });
    expect(ids(out)).toEqual(["a", "b", "d", "o"]);
  });
  it("auth-self tech without id still fails closed", () => {
    expect(filterMonthJobs(ALL, { ...base, isTech: true, techFilter: "all", resolvedTechId: null, techCrewIds: null })).toEqual([]);
  });
  it("non-member tech t4 → own crew job + catch-alls only", () => {
    const out = filterMonthJobs(ALL, { ...base, isTech: false, techFilter: "t4", techCrewIds: buildTechCrewIds(CREWS, "t4") });
    expect(ids(out)).toEqual(["c", "o"]);
  });
});

describe("calendar.tsx wiring (source lock)", () => {
  const SRC = fs.readFileSync(path.join(__dirname, "../app/(app)/schedule/calendar.tsx"), "utf8");
  it("techCrewIds derived from crews + active tech id", () => {
    expect(SRC).toContain('const activeTechId = techFilter !== "all" ? techFilter : (isTech ? resolvedTechId : null);');
    expect(SRC).toContain("const techCrewIds = useMemo(() => buildTechCrewIds(crews, activeTechId), [crews, activeTechId]);");
  });
  it("both filteredJobs branches + month filter use the widened predicate", () => {
    expect(SRC).toContain("const inTechCrews = useCallback((j: any) => !!techCrewIds && !!j.crew_id && techCrewIds.has(j.crew_id), [techCrewIds]);");
    expect(SRC).toContain("return jobs.filter((j) => j.technician_id === tid || !j.technician_id || inTechCrews(j));");
    expect(SRC).toContain("return jobs.filter((j) => j.technician_id === techFilter || !j.technician_id || inTechCrews(j));");
    expect(SRC).toContain("filterMonthJobs(arr, { isTech, techFilter, resolvedTechId, showCancelled, techCrewIds })");
    expect(SRC).toContain("if (!tid) return []; // fail closed: no id → empty");
  });
});
