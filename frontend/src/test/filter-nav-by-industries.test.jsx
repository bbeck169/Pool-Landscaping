/**
 * Feb-2026 · Nav Tester Follow-ups · Fix 1
 *
 * Covers the TOLERANT SLUG MATCH behaviour baked into
 * ``filterNavByIndustries``.  The helper now normalises both
 * tenant slugs AND entry slugs by:
 *   • lowercase + trim
 *   • ``-`` / whitespace → ``_``
 *   • drop a trailing ``s`` (so plural / singular collapse to a
 *     shared root — "pools" ↔ "pool", "landscapes" ↔ "landscape")
 *
 * Why the tolerance exists:  the signup pipeline normalises
 * inbound "pools" → canonical singular "pool" (see
 * ``backend/routers/signup.py.INDUSTRY_ALIASES``), while the
 * Phase A multi-industry mirror in
 * ``backend/services/industries.INDUSTRIES`` + the frontend
 * mirror ``config/industries.js`` still ship plural slugs.  Prior
 * to this helper's hardening pass a nav entry tagged
 * ``industry: "pools"`` was INVISIBLE to a tenant whose Mongo
 * doc stored ``["pool"]`` — silently nuking the "Specialty
 * Services" nested submenu for every post-Feb-2026 pool tenant.
 */
import { describe, it, expect } from "vitest";
import { filterNavByIndustries } from "@/nav/adminNav";


const E = (industry, label = "x") => ({ to: `/${label}`, label, industry });


describe("filterNavByIndustries · tolerant slug match", () => {
  it("tenant ['pool'] shows an entry tagged industry: 'pool'", () => {
    const out = filterNavByIndustries(
      [E("pool", "a"), E("hvac", "b")],
      ["pool"],
    );
    expect(out.map((e) => e.label)).toEqual(["a"]);
  });

  it("tenant ['pool'] ALSO shows an entry tagged industry: 'pools'", () => {
    const out = filterNavByIndustries(
      [E("pools", "a"), E("hvac", "b")],
      ["pool"],
    );
    expect(out.map((e) => e.label)).toEqual(["a"]);
  });

  it("tenant ['pools'] shows an entry tagged industry: 'pool'", () => {
    const out = filterNavByIndustries(
      [E("pool", "a"), E("hvac", "b")],
      ["pools"],
    );
    expect(out.map((e) => e.label)).toEqual(["a"]);
  });

  it("tenant ['pools'] shows an entry tagged industry: 'pools'", () => {
    const out = filterNavByIndustries(
      [E("pools", "a"), E("hvac", "b")],
      ["pools"],
    );
    expect(out.map((e) => e.label)).toEqual(["a"]);
  });

  it("case-insensitive + whitespace-tolerant on BOTH sides", () => {
    const out = filterNavByIndustries(
      [E("Pools", "a"), E(" POOL ", "b"), E("Hvac", "c")],
      [" Pool  "],
    );
    expect(out.map((e) => e.label).sort()).toEqual(["a", "b"]);
  });

  it("landscape ↔ landscapes also normalise", () => {
    const out = filterNavByIndustries(
      [E("landscape", "a"), E("landscapes", "b"), E("pool", "c")],
      ["landscapes"],
    );
    expect(out.map((e) => e.label).sort()).toEqual(["a", "b"]);
  });

  it("empty tenant industries array → fail-open (show everything)", () => {
    const out = filterNavByIndustries(
      [E("pool", "a"), E("hvac", "b")],
      [],
    );
    expect(out.map((e) => e.label).sort()).toEqual(["a", "b"]);
  });

  it("entry without an industry key is always visible", () => {
    const out = filterNavByIndustries(
      [{ to: "/x", label: "x" }, E("hvac", "y")],
      ["pool"],
    );
    expect(out.map((e) => e.label)).toEqual(["x"]);
  });

  it("tenant with no overlap on either side hides every tagged entry", () => {
    const out = filterNavByIndustries(
      [E("pool", "a"), E("landscaping", "b"), { to: "/x", label: "x" }],
      ["hvac"],
    );
    expect(out.map((e) => e.label)).toEqual(["x"]);
  });

  it("multi-industry tenant — ['pool', 'landscaping'] — unions the match", () => {
    const out = filterNavByIndustries(
      [E("pools", "a"), E("landscaping", "b"), E("hvac", "c")],
      ["pool", "landscaping"],
    );
    expect(out.map((e) => e.label).sort()).toEqual(["a", "b"]);
  });

  it("non-array industries input defaults to fail-open", () => {
    const out = filterNavByIndustries(
      [E("pool", "a")],
      null,
    );
    expect(out.map((e) => e.label)).toEqual(["a"]);
  });
});


