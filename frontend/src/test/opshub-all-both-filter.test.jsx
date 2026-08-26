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
 */
function _roleKey(user) {
  const role = (user?.role || "").toLowerCase();
  const dept = (user?.department || "").toLowerCase();
  if (role === "super_admin") return "super_admin";
  if (role === "admin" && dept === "both") return "all";
  if (role === "admin") return "admin";
  if (role === "technician" && dept === "both") return "tech_both";
  if (role === "technician" && dept === "pool") return "pool_tech";
  if (role === "technician" && dept === "landscaping") return "landscape_tech";
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
    expect(SRC).toMatch(/if\s*\(role\s*===\s*"admin"\s*&&\s*dept\s*===\s*"both"\)\s*return\s*"all";/);
    expect(SRC).toMatch(/if\s*\(role\s*===\s*"technician"\s*&&\s*dept\s*===\s*"both"\)\s*return\s*"tech_both";/);
    expect(SRC).toMatch(/if\s*\(role\s*===\s*"technician"\s*&&\s*dept\s*===\s*"pool"\)\s*return\s*"pool_tech";/);
    expect(SRC).toMatch(/if\s*\(role\s*===\s*"technician"\s*&&\s*dept\s*===\s*"landscaping"\)\s*return\s*"landscape_tech";/);
  });
});
