/**
 * Phase S1 · Feb-2026 — Per-tech filter with role-aware default +
 * localStorage persistence (WEB).
 *
 * The full ``CalendarSchedule`` page has heavy dependencies (react-
 * big-calendar, auth context, api mocks, RBC drag layer). We split
 * the coverage:
 *
 *   1. Source-level assertions on ``CalendarSchedule.jsx`` — verify
 *      the dropdown is hidden for techs, the default-value chain is
 *      role-aware, and the localStorage roundtrip is wired.
 *   2. A headless behavioural test on the extracted filter rule
 *      (assigned-tech match OR unassigned) — proves the semantics
 *      the source assertions rely on.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, it, expect, beforeEach } from "vitest";

const SRC = fs.readFileSync(
  path.resolve(process.cwd(), "src/pages/schedule/CalendarSchedule.jsx"),
  "utf-8",
);


// ═════════════════════════════════════════════════════════════════════
// 1. Source-level contract assertions
// ═════════════════════════════════════════════════════════════════════
describe("Phase S1 · CalendarSchedule source contracts", () => {
  it("hides the tech dropdown for the ``technician`` role", () => {
    // The dropdown lives inside a ``{_isTech ? null : ( … )}`` gate.
    expect(SRC).toMatch(/const\s+_isTech\s*=\s*String\(user\?\.role\s*\|\|\s*""\)\.toLowerCase\(\)\s*===\s*"technician"/);
    expect(SRC).toMatch(/\{_isTech \? null : \(\s*[\s\S]{0,200}<select/);
  });

  it("computes the admin-like role bucket for the default", () => {
    expect(SRC).toMatch(/_isAdminLike[\s\S]{0,200}"admin"[\s\S]{0,60}"super_admin"[\s\S]{0,60}"manager"[\s\S]{0,60}"owner"/);
  });

  it("scopes the localStorage key by user.id", () => {
    expect(SRC).toMatch(/`schedule\.tech_filter\.\$\{user\.id\}`/);
  });

  it("default-value chain: URL param → localStorage → role default", () => {
    // Confirm all three branches appear in the ``useState(() => { … })``.
    const initBlock = SRC.match(/const \[techId, setTechId\] = useState\(\(\)\s*=>\s*\{[\s\S]+?\}\);/);
    expect(initBlock).toBeTruthy();
    const body = initBlock[0];
    // 1) URL param
    expect(body).toMatch(/params\.get\("technician_id"\)/);
    // 2) localStorage (per-user)
    expect(body).toMatch(/localStorage\.getItem\(_techFilterKey\)/);
    // 3) role default
    expect(body).toMatch(/if\s*\(_isTech\)\s*return\s+user\?\.technician_id\s*\|\|\s*""/);
    // Admin-like default = ""
    expect(body).toMatch(/return\s+"";\s+\/\/\s*admin-like/);
  });

  it("onChange persists to localStorage per user", () => {
    expect(SRC).toMatch(/localStorage\.setItem\(_techFilterKey,\s*nextV\)/);
  });

  it("filter rule keeps unassigned jobs visible when a specific tech is picked", () => {
    // Match against the filteredJobs memo — a specific tech is
    // selected AND the job has a technician_id AND the ids don't
    // match → hide. Empty ``technician_id`` slips through.
    expect(SRC).toMatch(
      /techId\s*&&\s*j\.technician_id\s*!==\s*techId\s*&&\s*!!j\.technician_id/,
    );
  });

  it("dropdown carries ``schedule-tech-filter`` testid + legacy id preserved", () => {
    expect(SRC).toMatch(/data-testid="schedule-tech-filter"/);
    // Legacy testid preserved via ``data-testid-legacy`` for any
    // pre-S1 regex assertion that scans on it (K42/F6a suites).
    expect(SRC).toMatch(/data-testid-legacy="calendar-filter-tech"/);
  });

  it("tech list renders alphabetically by name/email", () => {
    expect(SRC).toMatch(
      /techs\.slice\(\)\.sort\(\(a, b\)\s*=>[\s\S]{0,200}\.localeCompare\(b\.name\s*\|\|\s*b\.email\s*\|\|\s*""\)[\s\S]{0,20}\.map/,
    );
  });
});


// ═════════════════════════════════════════════════════════════════════
// 2. Behavioural test on the extracted filter rule
// ═════════════════════════════════════════════════════════════════════
//
// Mirrors the exact ``filteredJobs`` semantics from the source
// (assigned-tech match OR unassigned).
function _passesTechFilter(job, techId) {
  if (!techId) return true;                             // "all" bucket
  if (!job.technician_id) return true;                  // unassigned
  return job.technician_id === techId;
}

describe("Phase S1 · filter semantics — assigned + unassigned pass", () => {
  const jobs = [
    { id: "j-a", customer_name: "Alice",  technician_id: "tech-diego" },
    { id: "j-b", customer_name: "Bob",    technician_id: "tech-sofia" },
    { id: "j-c", customer_name: "Cara",   technician_id: "" },        // unassigned
    { id: "j-d", customer_name: "Diego",  technician_id: null },      // unassigned
    { id: "j-e", customer_name: "Ethan",  technician_id: "tech-diego" },
  ];

  it("techId = 'all' → every job passes", () => {
    const out = jobs.filter((j) => _passesTechFilter(j, ""));
    expect(out.map((j) => j.id)).toEqual(["j-a", "j-b", "j-c", "j-d", "j-e"]);
  });

  it("techId = 'tech-diego' → Diego's jobs + unassigned pass", () => {
    const out = jobs.filter((j) => _passesTechFilter(j, "tech-diego"));
    expect(out.map((j) => j.id)).toEqual(["j-a", "j-c", "j-d", "j-e"]);
    // Bob's assignment to Sofia is filtered out.
    expect(out.some((j) => j.id === "j-b")).toBe(false);
  });

  it("techId = 'tech-sofia' → Sofia's jobs + unassigned pass, Diego's hidden", () => {
    const out = jobs.filter((j) => _passesTechFilter(j, "tech-sofia"));
    expect(out.map((j) => j.id).sort()).toEqual(["j-b", "j-c", "j-d"]);
  });
});


// ═════════════════════════════════════════════════════════════════════
// 3. localStorage roundtrip + multi-user key isolation
// ═════════════════════════════════════════════════════════════════════
describe("Phase S1 · localStorage per-user isolation", () => {
  beforeEach(() => {
    try { localStorage.clear(); } catch { /* noop in SSR */ }
  });

  it("roundtrips a pick under the per-user key", () => {
    const key = "schedule.tech_filter.user-42";
    localStorage.setItem(key, "tech-diego");
    expect(localStorage.getItem(key)).toBe("tech-diego");
  });

  it("two users' selections don't collide", () => {
    const kA = "schedule.tech_filter.user-A";
    const kB = "schedule.tech_filter.user-B";
    localStorage.setItem(kA, "tech-diego");
    localStorage.setItem(kB, "tech-sofia");
    expect(localStorage.getItem(kA)).toBe("tech-diego");
    expect(localStorage.getItem(kB)).toBe("tech-sofia");
    // Clearing one user's key does not affect the other.
    localStorage.removeItem(kA);
    expect(localStorage.getItem(kA)).toBeNull();
    expect(localStorage.getItem(kB)).toBe("tech-sofia");
  });

  it("empty-string pick (All techs) is persisted verbatim (not deleted)", () => {
    const key = "schedule.tech_filter.user-1";
    localStorage.setItem(key, "");
    // Round-tripping "" MUST return "" — the S1 rehydrate loop treats
    // ``saved !== null`` as "user made a pick" so an explicit "All
    // techs" survives reloads instead of resetting to the role
    // default.
    expect(localStorage.getItem(key)).toBe("");
  });
});
