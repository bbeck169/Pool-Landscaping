/**
 * crew-schedule-fanout-badge.test.ts — MOBILE-CREW-BADGE-PARITY
 *
 * Source-inspection + logic tests for the crew role badge on schedule
 * job cards. Mirrors web CREW-SCHEDULE-FANOUT (commit a30f05741).
 */
import * as fs from "fs";
import * as path from "path";

const SRC = fs.readFileSync(
  path.resolve(__dirname, "../app/(app)/schedule/calendar.tsx"),
  "utf-8",
);

describe("MOBILE-CREW-BADGE-PARITY — source audit", () => {
  it("contains the crew_id + _crew_role visibility gate", () => {
    expect(SRC).toContain('job.crew_id && (job._crew_role === "direct" || job._crew_role === "member")');
  });

  it("renders 'Crew lead' for _crew_role=direct", () => {
    expect(SRC).toContain('job._crew_role === "direct" ? "Crew lead" : "Crew member"');
  });

  it("testID follows schedule-card-crew-badge-{id} pattern (GridView)", () => {
    expect(SRC).toContain("schedule-card-crew-badge-${job.id}");
  });

  it("testID follows schedule-card-crew-badge-{id} pattern (CalendarView)", () => {
    expect(SRC).toContain("schedule-card-crew-badge-${j.id}");
  });

  it("has accessibilityLabel on the badge", () => {
    const labels = SRC.match(/accessibilityLabel=\{.*?Crew (lead|member).*?\}/g) || [];
    expect(labels.length).toBeGreaterThanOrEqual(2);
  });

  it("uses correct blue colors for direct (lead) badge", () => {
    expect(SRC).toContain('"#DBEAFE"'); // bg
    expect(SRC).toContain('"#1E3A8A"'); // text
    expect(SRC).toContain('"#3B82F6"'); // border
  });

  it("uses correct indigo colors for member badge", () => {
    expect(SRC).toContain('"#E0E7FF"'); // bg
    expect(SRC).toContain('"#3730A3"'); // text
    expect(SRC).toContain('"#6366F1"'); // border
  });

  it("does not render badge when crew_id or _crew_role is absent", () => {
    // The gate is `job.crew_id && (job._crew_role === "direct" || job._crew_role === "member")`
    // If crew_id is falsy or _crew_role is something else, badge doesn't render.
    // Source-level: there is no unconditional badge render without the gate.
    const badgeRenders = SRC.match(/schedule-card-crew-badge/g) || [];
    const gateChecks = SRC.match(/\.crew_id && \(.*\._crew_role === "direct"/g) || [];
    // Each badge render (grid + calendar) is guarded by a gate
    expect(badgeRenders.length).toBe(gateChecks.length);
  });

  it("uses Ionicons people-outline icon (no lucide dependency)", () => {
    expect(SRC).toContain('name="people-outline"');
    expect(SRC).not.toContain("lucide-react-native");
  });
});

// ── Logic unit tests for crew badge rendering ────────────────────
describe("MOBILE-CREW-BADGE-PARITY — badge rendering logic", () => {
  // Mirror the gate exactly
  function shouldShowCrewBadge(job: { crew_id?: string; _crew_role?: string }): boolean {
    return !!(job.crew_id && (job._crew_role === "direct" || job._crew_role === "member"));
  }

  function crewBadgeCopy(role: string): string {
    return role === "direct" ? "Crew lead" : "Crew member";
  }

  it("shows badge for direct crew lead", () => {
    expect(shouldShowCrewBadge({ crew_id: "crew-1", _crew_role: "direct" })).toBe(true);
    expect(crewBadgeCopy("direct")).toBe("Crew lead");
  });

  it("shows badge for crew member", () => {
    expect(shouldShowCrewBadge({ crew_id: "crew-1", _crew_role: "member" })).toBe(true);
    expect(crewBadgeCopy("member")).toBe("Crew member");
  });

  it("hides badge when crew_id is absent", () => {
    expect(shouldShowCrewBadge({ _crew_role: "direct" })).toBe(false);
    expect(shouldShowCrewBadge({ crew_id: "", _crew_role: "direct" })).toBe(false);
  });

  it("hides badge when _crew_role is absent", () => {
    expect(shouldShowCrewBadge({ crew_id: "crew-1" })).toBe(false);
    expect(shouldShowCrewBadge({ crew_id: "crew-1", _crew_role: "" })).toBe(false);
  });

  it("hides badge for unknown _crew_role values", () => {
    expect(shouldShowCrewBadge({ crew_id: "crew-1", _crew_role: "observer" })).toBe(false);
    expect(shouldShowCrewBadge({ crew_id: "crew-1", _crew_role: "admin" })).toBe(false);
  });
});
