// Phase 36 · Feb-2026 — Mobile CFO Deep-Dives Parity (P1.2)
// source-inspection vitest.
//
// Locks in the five NEW CFO deep-dive surfaces + the CFO hub link-out
// tiles + the drawer-nav flip that promotes them to T1.
//
//   1. CFO · AP Aging        mobile/app/cfo/ap-aging.tsx
//   2. CFO · Cash Forecast   mobile/app/cfo/forecast.tsx
//   3. CFO · Anomalies       mobile/app/cfo/anomalies.tsx
//   4. CFO · Payroll         mobile/app/cfo/payroll.tsx
//   5. CFO · Price Increase  mobile/app/cfo/price-increase.tsx
//
// Bills is delegated to Phase 35's `mobile/app/finance/vendor-bills.tsx`
// via a hub tile — no new file for that surface.

import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const MOBILE = resolve(__dirname, "../../../mobile");
const NAV_PATH = resolve(MOBILE, "src/nav/adminNav.ts");
const HUB_PATH = resolve(MOBILE, "app/(app)/cfo/index.tsx");

const SURFACES = [
  {
    name: "CFO · AP Aging",
    file: "app/cfo/ap-aging.tsx",
    title: "AP Aging",
    endpoints: ['api.get("/cfo/ap-aging")'],
    testId: "cfo-ap-aging-page",
  },
  {
    name: "CFO · Cash Forecast",
    file: "app/cfo/forecast.tsx",
    title: "Cash Forecast",
    endpoints: ["/cfo/forecast?horizon="],
    testId: "cfo-forecast-page",
  },
  {
    name: "CFO · Anomalies",
    file: "app/cfo/anomalies.tsx",
    title: "Anomalies",
    endpoints: ["/cfo/anomalies?window_days="],
    testId: "cfo-anomalies-page",
  },
  {
    name: "CFO · Payroll",
    file: "app/cfo/payroll.tsx",
    title: "Payroll (CFO)",
    endpoints: ["/cfo/payroll?period="],
    testId: "cfo-payroll-page",
  },
  {
    name: "CFO · Price Increase",
    file: "app/cfo/price-increase.tsx",
    title: "Price Increase",
    endpoints: ['api.post("/cfo/price-increase-suggestions"'],
    testId: "cfo-price-increase-page",
  },
];

describe("Phase 36 · Mobile CFO deep-dives — new surfaces", () => {
  for (const s of SURFACES) {
    describe(s.name, () => {
      const p = resolve(MOBILE, s.file);
      const src = existsSync(p) ? readFileSync(p, "utf8") : "";

      it(`file exists at mobile/${s.file}`, () => {
        expect(existsSync(p)).toBe(true);
      });

      it(`mounts <Header> and includes the title text "${s.title}"`, () => {
        expect(src).toMatch(/<Header\b/);
        expect(src).toContain(s.title);
      });

      for (const ep of s.endpoints) {
        it(`hits the backend endpoint (${ep})`, () => {
          expect(src).toContain(ep);
        });
      }

      it(`carries the root testID (${s.testId})`, () => {
        expect(src).toMatch(new RegExp(`testID=["'\`]${s.testId}["'\`]`));
      });

      it("role-gates to strict_admin (RoleGate wrapper)", () => {
        expect(src).toMatch(/<RoleGate\s+level=["']strict_admin["']/);
      });

      it("does NOT use Alert.alert (Phase 30.4 root cause)", () => {
        expect(src).not.toMatch(/Alert\.alert\(/);
      });
    });
  }
});

describe("Phase 36 · CFO hub — link-out tiles", () => {
  const src = existsSync(HUB_PATH) ? readFileSync(HUB_PATH, "utf8") : "";

  it("exposes mobile/app/(app)/cfo/index.tsx", () => {
    expect(existsSync(HUB_PATH)).toBe(true);
  });

  it("renders the deep-dive tile row", () => {
    expect(src).toMatch(/testID=["']cfo-deep-dives["']/);
  });

  const LINKS = [
    { to: "/cfo/ap-aging",       testId: "cfo-link-ap-aging" },
    { to: "/cfo/forecast",       testId: "cfo-link-forecast" },
    { to: "/cfo/anomalies",      testId: "cfo-link-anomalies" },
    { to: "/cfo/payroll",        testId: "cfo-link-payroll" },
    { to: "/cfo/price-increase", testId: "cfo-link-price-increase" },
    { to: "/finance/vendor-bills", testId: "cfo-link-vendor-bills" },
  ];

  for (const l of LINKS) {
    it(`links to ${l.to}`, () => {
      expect(src).toContain(l.to);
      expect(src).toContain(l.testId);
    });
  }

  it("regression: still fetches /cfo/dashboard (pre-existing behavior)", () => {
    expect(src).toMatch(/api\.get\(`?\/cfo\/dashboard/);
  });

  it("no longer displays the 'live on the desktop for now' foot-note text", () => {
    // Old copy read: "Forecast · Anomalies · Auto-Categorize live on the desktop for now."
    expect(src).not.toMatch(/live on the desktop for now/);
  });
});

describe("Phase 36 · Drawer nav — Reports group flip", () => {
  const src = existsSync(NAV_PATH) ? readFileSync(NAV_PATH, "utf8") : "";

  it("adds the five new CFO deep-dive T1 entries", () => {
    for (const testId of [
      "drawer-nav-cfo-ap-aging",
      "drawer-nav-cfo-forecast",
      "drawer-nav-cfo-anomalies",
      "drawer-nav-cfo-payroll",
      "drawer-nav-cfo-price-increase",
    ]) {
      expect(src).toContain(testId);
    }
    for (const route of [
      "/cfo/ap-aging",
      "/cfo/forecast",
      "/cfo/anomalies",
      "/cfo/payroll",
      "/cfo/price-increase",
    ]) {
      expect(src).toContain(route);
    }
  });

  it("removes the duplicate T3 Recurring Jobs / Vendor Bills stubs (Phase 35 already ships them at T1)", () => {
    expect(src).not.toMatch(/drawer-nav-t3-recurring-jobs/);
    expect(src).not.toMatch(/drawer-nav-t3-vendor-bills/);
  });

  it("keeps the pre-existing Reports T1 entries intact", () => {
    // Regression net — Phase 36 must ADD, not clobber.
    expect(src).toContain("drawer-nav-dashboard");
    expect(src).toContain("drawer-nav-reports");
    expect(src).toContain("drawer-nav-forecast");
    expect(src).toContain("drawer-nav-revenue-by-service");
    expect(src).toContain("drawer-nav-access-history");
  });
});
