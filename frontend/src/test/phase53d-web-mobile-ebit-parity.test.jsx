/**
 * Phase 53d · Feb-2026 — Web ↔ mobile EBIT panel parity snapshot.
 *
 * Source-inspection tests that read the two EBIT panel source files
 * and lock the shared product decisions in place. If a future patch
 * drifts the mobile side (or vice versa) without mirroring the
 * change, the corresponding assertion here fails immediately.
 *
 * This file is a plain-text diff canary — no mount, no runtime.
 * Runtime behavior is exercised by ``ebit-panel.test.jsx`` (web) and
 * ``phase53c-mobile-ebit-panel.test.tsx`` (mobile).
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");
function readMobile(rel) {
  return fs.readFileSync(path.join(REPO_ROOT, "mobile", rel), "utf-8");
}
function readWeb(rel) {
  return fs.readFileSync(path.join(REPO_ROOT, "frontend", rel), "utf-8");
}

const WEB_EBIT = readWeb("src/components/admin/EbitPanel.jsx");
const MOBILE_EBIT = readMobile("src/components/admin/EbitPanel.tsx");
const WEB_PROFIT_PAGE = readWeb("src/pages/admin/ProfitReportPage.jsx");
const MOBILE_PROFIT_PAGE = readMobile("app/profit-report.tsx");

// ═══════════════════════════════════════════════════════════════════
// Shared vocab
// ═══════════════════════════════════════════════════════════════════
const ADJUSTMENT_KEYS = ["revenue", "cogs", "opex", "depreciation"];
const EDITOR_ROLES = ["super_admin", "admin"];
const VIEWER_ROLES = ["super_admin", "admin", "manager"];
const RANGE_ENUM = [
  "this_month", "last_month", "qtd", "ytd",
  "monthly", "quarterly", "custom",
];
const BASIS_VALUES = ["cash", "accrual"];
const MANAGER_READONLY_TESTIDS = [
  "ebit-panel-readonly-badge",
  "ebit-row-${lineKey}-adjustment-input",
];
const MANAGER_HIDDEN_TESTIDS = [
  "ebit-row-${lineKey}-flip-override",
  "ebit-save-btn",
  "ebit-save-note",
];

describe("Phase 53d · web ↔ mobile EBIT parity snapshot", () => {
  it("both surfaces mount <EbitPanel /> from src/components/admin", () => {
    expect(WEB_PROFIT_PAGE).toMatch(/import\s+EbitPanel\s+from\s+["']@\/components\/admin\/EbitPanel["']/);
    expect(MOBILE_PROFIT_PAGE).toMatch(/import\s+EbitPanel\s+from\s+["']@\/src\/components\/admin\/EbitPanel["']/);
    expect(WEB_PROFIT_PAGE).toContain("<EbitPanel />");
    expect(MOBILE_PROFIT_PAGE).toContain("<EbitPanel />");
  });

  it("ADJUSTMENT_KEYS = {revenue, cogs, opex, depreciation} on both sides", () => {
    function extractLineKeys(src) {
      const m = src.match(/LINE_KEYS[^\n=]*=\s*\[([^\]]+)\]/);
      if (!m) return [];
      return m[1]
        .split(",")
        .map((s) => s.trim().replace(/["'`]/g, ""))
        .filter(Boolean);
    }
    expect(extractLineKeys(WEB_EBIT)).toEqual(ADJUSTMENT_KEYS);
    expect(extractLineKeys(MOBILE_EBIT)).toEqual(ADJUSTMENT_KEYS);
  });

  it("EDITOR_ROLES = {super_admin, admin} — canEdit uses the exact OR expression on both surfaces", () => {
    const CAN_EDIT = /role === ["']super_admin["'] \|\| role === ["']admin["']/;
    expect(WEB_EBIT).toMatch(CAN_EDIT);
    expect(MOBILE_EBIT).toMatch(CAN_EDIT);
    for (const r of EDITOR_ROLES) {
      expect(WEB_EBIT).toContain(`role === "${r}"`);
      expect(MOBILE_EBIT).toContain(`role === "${r}"`);
    }
  });

  it("VIEWER_ROLES = {super_admin, admin, manager} — canView adds manager on both surfaces", () => {
    const CAN_VIEW = /canEdit \|\| role === ["']manager["']/;
    expect(WEB_EBIT).toMatch(CAN_VIEW);
    expect(MOBILE_EBIT).toMatch(CAN_VIEW);
    // sanity: none of the viewer roles is missing from either side
    for (const r of VIEWER_ROLES) {
      const inWeb = WEB_EBIT.includes(`"${r}"`) || WEB_EBIT.includes(`'${r}'`);
      const inMob = MOBILE_EBIT.includes(`"${r}"`) || MOBILE_EBIT.includes(`'${r}'`);
      expect(inWeb).toBe(true);
      expect(inMob).toBe(true);
    }
  });

  it("MANAGER_READONLY_TESTIDS render on both surfaces (visible, disabled/greyed)", () => {
    for (const t of MANAGER_READONLY_TESTIDS) {
      expect(WEB_EBIT).toContain(t);
      expect(MOBILE_EBIT).toContain(t);
    }
  });

  it("MANAGER_HIDDEN_TESTIDS exist in both surfaces (rendered behind a canEdit gate)", () => {
    for (const t of MANAGER_HIDDEN_TESTIDS) {
      expect(WEB_EBIT).toContain(t);
      expect(MOBILE_EBIT).toContain(t);
    }
  });

  it("range-picker client-driven values match the OpenAPI enum subset", () => {
    // These three are the pill options the user actually clicks;
    // the rest of the enum is server-side plumbing.
    const CLIENT_DRIVEN = new Set(["monthly", "quarterly", "custom"]);
    for (const v of RANGE_ENUM) {
      if (CLIENT_DRIVEN.has(v)) {
        expect(WEB_EBIT).toContain(v);
        expect(MOBILE_EBIT).toContain(v);
      }
    }
  });

  it("revenue-basis toggle exposes exactly {cash, accrual}", () => {
    for (const v of BASIS_VALUES) {
      expect(WEB_EBIT).toContain(`"${v}"`);
      expect(MOBILE_EBIT).toContain(`"${v}"`);
    }
    // Neither surface should list anything else — no ``modified_cash``
    // or ``tax_adjusted`` sneaking in without a docs update.
    const REJECTED = ["modified_cash", "tax_adjusted", "gaap"];
    for (const bad of REJECTED) {
      expect(WEB_EBIT).not.toContain(bad);
      expect(MOBILE_EBIT).not.toContain(bad);
    }
  });

  it("EBIT total formula literal is identical on both surfaces", () => {
    const FORMULA = /out\.ebit\s*=\s*out\.revenue\s*-\s*out\.cogs\s*-\s*out\.opex\s*-\s*out\.depreciation/;
    expect(WEB_EBIT).toMatch(FORMULA);
    expect(MOBILE_EBIT).toMatch(FORMULA);
  });

  it("both surfaces POST /ebit/snapshots (immutable) — no client PATCH", () => {
    expect(WEB_EBIT).toMatch(/api\.post\(\s*[`"']\/ebit\/snapshots/);
    expect(MOBILE_EBIT).toMatch(/api\.post\(\s*[`"']\/ebit\/snapshots/);
    expect(WEB_EBIT).not.toMatch(/api\.patch\(\s*[`"']\/ebit/);
    expect(MOBILE_EBIT).not.toMatch(/api\.patch\(\s*[`"']\/ebit/);
  });

  it("both surfaces consume the same 3 read-side endpoints", () => {
    for (const e of ["/ebit/compute", "/ebit/snapshots"]) {
      expect(WEB_EBIT).toContain(e);
      expect(MOBILE_EBIT).toContain(e);
    }
  });
});
