/**
 * Feb-2026 · OpsHub TeamRoster — "All (Both)" filter chip fix.
 *
 * Prior bug: the chip's ``filter`` key was ``all_both`` but the
 * ``_roleKey`` function never returned that string (returns
 * ``pool_tech`` / ``landscape_tech`` / ``tech_both`` / ``admin`` /
 * ``all`` (admin+both) / ``unassigned``). The base useMemo did
 * ``k === filter`` → filtering by ``all_both`` matched nothing →
 * empty roster displayed.
 *
 * Fix (per product intent): ``all_both`` = union of every
 * technician regardless of specialty (pool + landscape +
 * cross-trained). Locked here with a pure-function replica of the
 * fix's filter predicate — avoids needing to render the full
 * OpsHub tree (heavy imports, useAuth context, etc.).
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const SRC = readFileSync(
  resolve(__dirname, "../pages/ops/OpsHub.jsx"),
  "utf8",
);

/**
 * Mirror of ``_roleKey`` from OpsHub.jsx. Kept private-to-test —
 * if the OpsHub definition ever drifts, the source-string
 * assertion below will fail before this replica silently diverges.
 *
 * Feb-2026 · updated with the department-alias sets so pool_tech /
 * landscape_tech / tech_both (real prod data shapes) resolve to
 * the canonical filter keys.
 */
const _POOL = new Set(["pool", "pool_tech"]);
const _LAND = new Set(["landscaping", "landscape_tech"]);
const _BOTH = new Set(["both", "tech_both"]);

function _roleKey(user) {
  const role = (user?.role || "").toLowerCase();
  const dept = (user?.department || "").trim().toLowerCase();
  if (role === "super_admin") return "super_admin";
  if (role === "admin" && _BOTH.has(dept)) return "all";
  if (role === "admin") return "admin";
  if (role === "technician" && _BOTH.has(dept)) return "tech_both";
  if (role === "technician" && _POOL.has(dept)) return "pool_tech";
  if (role === "technician" && _LAND.has(dept)) return "landscape_tech";
  return "unassigned";
}

/**
 * Mirror of the post-fix ``filtered`` predicate.
 */
function _filterUser(u, filter) {
  const k = _roleKey(u);
  if (filter === "all") return true;
  if (filter === "unassigned") return k === "unassigned";
  if (filter === "all_both") {
    return k === "pool_tech" || k === "landscape_tech" || k === "tech_both";
  }
  return k === filter;
}

const ROSTER = [
  { id: "u-adm",     role: "admin",       department: "pool",         name: "Admin Alice" },
  { id: "u-adm-b",   role: "admin",       department: "both",         name: "Admin Both" },
  { id: "u-super",   role: "super_admin", department: "both",         name: "Super Sam" },
  { id: "u-pool",    role: "technician",  department: "pool",         name: "Pool Pete" },
  { id: "u-land",    role: "technician",  department: "landscaping",  name: "Landscape Larry" },
  { id: "u-both",    role: "technician",  department: "both",         name: "Cross-Trained Cara" },
  { id: "u-un",      role: "technician",  department: null,           name: "Unassigned Uma" },
];

