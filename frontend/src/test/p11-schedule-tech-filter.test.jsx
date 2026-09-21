/**
 * Phase P11 · Feb-2026 — Schedule Tech Filter · Server-Side + Crewless-Tech Fix.
 *
 * Locks in the four acceptance points:
 *
 *   1. Crewless-tech self-heal parity — a tech with NO ``crew_id``
 *      anywhere in the fixture whose canonical id equals the stored
 *      filter value is NEVER cleared. Verified across initial mount
 *      AND a subsequent techs-list reload.
 *   2. ``jobMatchesLane(job, T1)`` returns true when a job carries
 *      T1 under ANY of the five assignment fields
 *      (``technician_id`` / ``assigned_technician_id`` /
 *      ``assigned_to`` / ``tech_user_id`` / ``crew_id``).
 *   3. Selecting a specific tech fires ``GET /jobs?...&technician_id=T1``.
 *      Selecting "All" fires a fetch with NO ``technician_id=`` param.
 *   4. Legacy user-id-shaped stored value that doesn't exist in the
 *      canonical set → self-heal clears it with exactly ONE
 *      ``console.warn``.
 *
 * Testing strategy:
 *   * Acceptance point (2) is a pure unit test on the exported
 *     ``jobMatchesLane`` helper — no mount needed.
 *   * Acceptance points (1), (3), (4) use source-inspection contracts
 *     on ``CalendarSchedule.jsx``. The full page is 3 kLOC and pulls
 *     react-big-calendar + @vis.gl/react-google-maps + supabase-adjacent
 *     realtime deps that make a JSDOM mount prohibitive; a targeted
 *     scan for the exact invariants (predicate shape, effect deps,
 *     API URL construction) is the pragmatic contract this file needs.
 */
import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";


const SRC_PATH = path.resolve(
  __dirname, "../pages/schedule/CalendarSchedule.jsx",
);
const scheduleSrc = fs.readFileSync(SRC_PATH, "utf8");


// ─── Unit tests on the exported helper (acceptance point 2) ────────
import { jobMatchesLane } from "../pages/schedule/CalendarSchedule";


describe("Phase P11 · jobMatchesLane · K42-parity disjunction", () => {
  const T1 = "tech-1-id";
  const T2 = "tech-2-id";

  it("returns true when job.technician_id === laneId (canonical primary)", () => {
    expect(jobMatchesLane({ technician_id: T1 }, T1)).toBe(true);
  });

  it("returns true when job.assigned_technician_id === laneId (R1.1 fallback)", () => {
    expect(jobMatchesLane({ assigned_technician_id: T1 }, T1)).toBe(true);
  });

  it("returns true when job.assigned_to === laneId (legacy dispatch)", () => {
    expect(jobMatchesLane({ assigned_to: T1 }, T1)).toBe(true);
  });

  it("returns true when job.tech_user_id === laneId (reorder-day-route)", () => {
    expect(jobMatchesLane({ tech_user_id: T1 }, T1)).toBe(true);
  });

  it("returns true when job.crew_id === laneId (crew-lane dispatch)", () => {
    expect(jobMatchesLane({ crew_id: T1 }, T1)).toBe(true);
  });

  it("returns false when NONE of the five fields match laneId", () => {
    const other = { technician_id: T2, assigned_to: T2, tech_user_id: T2 };
    expect(jobMatchesLane(other, T1)).toBe(false);
  });

  it("returns true (pass) when laneId is empty — the 'All' pseudo-value", () => {
    expect(jobMatchesLane({ technician_id: "anything" }, "")).toBe(true);
    expect(jobMatchesLane({ technician_id: "anything" }, null)).toBe(true);
    expect(jobMatchesLane({ technician_id: "anything" }, undefined)).toBe(true);
  });

  it("returns false when job is null/undefined AND laneId is set", () => {
    expect(jobMatchesLane(null, "T1")).toBe(false);
    expect(jobMatchesLane(undefined, "T1")).toBe(false);
  });

  it("does NOT match on a substring / prefix — strict equality only", () => {
    expect(jobMatchesLane({ technician_id: "tech-1-id-suffix" }, "tech-1-id")).toBe(false);
    expect(jobMatchesLane({ technician_id: "prefix-tech-1-id" }, "tech-1-id")).toBe(false);
  });
});


