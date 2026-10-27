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
  expect(body).toContain('api.post("/jobs/bulk-reassign"');
  expect(body).toMatch(/new_tech_id: reassignTechId/);
  expect(body).not.toMatch(/[{,]\s*tech_id:/);
  expect(SRC).not.toMatch(/bulk-reassign",\s*\{[^}]*\btech_id:/);
});

it("C1 · unchanged around it: job_ids from the selection, success Alert, selection cleared, forced reload", () => {
  const body = fnBody("bulkReassign");
  expect(body).toContain("job_ids: [...checked]");
  expect(body).toContain('Alert.alert("Reassigned"');
  expect(body).toContain("setChecked(new Set());");
  expect(body).toContain("await load(true);");
  expect(body).toContain('Alert.alert("Reassign failed", e.message || "Unknown error");');
});