describe("filterNavByIndustries · nav-tree integration · pool tenant", () => {
  // Verifies the actual production nav shape ships Specialty
  // Services + Pool Service + Pool Service Report under BOTH the
  // signup-canonical singular ``["pool"]`` AND the Phase A plural
  // ``["pools"]`` — regression guard for the Feb-2026 nav tester
  // Fix 1 bug (specialty submenu hidden for pool-only tenants).
  it("tenant ['pool'] sees Filter Tracker + Salt Cell Tracker " +
     "inside Operations", async () => {
    const { ADMIN_NAV_V2 } = await import("@/nav/adminNav");
    const ops = ADMIN_NAV_V2.find((g) => g.key === "operations");
    expect(ops).toBeTruthy();
    const kept = filterNavByIndustries(ops.entries, ["pool"]);
    const trackers = kept.filter(
      (e) => e.nested === "Specialty Services",
    );
    expect(trackers.map((e) => e.to).sort()).toEqual([
      "/tracking/filter",
      "/tracking/salt-cell",
    ]);
  });

  it("tenant ['pools'] (legacy plural) ALSO sees both trackers", async () => {
    const { ADMIN_NAV_V2 } = await import("@/nav/adminNav");
    const ops = ADMIN_NAV_V2.find((g) => g.key === "operations");
    const kept = filterNavByIndustries(ops.entries, ["pools"]);
    const trackers = kept.filter(
      (e) => e.nested === "Specialty Services",
    );
    expect(trackers.length).toBe(2);
  });

  it("tenant ['hvac'] does NOT see either tracker (pool-gated)", async () => {
    const { ADMIN_NAV_V2 } = await import("@/nav/adminNav");
    const ops = ADMIN_NAV_V2.find((g) => g.key === "operations");
    const kept = filterNavByIndustries(ops.entries, ["hvac"]);
    const trackers = kept.filter(
      (e) => e.nested === "Specialty Services",
    );
    expect(trackers.length).toBe(0);
  });

  it("tenant ['pool'] sees Pool Service + Pool Service Report " +
     "(the other two industry-gated pool rows that were historically " +
     "tagged with the plural ``pools`` slug)", async () => {
    const { ADMIN_NAV_V2 } = await import("@/nav/adminNav");
    const ops = ADMIN_NAV_V2.find((g) => g.key === "operations");
    const reports = ADMIN_NAV_V2.find((g) => g.key === "reports");
    const opsKept = filterNavByIndustries(ops.entries, ["pool"]);
    const reportsKept = filterNavByIndustries(reports.entries, ["pool"]);
    expect(opsKept.find((e) => e.to === "/pool-service")).toBeTruthy();
    expect(
      reportsKept.find((e) => e.to === "/admin/reports/pool-service"),
    ).toBeTruthy();
  });
});


describe("filterNavByIndustries · nav-source slug audit", () => {
  // Grep-lock on the real nav source — no entry should tag itself
  // with a non-canonical slug now that the signup pipeline settled
  // on singular.  Lists in both canonical sets below for easy
  // extension when future industries land.
  it("every ``industry: '...'`` tag in adminNav.js uses a slug that " +
     "normalises to a signup-canonical root", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(
      path.resolve(__dirname, "../nav/adminNav.js"),
      "utf8",
    );
    const matches = [...src.matchAll(/\bindustry:\s*"([^"]+)"/g)];
    expect(matches.length).toBeGreaterThan(0);
    // Signup-canonical singular set (from
    // ``routers/industry_checklists.INDUSTRY_SLUGS``).
    const SINGULAR = new Set([
      "pool", "landscaping", "hvac", "pest_control", "cleaning",
      "solar", "handyman", "plumbing", "electrical", "roofing",
      "painting", "garage_door", "appliance_repair", "locksmith",
      "chimney_sweep", "gutter", "window_cleaning",
      "carpet_cleaning", "pressure_washing", "tree_service",
      "snow_removal", "fencing", "irrigation", "landscape",
    ]);
    const norm = (s) => {
      let v = s.toLowerCase().trim().replace(/-/g, "_");
      if (v.length > 1 && v.endsWith("s")) v = v.slice(0, -1);
      return v;
    };
    for (const m of matches) {
      const slug = m[1];
      const normed = norm(slug);
      expect(
        SINGULAR.has(normed),
        `industry slug "${slug}" (norm="${normed}") not in signup-canonical set`,
      ).toBe(true);
    }
  });
});