// ─── Source-inspection contracts (acceptance points 1, 3, 4) ───────

describe("Phase P11 · self-heal predicate loosened (crewless-tech parity)", () => {
  it("self-heal effect NO LONGER references crew_id / crew_anchor in the invalidation predicate", () => {
    const start = scheduleSrc.indexOf("Phase P5 · Feb-2026 — Legacy tech-filter self-heal");
    expect(start).toBeGreaterThan(0);
    const end = scheduleSrc.indexOf("Phase F6a · Feb-2026 — resolved tech-id set", start);
    expect(end).toBeGreaterThan(start);
    const slab = scheduleSrc.slice(start, end);
    // The invalidation check is a plain ``canonicalIds.has(techId)``.
    expect(slab).toMatch(/if\s*\(\s*canonicalIds\.has\(techId\)\s*\)\s*return/);
    // Extract just the effect body (from ``useEffect(() => {`` to the
    // matching ``}, [...]`` line) so we don't false-positive on
    // ``crewId`` references elsewhere in the containing slab.
    const bodyStart = slab.indexOf("useEffect(() => {");
    const bodyEnd = slab.indexOf("}, [techs, techId, _techFilterKey]");
    expect(bodyStart).toBeGreaterThan(-1);
    expect(bodyEnd).toBeGreaterThan(bodyStart);
    const body = slab.slice(bodyStart, bodyEnd);
    // Only actual reads of crew-related identifiers are the offense.
    expect(body).not.toMatch(/\bcrewId\b/);
    expect(body).not.toMatch(/\bcrew_anchor\b/);
    expect(body).not.toMatch(/\bcrewMember/);
  });

  it("guard runs at most once per techs-list load (ref keys on techs identity, not a boolean)", () => {
    // The pre-P11 shape was ``useRef(false)`` + ``.current = true``
    // which hard-locked the effect after the FIRST firing — a
    // subsequent techs reload could not re-evaluate. P11 keys the
    // ref on the techs list identity itself.
    expect(scheduleSrc).toMatch(
      /_healedLegacyTechFilterRef\s*=\s*React\.useRef\(null\)/,
    );
    expect(scheduleSrc).toMatch(
      /_healedLegacyTechFilterRef\.current\s*===\s*techs/,
    );
    expect(scheduleSrc).toMatch(
      /_healedLegacyTechFilterRef\.current\s*=\s*techs/,
    );
    // Anti-pattern: the boolean-flag lock is GONE.
    expect(scheduleSrc).not.toMatch(
      /_healedLegacyTechFilterRef\s*=\s*React\.useRef\(false\)/,
    );
    expect(scheduleSrc).not.toMatch(
      /_healedLegacyTechFilterRef\.current\s*=\s*true/,
    );
  });

  it("clears via setTechId('') + setParam + localStorage.removeItem AND emits exactly ONE console.warn", () => {
    // Land inside the P5 self-heal block.
    const start = scheduleSrc.indexOf("Phase P5 · Feb-2026 — Legacy tech-filter self-heal");
    const end = scheduleSrc.indexOf("Phase F6a · Feb-2026 — resolved tech-id set", start);
    const slab = scheduleSrc.slice(start, end);
    // Exactly one console.warn in the block — no double-log after loop.
    const warns = (slab.match(/console\.warn\(/g) || []);
    expect(warns.length).toBe(1);
    // Cleanup path is present.
    expect(slab).toMatch(/setTechId\(""\)/);
    expect(slab).toMatch(/setParam\("technician_id",\s*""\)/);
    expect(slab).toMatch(/localStorage\.removeItem\(_techFilterKey\)/);
  });
});


describe("Phase P11 · server-side tech scope on /jobs fetch", () => {
  it("load() appends &technician_id=<techId> to the /jobs URL when a specific tech is selected", () => {
    // The exact idiom the fetch site uses.
    expect(scheduleSrc).toMatch(
      /const\s+_techScope\s*=\s*\(techId\s*&&\s*techId\s*!==\s*"all"\)/,
    );
    expect(scheduleSrc).toMatch(
      /`&technician_id=\$\{encodeURIComponent\(techId\)\}`/,
    );
    // The scope segment is spliced into the URL template.
    expect(scheduleSrc).toMatch(
      /`\/jobs\?start=\$\{start\}&end=\$\{end\}[\s\S]{0,120}\$\{_techScope\}`/,
    );
  });

  it("no /jobs URL is hardcoded WITHOUT the _techScope splice (regression net)", () => {
    // Locate the ``api.get(...`/jobs?...`)`` call site directly and
    // pull the ~500-char slab around it — the outer template literal
    // interpolates an inner one for the ``crew_id`` param, so a
    // naïve `` `/jobs?...` `` regex stops at the first nested
    // backtick. Instead, scan the ``api.get`` args line-by-line for
    // the ``/jobs?start=`` marker.
    const idx = scheduleSrc.indexOf("api.get(\n          `/jobs?start=");
    expect(idx).toBeGreaterThan(-1);
    const slab = scheduleSrc.slice(idx, idx + 500);
    // Every /jobs-URL construction MUST splice ``${_techScope}``
    // AFTER the ``&end=…`` segment. The pre-P11 regression removed
    // this splice entirely — that's what this test guards against.
    expect(slab).toContain("${_techScope}");
    expect(slab).toMatch(/api\.get\(\s*`\/jobs\?start=/);
  });

  it("'All' (empty techId) yields no technician_id= query segment", () => {
    // ``_techScope`` is empty when ``techId`` is falsy or === "all".
    expect(scheduleSrc).toMatch(
      /_techScope\s*=\s*\(techId\s*&&\s*techId\s*!==\s*"all"\)\s*\?\s*`&technician_id=[^`]+`\s*:\s*""/,
    );
  });

  it("techId changes trigger a forced refetch (own useEffect, force: true)", () => {
    // Same shape as the F6a crewId hook — force:true so the cache-
    // window guard doesn't short-circuit the refetch.
    expect(scheduleSrc).toMatch(
      /useEffect\(\(\)\s*=>\s*\{\s*load\(\s*\{\s*force:\s*true\s*\}\s*\);\s*\},\s*\[techId\]\)/,
    );
  });
});


describe("Phase P11 · client-side predicate is the K42-parity helper", () => {
  it("filteredJobs uses jobMatchesLane — no bare j.technician_id !== techId check remains", () => {
    // Locate the ``filteredJobs = useMemo`` block.
    const start = scheduleSrc.indexOf("const filteredJobs = useMemo");
    const end = scheduleSrc.indexOf("}, [rawJobs, q, techId", start);
    expect(start).toBeGreaterThan(-1);
    expect(end).toBeGreaterThan(start);
    const body = scheduleSrc.slice(start, end);
    expect(body).toMatch(/jobMatchesLane\(j,\s*techId\)/);
    // Anti-pattern: bare single-field check must be gone from ACTUAL
    // code paths. The pre-P11 shape lives inside the P11 docstring
    // as a "here's what we removed" reminder, so strip block comments
    // AND line comments before scanning.
    const stripped = body
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .split("\n")
      .filter((ln) => !/^\s*\/\//.test(ln))
      .join("\n");
    expect(stripped).not.toMatch(/j\.technician_id\s*!==\s*techId\s*&&/);
  });
});