describe("OpsHub TeamRoster — filter predicate", () => {
  it("`all_both` returns the union of pool + landscape + cross-trained techs", () => {
    const out = ROSTER.filter((u) => _filterUser(u, "all_both"));
    const ids = out.map((r) => r.id).sort();
    expect(ids).toEqual(["u-both", "u-land", "u-pool"]);
  });

  it("`all_both` does NOT include admins (previous ambiguity)", () => {
    const out = ROSTER.filter((u) => _filterUser(u, "all_both"));
    expect(out.map((r) => r.id)).not.toContain("u-adm");
    expect(out.map((r) => r.id)).not.toContain("u-adm-b");
    expect(out.map((r) => r.id)).not.toContain("u-super");
  });

  it("`all_both` does NOT include unassigned (implicit)", () => {
    const out = ROSTER.filter((u) => _filterUser(u, "all_both"));
    expect(out.map((r) => r.id)).not.toContain("u-un");
  });

  it("`all` still returns every row (regression guard)", () => {
    expect(ROSTER.filter((u) => _filterUser(u, "all"))).toHaveLength(ROSTER.length);
  });

  it("`pool_tech` filters to pool-only techs", () => {
    const out = ROSTER.filter((u) => _filterUser(u, "pool_tech"));
    expect(out.map((r) => r.id)).toEqual(["u-pool"]);
  });

  it("`landscape_tech` filters to landscape-only techs", () => {
    const out = ROSTER.filter((u) => _filterUser(u, "landscape_tech"));
    expect(out.map((r) => r.id)).toEqual(["u-land"]);
  });

  it("`tech_both` filters to cross-trained-only techs", () => {
    const out = ROSTER.filter((u) => _filterUser(u, "tech_both"));
    expect(out.map((r) => r.id)).toEqual(["u-both"]);
  });

  it("`admin` filters to non-both admins", () => {
    const out = ROSTER.filter((u) => _filterUser(u, "admin"));
    expect(out.map((r) => r.id)).toEqual(["u-adm"]);
  });

  it("`unassigned` filters to techs with no department", () => {
    const out = ROSTER.filter((u) => _filterUser(u, "unassigned"));
    expect(out.map((r) => r.id)).toEqual(["u-un"]);
  });

  // ═════════════════════════════════════════════════════════════════════
  // Feb-2026 · Department-alias coverage — real prod data ships
  // ``pool_tech`` / ``landscape_tech`` / ``tech_both`` (the
  // tech-form enum), not the legacy ``pool`` / ``landscaping`` /
  // ``both`` shape. Regression test that both alias sets resolve
  // correctly + regional labels stay ``unassigned``.
  // ═════════════════════════════════════════════════════════════════════
  it("department=`pool_tech` maps to pool_tech and appears in All (Both)", () => {
    const u = { id: "u-mt", role: "technician", department: "pool_tech",
                 name: "Modern Pool Tech" };
    expect(_roleKey(u)).toBe("pool_tech");
    expect(_filterUser(u, "pool_tech")).toBe(true);
    expect(_filterUser(u, "all_both")).toBe(true);
    // Sanity: NOT in unrelated chips.
    expect(_filterUser(u, "landscape_tech")).toBe(false);
    expect(_filterUser(u, "tech_both")).toBe(false);
    expect(_filterUser(u, "unassigned")).toBe(false);
  });

  it("department=`landscape_tech` maps to landscape_tech and appears in All (Both)", () => {
    const u = { id: "u-ml", role: "technician", department: "landscape_tech",
                 name: "Modern Landscape Tech" };
    expect(_roleKey(u)).toBe("landscape_tech");
    expect(_filterUser(u, "landscape_tech")).toBe(true);
    expect(_filterUser(u, "all_both")).toBe(true);
    expect(_filterUser(u, "pool_tech")).toBe(false);
  });

  it("department=`tech_both` maps to tech_both and appears in All (Both)", () => {
    const u = { id: "u-mb", role: "technician", department: "tech_both",
                 name: "Modern Cross-Trained" };
    expect(_roleKey(u)).toBe("tech_both");
    expect(_filterUser(u, "tech_both")).toBe(true);
    expect(_filterUser(u, "all_both")).toBe(true);
  });

  it("department=` Pool_Tech ` — whitespace + case-insensitive — still maps", () => {
    const u = { id: "u-wc", role: "technician", department: " Pool_Tech ",
                 name: "Whitespace Case Tech" };
    expect(_roleKey(u)).toBe("pool_tech");
    expect(_filterUser(u, "pool_tech")).toBe(true);
    expect(_filterUser(u, "all_both")).toBe(true);
  });

  it("regional department=`north` stays unassigned (drift NOT reclassified)", () => {
    const u = { id: "u-nr", role: "technician", department: "north",
                 name: "Regional North Tech" };
    // Regional labels are NOT chemistry specialties — the fix
    // intentionally does NOT reclassify them so ops can spot the
    // data drift.
    expect(_roleKey(u)).toBe("unassigned");
    expect(_filterUser(u, "unassigned")).toBe(true);
    expect(_filterUser(u, "pool_tech")).toBe(false);
    expect(_filterUser(u, "landscape_tech")).toBe(false);
    expect(_filterUser(u, "tech_both")).toBe(false);
    expect(_filterUser(u, "all_both")).toBe(false);
  });

  it("department=null stays unassigned", () => {
    const u = { id: "u-nl", role: "technician", department: null,
                 name: "Null Dept Tech" };
    expect(_roleKey(u)).toBe("unassigned");
    expect(_filterUser(u, "unassigned")).toBe(true);
    expect(_filterUser(u, "all_both")).toBe(false);
  });

  it("All (Both) union includes modern-alias techs (integration case)", () => {
    // The exact regression the tester hit — a roster where every
    // real tech carries the modern enum. Before the alias fix all
    // three rows resolved to ``unassigned`` and "All (Both)"
    // returned []. Now they all surface.
    const modern = [
      { id: "u-mp", role: "technician", department: "pool_tech" },
      { id: "u-ml", role: "technician", department: "landscape_tech" },
      { id: "u-mb", role: "technician", department: "tech_both" },
    ];
    const out = modern.filter((u) => _filterUser(u, "all_both"));
    expect(out.map((r) => r.id).sort()).toEqual(["u-mb", "u-ml", "u-mp"]);
  });
});

