/**
 * Phase F6a · Feb-2026 — Schedule "All crews" filter wiring test.
 *
 * File-body match test — asserts the crew-filter source is wired
 * end-to-end: crew state, dropdown, chip row, tech-dropdown disable,
 * URL round-trip, and inclusion of `crew_id` in the schedule fetch.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/schedule/CalendarSchedule.jsx"),
  "utf-8",
);

describe("CalendarSchedule · F6a crew filter", () => {
  it("holds a crewId state seeded from the ?crew URL param", () => {
    expect(SRC).toMatch(
      /const \[crewId, setCrewId\] = useState\(params\.get\("crew"\)/,
    );
  });

  it("fetches /crews alongside /technicians on load", () => {
    // Phase Hygiene B · Feb-2026 — schedule loader now passes an explicit
    // timeout (``SCHEDULE_LOAD_TIMEOUT_MS``) as the second arg to
    // ``api.get``.  Relax the regex to accept an optional trailing arg so
    // this contract test doesn't fail on a purely mechanical hardening.
    expect(SRC).toMatch(/api\.get\("\/crews"(?:\s*,[^)]*)?\)/);
  });

  it("passes crew_id into the schedule /jobs fetch when set", () => {
    // Match against a template literal that includes the crew_id param.
    expect(SRC).toMatch(/&crew_id=\$\{encodeURIComponent\(crewId\)\}/);
  });

  it("renders the crew dropdown next to the tech / service / status ones",
     () => {
    expect(SRC).toMatch(/data-testid="calendar-filter-crew"/);
    expect(SRC).toMatch(/All crews<\/option>/);
  });

  it("disables the tech dropdown when a crew is selected", () => {
    // The tech <select> gets `disabled={!!crewId}`.
    expect(SRC).toMatch(/data-testid="calendar-filter-tech"[\s\S]{0,600}disabled=\{!!crewId\}/);
  });

  it("renders the crew-member chips row when a crew is active", () => {
    expect(SRC).toMatch(/data-testid="calendar-crew-chips"/);
    expect(SRC).toMatch(/data-testid=\{`calendar-crew-chip-\$\{tid\}`\}/);
  });

  it("clears the crew filter (and its URL param) via clearFilters", () => {
    expect(SRC).toMatch(/setCrewId\(""\)/);
    expect(SRC).toMatch(/setParam\("crew", ""\)/);
  });

  it("wires a separate reload effect on crewId (bypasses cache guard)",
     () => {
    // Two useEffect blocks: [date] with force:false (unchanged
    // contract from Task B) and [crewId] with force:true.
    expect(SRC).toMatch(
      /useEffect\(\s*\(\)\s*=>\s*\{\s*load\(\s*\{\s*force:\s*true\s*\}\s*\);?\s*\},\s*\[crewId\]\)/,
    );
  });
});
