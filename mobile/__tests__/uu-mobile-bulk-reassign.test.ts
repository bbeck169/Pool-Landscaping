/**
 * UU-mobile · Schedule bulk-reassign (POST /jobs/bulk-reassign).
 * BE BulkReassignIn = { job_ids, new_tech_id?, new_crew_id? } — the legacy
 * `tech_id` key is silently dropped by pydantic → 400 "new_tech_id or
 * new_crew_id is required" on every mobile reassign (pre-fix).
 * calendar.tsx has no screen render harness (baseline) → source locks.
 */
import fs from "fs";
import path from "path";

const SRC = fs.readFileSync(path.resolve(__dirname, "../app/(app)/schedule/calendar.tsx"), "utf8");
const fnBody = (name: string) => {
  const s = SRC.indexOf(`const ${name} = async () => {`);
  return SRC.slice(s, SRC.indexOf("\n  };\n", s));
};

it("C1 · bulk-reassign sends new_tech_id (BE contract), never the legacy tech_id key", () => {
  const body = fnBody("bulkReassign");
  expect(body).toContain('api.post("/jobs/bulk-reassign", bulkReassignPayload([...checked], pick));');
  expect(body).not.toMatch(/[{,]\s*tech_id:/);
  expect(SRC).not.toMatch(/bulk-reassign",\s*\{[^}]*\btech_id:/);
  const { bulkReassignPayload } = require("@/src/lib/bulkReassign");
  expect(bulkReassignPayload(["j1"], { kind: "tech", id: "t1" })).toEqual({ job_ids: ["j1"], new_tech_id: "t1" });
});

it("C1 · unchanged around it: job_ids from the selection, success Alert, selection cleared, forced reload", () => {
  const body = fnBody("bulkReassign");
  expect(body).toContain("bulkReassignPayload([...checked], pick)");
  expect(body).toContain('Alert.alert("Reassigned"');
  expect(body).toContain("setChecked(new Set());");
  expect(body).toContain("await load(true);");
  expect(body).toContain('Alert.alert("Reassign failed", e.message || "Unknown error");');
});

describe("UU-mobile-2 · tech-list source", () => {
  const { reassignableTechs } = require("@/src/lib/bulkReassign");

  it("C2 · openReassign loads GET /technicians (not /users?role=tech) via reassignableTechs", () => {
    const body = fnBody("openReassign");
    expect(body).toContain('const res = await api.get("/technicians");');
    expect(body).toContain("const list = reassignableTechs(res);");
    expect(SRC).not.toContain("/users?role=tech");
  });

  it("C2 · same unwrap as the calendar's /technicians load (bare array OR {technicians})", () => {
    const t = { id: "t1", name: "Mike", role: "pool_tech" };
    expect(reassignableTechs([t])).toEqual([t]);
    expect(reassignableTechs({ technicians: [t] })).toEqual([t]);
    expect(reassignableTechs(null)).toEqual([]);
    expect(reassignableTechs({ users: [t] })).toEqual([]);
  });

  it("C2 · keeps only named rows with a BE-accepted tech role (pool_tech / landscape_tech / technician / tech)", () => {
    const rows = [
      { id: "a", name: "A", role: "pool_tech" }, { id: "b", name: "B", role: "Landscape_Tech" },
      { id: "c", name: "C", role: "technician" }, { id: "d", name: "D", role: "tech" },
      { id: "e", name: "E", role: null }, { id: "f", name: "F", role: "admin" },
      { id: "g", name: "", role: "tech" }, { id: "", name: "H", role: "tech" },
    ];
    expect(reassignableTechs(rows).map((r: any) => r.id)).toEqual(["a", "b", "c", "d"]);
  });
});
