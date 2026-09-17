/**
 * Phase S1 — Schedule per-tech filter + tech default to "My jobs only".
 *
 * Source-level assertions on calendar.tsx to verify:
 *  1. Tech role → dropdown not rendered (isTech gate).
 *  2. Admin role → dropdown rendered (testID present).
 *  3. AsyncStorage persistence key structure.
 *  4. Filter logic: specific tech keeps that tech's + unassigned jobs.
 *  5. "All techs" shows everything.
 */
import * as fs from "fs";
import * as path from "path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../app/(app)/schedule/calendar.tsx"),
  "utf-8",
);

describe("Phase S1 — Schedule per-tech filter (source assertions)", () => {
  it("hides tech filter dropdown for tech role via !isTech gate", () => {
    // The dropdown render block should be gated by {!isTech && (
    expect(SRC).toContain('{!isTech && (');
    expect(SRC).toContain('testID="schedule-tech-filter"');
  });

  it("renders dropdown for admin with correct testID", () => {
    expect(SRC).toContain('testID="schedule-tech-filter"');
    expect(SRC).toContain('testID="schedule-tech-filter-row"');
    expect(SRC).toContain('testID="schedule-tech-filter-label"');
  });

  it("persists tech filter to AsyncStorage with per-user key", () => {
    expect(SRC).toContain('TECH_FILTER_KEY = "schedule.tech_filter"');
    // Persistence uses `${TECH_FILTER_KEY}.${uid}` pattern
    expect(SRC).toContain("`${TECH_FILTER_KEY}.${uid}`");
  });

  it("filter logic: specific tech keeps that tech's + unassigned jobs", () => {
    // filteredJobs memo should check technician_id === techFilter OR !technician_id
    expect(SRC).toContain("j.technician_id === techFilter || !j.technician_id");
  });

  it('filter logic: "all" passes through all jobs', () => {
    // When techFilter === "all", return jobs unfiltered
    expect(SRC).toContain('if (techFilter === "all") return jobs;');
  });

  it("tech picker modal has option for all techs and per-tech entries", () => {
    expect(SRC).toContain('testID="tech-filter-option-all"');
    expect(SRC).toContain("tech-filter-option-${t.id}");
  });

  it("default tech filter for tech role is user's technician_id", () => {
    // On mount effect, tech role defaults to user?.technician_id
    expect(SRC).toContain('setTechFilter(isTech ? (user?.technician_id || "all") : "all")');
  });

  it("dayJobs, weekCounts, jobsByDay all use filteredJobs", () => {
    // All three memos should reference filteredJobs, not raw jobs
    expect(SRC).toContain("filteredJobs.filter((j) => j.scheduled_date === focusISO)");
    expect(SRC).toContain("for (const j of filteredJobs) {\n      const d = j.scheduled_date?.slice(0, 10)");
    expect(SRC).toContain("for (const j of filteredJobs) {\n      const d = j.scheduled_date || \"\"");
  });
});
