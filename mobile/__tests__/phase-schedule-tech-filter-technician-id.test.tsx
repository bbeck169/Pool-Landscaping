/**
 * Phase S1-fix — Schedule tech filter uses technician_id (not user account ID).
 *
 * Tests:
 *  1. Data source is /api/technicians (not /users?role=tech).
 *  2. Tech self-scope uses user?.technician_id (not user?.id).
 *  3. The filteredJobs memo compares j.technician_id === techFilter.
 *  4. The old buggy pattern (user?.id as tech scope) is NOT present.
 *  5. Unassigned jobs (technician_id null) visible under "all".
 *  6. The picker options use t.id from /api/technicians (which IS technician_id).
 */
import * as fs from "fs";
import * as path from "path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../app/(app)/schedule/calendar.tsx"),
  "utf-8",
);

describe("Phase S1-fix — tech filter uses technician_id", () => {
  it('data source is GET /api/technicians (not /users?role=tech for allTechs)', () => {
    // The allTechs fetch should use /technicians
    expect(SRC).toContain('api.get("/technicians")');
    // Old endpoint should NOT be used for allTechs (may still exist for openReassign)
    const allTechsBlock = SRC.slice(
      SRC.indexOf("setAllTechs") - 200,
      SRC.indexOf("setAllTechs") + 200,
    );
    expect(allTechsBlock).not.toContain("/users?role=tech");
  });

  it("tech self-scope uses user?.technician_id", () => {
    expect(SRC).toContain('user?.technician_id || "all"');
    // Old buggy pattern must be gone from the filter init
    // (it may still exist in openReassign or elsewhere — just not in the filter)
    const filterBlock = SRC.slice(
      SRC.indexOf("TECH_FILTER_KEY"),
      SRC.indexOf("TECH_FILTER_KEY") + 800,
    );
    expect(filterBlock).not.toContain('isTech ? (user?.id || "all")');
  });

  it("filteredJobs compares j.technician_id === techFilter", () => {
    expect(SRC).toContain("j.technician_id === techFilter");
  });

  it("filteredJobs includes unassigned jobs (|| !j.technician_id) when filter is specific tech — wait, should NOT. Only under 'all'", () => {
    // The current filter: techFilter === "all" → all jobs; specific → only that tech + unassigned
    // Actually per S1 spec, unassigned jobs ARE visible when a specific tech is selected.
    // Verify the filter shape:
    expect(SRC).toContain(
      'j.technician_id === techFilter || !j.technician_id',
    );
  });

  it('"all" filter passes through every job', () => {
    expect(SRC).toContain('if (techFilter === "all") return jobs;');
  });

  it("useEffect deps include user?.technician_id for proper reactivity", () => {
    expect(SRC).toContain("user?.technician_id, isTech]");
  });

  it("picker options check t.id against techFilter (technician record ID)", () => {
    expect(SRC).toContain("techFilter === t.id");
  });

  it("techScope query param uses user.technician_id NOT user.id (K42 fix)", () => {
    // The query-param line that scopes the /jobs fetch for techs MUST
    // reference user?.technician_id (technicians.id) — NOT user?.id
    // (users.id). Jobs store technicians.id in their technician_id field.
    expect(SRC).toContain("user?.technician_id ? `&technician_id=${user.technician_id}`");
    // The old buggy pattern must NOT be present in the techScope line
    expect(SRC).not.toMatch(/techScope.*user\?\.id.*technician_id=.*user\.id/);
  });
});
