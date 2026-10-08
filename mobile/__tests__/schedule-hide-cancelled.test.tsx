/**
 * INACTIVE-CUSTOMER-CASCADE mobile (b80bf780f) — hide-cancelled toggle.
 * Source-contract test (repo convention for the 2.4k-line calendar screen).
 */
import * as fs from "fs";
import * as path from "path";

const SRC = fs.readFileSync(path.resolve(__dirname, "../app/(app)/schedule/calendar.tsx"), "utf-8");

describe("schedule hide-cancelled toggle", () => {
  it("defaults to hidden and persists under schedule_show_cancelled", () => {
    expect(SRC).toContain("useState(false);\n  useEffect(() => {\n    AsyncStorage.getItem(\"schedule_show_cancelled\")");
    expect(SRC).toContain('if (v === "true") setShowCancelled(true);');
    expect(SRC).toContain('AsyncStorage.setItem("schedule_show_cancelled", String(next))');
  });

  it("filters cancelled/canceled/skipped (case-insensitive) unless toggled on", () => {
    expect(SRC).toContain('new Set(["cancelled", "canceled", "skipped"])');
    expect(SRC).toMatch(/if \(showCancelled\) return filteredJobs;\s+return filteredJobs\.filter\(\s+\(j\) => !CANCELLED_SET\.has\(String\(j\.status \|\| ""\)\.toLowerCase\(\)\)/);
  });

  it("boundary: every rendered list reads visibleJobs, never raw filteredJobs", () => {
    for (const re of [/visibleJobs\.filter\(\(j\) => j\.scheduled_date === focusISO\)/, /for \(const j of visibleJobs\)[\s\S]{0,80}counts\[d\]/, /for \(const j of visibleJobs\)[\s\S]{0,80}\(m\[d\] = m\[d\]/]) {
      expect(SRC).toMatch(re);
    }
    expect(SRC).not.toMatch(/for \(const j of filteredJobs\)/);
    expect(SRC).toContain('testID="schedule-show-cancelled-toggle"');
  });
});