describe("OpsHub TeamRoster — source-level guard", () => {
  it("the fix branch is present in OpsHub.jsx", () => {
    // Lock the specific fix — if this predicate drifts back to
    // ``k === filter`` for ``all_both``, this catches it.
    expect(SRC).toMatch(
      /if\s*\(\s*filter\s*===\s*"all_both"\s*\)\s*\{[\s\S]{0,400}?pool_tech[\s\S]{0,80}?landscape_tech[\s\S]{0,80}?tech_both/,
    );
  });

  it("`_roleKey` mirror in this test matches the OpsHub source", () => {
    // Guards against silent drift between the source and this
    // test file's mirror. Substring anchors on the branches that
    // matter for the fix.
    expect(SRC).toMatch(/if\s*\(role\s*===\s*"admin"\s*&&\s*_DEPT_ALIASES_BOTH\.has\(dept\)\)\s*return\s*"all";/);
    expect(SRC).toMatch(/if\s*\(role\s*===\s*"technician"\s*&&\s*_DEPT_ALIASES_BOTH\.has\(dept\)\)\s*return\s*"tech_both";/);
    expect(SRC).toMatch(/if\s*\(role\s*===\s*"technician"\s*&&\s*_DEPT_ALIASES_POOL\.has\(dept\)\)\s*return\s*"pool_tech";/);
    expect(SRC).toMatch(/if\s*\(role\s*===\s*"technician"\s*&&\s*_DEPT_ALIASES_LAND\.has\(dept\)\)\s*return\s*"landscape_tech";/);
  });

  it("department alias sets include both legacy + modern shapes", () => {
    // Feb-2026 · alias sets must contain BOTH the legacy strings
    // (``pool`` / ``landscaping`` / ``both``) AND the modern
    // tech-form enum (``pool_tech`` / ``landscape_tech`` /
    // ``tech_both``) so filter chips work regardless of write path.
    expect(SRC).toMatch(
      /_DEPT_ALIASES_POOL\s*=\s*new Set\(\["pool",\s*"pool_tech"\]\)/,
    );
    expect(SRC).toMatch(
      /_DEPT_ALIASES_LAND\s*=\s*new Set\(\["landscaping",\s*"landscape_tech"\]\)/,
    );
    expect(SRC).toMatch(
      /_DEPT_ALIASES_BOTH\s*=\s*new Set\(\["both",\s*"tech_both"\]\)/,
    );
  });

  it("technician-department drift emits a dev-only console.warn (once per dept)", () => {
    // Locks the behavior that regional / unknown departments log a
    // warning in non-production builds but never silently
    // reclassify. The ``_DEPT_DRIFT_WARNED`` Set dedupes so a
    // tenant with 40 ``north`` techs doesn't spam the console.
    expect(SRC).toMatch(/_DEPT_DRIFT_WARNED\s*=\s*new Set\(\)/);
    expect(SRC).toMatch(/process\.env\?\.NODE_ENV\s*!==\s*"production"/);
    expect(SRC).toMatch(/\[OpsHub\] Technician with unrecognized department/);
    // Regional departments must NOT be reclassified — assert
    // ``north`` / ``south`` don't appear INSIDE any alias Set literal.
    // Extract each ``new Set([...])`` literal and check the content.
    const setLits = SRC.match(
      /_DEPT_ALIASES_(?:POOL|LAND|BOTH)\s*=\s*new Set\(\[[^\]]*\]\)/g,
    ) || [];
    expect(setLits.length).toBe(3);
    for (const s of setLits) {
      expect(s).not.toMatch(/\bnorth\b/);
      expect(s).not.toMatch(/\bsouth\b/);
    }
  });
});
