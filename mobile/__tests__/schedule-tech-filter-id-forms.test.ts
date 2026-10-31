/**
 * Bug C · Schedule tech filter matches both technician ID forms
 * (technicians.id record id OR technicians.user_id), mirroring BE
 * services/tech_id_resolver.resolve_tech_id_variants. Crew union +
 * unassigned catch-all unchanged.
 */
import fs from "fs";
import path from "path";
import { jobMatchesTech, filterMonthJobs, buildTechCrewIds } from "@/src/lib/monthGrid";

const REC = "tech-rec-1";   // technicians.id
const USR = "user-acct-1";  // technicians.user_id
const underRecord = { id: "r", technician_id: REC, status: "scheduled" };
const underUser = { id: "u", technician_id: USR, status: "scheduled" };
const otherTech = { id: "x", technician_id: "tech-rec-9", status: "scheduled" };
const unassigned = { id: "n", technician_id: null, status: "scheduled" };
const crewJob = { id: "c", technician_id: "tech-rec-7", crew_id: "crewA", status: "scheduled" };
const ALL = [underRecord, underUser, otherTech, unassigned, crewJob];
const ids = (a: any[]) => a.map((j) => j.id).sort();
const base = { showCancelled: true };

describe("jobMatchesTech · both ID forms", () => {
  it("1 · job saved under the technician record id matches (regression lock)", () => {
    expect(jobMatchesTech(underRecord, REC, null, USR)).toBe(true);
    expect(jobMatchesTech(underRecord, REC)).toBe(true);
  });
  it("2 · job saved under the tech's user_id matches (new)", () => {
    expect(jobMatchesTech(underUser, REC, null, USR)).toBe(true);
    expect(jobMatchesTech(underUser, REC)).toBe(false); // without the alt form → legacy miss
  });
  it("4 · a different tech's job stays excluded", () => {
    expect(jobMatchesTech(otherTech, REC, null, USR)).toBe(false);
  });
});

describe("filterMonthJobs · both ID forms", () => {
  it("3 · admin filter: mixed set → both forms surface, other tech excluded, catch-all + crew kept", () => {
    const out = filterMonthJobs(ALL, { ...base, isTech: false, techFilter: REC, altTechId: USR,
      techCrewIds: buildTechCrewIds([{ id: "crewA", tech_ids: [REC] }], REC) });
    expect(ids(out)).toEqual(["c", "n", "r", "u"]);
  });
  it("3 · tech own view (resolvedTechId + user.id) → both forms surface", () => {
    const out = filterMonthJobs(ALL, { ...base, isTech: true, techFilter: "all", resolvedTechId: REC, altTechId: USR });
    expect(ids(out)).toEqual(["n", "r", "u"]);
  });
  it("no alt id (preview: id === user_id) → unchanged legacy result", () => {
    const out = filterMonthJobs(ALL, { ...base, isTech: false, techFilter: REC, altTechId: null });
    expect(ids(out)).toEqual(["n", "r"]);
  });
});

describe("calendar.tsx wiring (source lock)", () => {
  const SRC = fs.readFileSync(path.join(__dirname, "../app/(app)/schedule/calendar.tsx"), "utf8");
  it("alt id = row user_id (admin) / user.id (tech), only when it differs", () => {
    expect(SRC).toContain("const alt = isTech ? user?.id : allTechs.find((t: any) => t.id === primary)?.user_id;");
    expect(SRC).toContain("return alt && alt !== primary ? String(alt) : null;");
  });
  it("both filteredJobs branches + month filter carry the alt-id clause", () => {
    expect(SRC).toContain("j.technician_id === tid || !j.technician_id || inTechCrews(j) || matchesAltTechId(j)");
    expect(SRC).toContain("j.technician_id === techFilter || !j.technician_id || inTechCrews(j) || matchesAltTechId(j)");
    expect(SRC).toContain("filterMonthJobs(arr, { isTech, techFilter, resolvedTechId, showCancelled, techCrewIds, altTechId })");
  });
});
