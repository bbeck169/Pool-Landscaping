/**
 * Phase (Feb-2026) — mobile admin drawer parity locking suite.
 *
 * The mobile drawer at ``mobile/app/(app)/more.tsx`` now renders from
 * a single data source at ``mobile/src/nav/adminNav.ts``. Every
 * canonical web group is mirrored, plus a synthetic Quick-Access
 * shortcut group at the very top per user request.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const R = (p) => fs.readFileSync(path.resolve(__dirname, "../../..", p), "utf-8");
const E = (p) => fs.existsSync(path.resolve(__dirname, "../../..", p));

const NAV = R("mobile/src/nav/adminNav.ts");
const MORE = R("mobile/app/(app)/more.tsx");

describe("Nav data · adminNav.ts (source of truth)", () => {
  it("exports QUICK_ACCESS, ADMIN_NAV, FLAT_ENTRIES, canSeeEntry, NavTier", () => {
    expect(NAV).toMatch(/export\s+const\s+QUICK_ACCESS\s*:/);
    expect(NAV).toMatch(/export\s+const\s+ADMIN_NAV\s*:/);
    expect(NAV).toMatch(/export\s+const\s+FLAT_ENTRIES\s*:/);
    expect(NAV).toMatch(/export\s+function\s+canSeeEntry/);
    expect(NAV).toMatch(/export\s+type\s+NavTier/);
  });

  it("mirrors the eight canonical web groups in order", () => {
    const groups = [
      "finance",
      "ai_employees",
      "marketing",
      "operations",
      "customers",
      "reports",
      "communications",
      "reviews",
    ];
    let lastIdx = -1;
    for (const g of groups) {
      const idx = NAV.indexOf(`key: "${g}"`);
      expect(idx).toBeGreaterThan(lastIdx);
      lastIdx = idx;
    }
  });

  it("Quick Access lists Schedule, Dispatch, Team in that order", () => {
    const qa = NAV.match(/QUICK_ACCESS[\s\S]*?entries:\s*\[([\s\S]*?)\]/)?.[1] || "";
    const s = qa.indexOf('route: "/schedule"');
    const d = qa.indexOf('route: "/dispatch"');
    const t = qa.indexOf('route: "/team"');
    expect(s).toBeGreaterThan(-1);
    expect(d).toBeGreaterThan(s);
    expect(t).toBeGreaterThan(d);
  });

  it("classifies every entry with a valid tier (t1 / t2 / t3)", () => {
    const tiers = Array.from(NAV.matchAll(/tier:\s*"(t[123])"/g)).map((m) => m[1]);
    expect(tiers.length).toBeGreaterThan(80);
    for (const t of tiers) expect(["t1", "t2", "t3"]).toContain(t);
  });

  it("has T1 + T2 + T3 counts in the Phase-B ballpark (Quick=3 + real groups + T3)", () => {
    const count = (t) => (NAV.match(new RegExp(`tier:\\s*"${t}"`, "g")) || []).length;
    const t1 = count("t1"); const t2 = count("t2"); const t3 = count("t3");
    // Quick Access adds three t1 dupes on top of the canonical groups.
    expect(t1).toBeGreaterThanOrEqual(50);
    expect(t2).toBeGreaterThanOrEqual(20);
    // Phase 35 · Feb-2026 · reclassified Master Invoices + Autobilling
    // Runs from T3 (web-only stubs) to T1 (real mobile pages); threshold
    // lowered accordingly. Any further T3 flips should update this too.
    expect(t3).toBeGreaterThanOrEqual(13);
    // Sanity: total across the file lines up with what we sized in the delivery.
    expect(t1 + t2 + t3).toBeGreaterThanOrEqual(85);
  });
});

describe("Shared stub / fallback components", () => {
  it("mobile/src/components/ComingSoonPage.tsx exists and exports default", () => {
    expect(E("mobile/src/components/ComingSoonPage.tsx")).toBe(true);
    expect(R("mobile/src/components/ComingSoonPage.tsx")).toMatch(
      /export\s+default\s+function\s+ComingSoonPage/,
    );
  });

  it("mobile/src/components/WebOnlyPage.tsx exists with WebView + Linking fallback", () => {
    expect(E("mobile/src/components/WebOnlyPage.tsx")).toBe(true);
    const src = R("mobile/src/components/WebOnlyPage.tsx");
    expect(src).toMatch(/from ["']react-native-webview["']/);
    expect(src).toMatch(/Platform\.OS\s*===\s*["']web["']/);
    expect(src).toMatch(/Linking\.openURL/);
  });

  it("mobile/app/web-only.tsx re-exports WebOnlyPage for the /web-only route", () => {
    expect(E("mobile/app/web-only.tsx")).toBe(true);
    expect(R("mobile/app/web-only.tsx")).toMatch(
      /from ["']@\/src\/components\/WebOnlyPage["']/,
    );
  });
});

describe("Drawer render (mobile/app/(app)/more.tsx)", () => {
  it("imports ADMIN_NAV + QUICK_ACCESS + canSeeEntry from adminNav.ts", () => {
    expect(MORE).toMatch(
      /import\s+\{\s*ADMIN_NAV[\s\S]*?QUICK_ACCESS[\s\S]*?canSeeEntry[\s\S]*?\}\s+from\s+["']@\/src\/nav\/adminNav["']/,
    );
  });

  it("renders QUICK_ACCESS above the canonical eight groups", () => {
    const qa = MORE.indexOf('group={QUICK_ACCESS}');
    const admin = MORE.indexOf('ADMIN_NAV.map');
    expect(qa).toBeGreaterThan(-1);
    expect(admin).toBeGreaterThan(qa);
  });

  it("declares DrawerGroup and DrawerRow helpers", () => {
    expect(MORE).toMatch(/function\s+DrawerGroup\(/);
    expect(MORE).toMatch(/function\s+DrawerRow\(/);
  });

  it("T3 rows show a 'WEB' pill and route to /web-only", () => {
    expect(MORE).toMatch(/pathname:\s*["']\/web-only["']/);
    expect(MORE).toMatch(/webOnlyPill/);
    expect(MORE).toMatch(/>WEB</);
  });

  it("T2 rows show a 'SOON' pill", () => {
    expect(MORE).toMatch(/comingSoonPill/);
    expect(MORE).toMatch(/>SOON</);
  });

  it("admin section gate still uses showAdminSection (tech/customer drawer untouched)", () => {
    expect(MORE).toMatch(/showAdminSection\s*\?\s*\(/);
    expect(MORE).toMatch(/isTech\s*\?\s*\(/);
    expect(MORE).toMatch(/showAdminSection\s*=\s*isAdmin/);
  });
});

// ── T2 stub route files exist ──────────────────────────────────────
const T2_STUB_ROUTES = [
  "/settings/income-categories",
  "/settings/service-categories",
  "/settings/notifications",
  "/settings/terms",
  "/settings/legal",
  "/settings/maps",
  "/settings/ringcentral",
  "/admin/reviews",
  "/admin/reviews/requests",
  "/admin/reviews/platforms",
  "/admin/reviews/widget",
  "/admin/comms/email",
  "/admin/comms/sms",
  "/admin/comms/templates",
  "/admin/comms/automations",
  "/admin/comms/sends",
  "/admin/tags",
  "/admin/service-reports",
  "/admin/appointments",
  "/admin/referrals/analytics",
  "/admin/referrals/settings",
  "/admin/chemicals",
  "/admin/moderation/checkins",
  "/admin/diagnostics/errors",
  "/weather",
];

describe("T2 stub route files exist and re-export ComingSoonPage", () => {
  for (const r of T2_STUB_ROUTES) {
    it(`mobile/app${r}.tsx exists and re-exports ComingSoonPage`, () => {
      const p = `mobile/app${r}.tsx`;
      expect(E(p)).toBe(true);
      expect(R(p)).toMatch(/from ["']@\/src\/components\/ComingSoonPage["']/);
    });
  }
});
