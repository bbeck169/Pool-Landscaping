// Phase 35 · Feb-2026 — Mobile Finance Ops Parity (P1.1) source-inspection
// vitest.
//
// Locks in the six mobile finance surfaces that Phase 35 shipped to
// match the web:
//
//   1. Recurring Jobs         mobile/app/finance/recurring-jobs.tsx
//   2. Auto-Billing config    mobile/app/auto-billing.tsx        (pre-existing)
//   3. Autobilling Runs       mobile/app/finance/autobilling-runs.tsx
//   4. Master Invoices List   mobile/app/finance/master-invoices/index.tsx
//   4b. Master Invoice Detail mobile/app/finance/master-invoices/[id].tsx
//   5. Payments Ledger        mobile/app/payments.tsx            (pre-existing)
//   6. Vendor Bills           mobile/app/finance/vendor-bills.tsx
//
// Plus drawer nav is flipped from T3 stubs → T1 real routes.

import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const MOBILE = resolve(__dirname, "../../../mobile");
const NAV_PATH = resolve(MOBILE, "src/nav/adminNav.ts");

const SURFACES = [
  {
    name: "Recurring Jobs",
    file: "app/finance/recurring-jobs.tsx",
    title: "Recurring Jobs",
    endpoints: ['api.get("/recurring-jobs")', "/recurring-jobs/${row.id}", "/generate?through="],
    testId: "recurring-jobs-page",
  },
  {
    name: "Auto-Billing config",
    file: "app/auto-billing.tsx",
    title: "Auto",
    endpoints: ["/billing-plans"],
    testId: "",  // pre-existing file, no strict testID guarantee
  },
  {
    name: "Autobilling Runs",
    file: "app/finance/autobilling-runs.tsx",
    title: "Autobilling Runs",
    endpoints: ["/autobilling-runs", "/autobilling/runs/bulk-cancel"],
    testId: "autobilling-runs-page",
  },
  {
    name: "Master Invoices List",
    file: "app/finance/master-invoices/index.tsx",
    title: "Master Invoices",
    endpoints: ['api.get("/invoices/master")'],
    testId: "master-invoices-page",
  },
  {
    name: "Master Invoice Detail",
    file: "app/finance/master-invoices/[id].tsx",
    title: "Master Invoice",
    endpoints: ["/invoices/master/${id}", "/apply-payment"],
    testId: "master-invoice-detail-page",
  },
  {
    name: "Payments",
    file: "app/payments.tsx",
    title: "",  // pre-existing — Header title not checked
    endpoints: ["/payments"],
    testId: "",
  },
  {
    name: "Vendor Bills",
    file: "app/finance/vendor-bills.tsx",
    title: "Vendor Bills",
    endpoints: ['api.get("/cfo/bills")', 'api.post("/cfo/bills"'],
    testId: "vendor-bills-page",
  },
];

describe("Phase 35 · Mobile Finance Ops Parity — surface files", () => {
  for (const s of SURFACES) {
    describe(s.name, () => {
      const p = resolve(MOBILE, s.file);
      const src = existsSync(p) ? readFileSync(p, "utf8") : "";

      it(`file exists at mobile/${s.file}`, () => {
        expect(existsSync(p)).toBe(true);
      });

      if (s.title) {
        it(`renders a Header whose title text contains "${s.title}"`, () => {
          // Forgiving check — Header title may be a JSX expression
          // (e.g. `title={doc?.number || "Master Invoice"}`) or a
          // literal `title="Recurring Jobs"`. Both accepted.
          expect(src).toMatch(/<Header\b/);
          expect(src).toContain(s.title);
        });
      }

      for (const ep of s.endpoints) {
        it(`calls the backend endpoint (${ep})`, () => {
          expect(src).toContain(ep);
        });
      }

      if (s.testId) {
        it(`carries the root testID (${s.testId})`, () => {
          expect(src).toMatch(new RegExp(`testID=["'\`]${s.testId}["'\`]`));
        });
      }
    });
  }
});

describe("Phase 35 · Drawer nav — Finance group tier flip", () => {
  const src = existsSync(NAV_PATH) ? readFileSync(NAV_PATH, "utf8") : "";

  it("exposes mobile/src/nav/adminNav.ts", () => {
    expect(existsSync(NAV_PATH)).toBe(true);
  });

  it("routes Master Invoices to the real mobile page (not the T3 web-only stub)", () => {
    // Old shape used `/invoices/master` route + tier: "t3".
    expect(src).toMatch(/route:\s*"\/finance\/master-invoices"/);
    // T3 web-only entry is gone.
    expect(src).not.toMatch(/drawer-nav-t3-master-invoices/);
  });

  it("routes Autobilling Runs to the real mobile page (not the T3 stub)", () => {
    expect(src).toMatch(/route:\s*"\/finance\/autobilling-runs"/);
    expect(src).not.toMatch(/drawer-nav-t3-autobilling-runs/);
  });

  it("adds Recurring Jobs as a T1 entry", () => {
    expect(src).toMatch(/route:\s*"\/finance\/recurring-jobs"/);
    expect(src).toMatch(/drawer-nav-recurring-jobs/);
  });

  it("adds Vendor Bills as a T1 entry", () => {
    expect(src).toMatch(/route:\s*"\/finance\/vendor-bills"/);
    expect(src).toMatch(/drawer-nav-vendor-bills/);
  });

  it("keeps the pre-existing T1 Finance entries (AI CFO, Invoices, Payments, Auto-billing)", () => {
    // Regression net — Phase 35 should ADD, not replace.
    expect(src).toMatch(/drawer-nav-cfo/);
    expect(src).toMatch(/drawer-nav-invoices/);
    expect(src).toMatch(/drawer-nav-payments/);
    expect(src).toMatch(/drawer-nav-auto-billing/);
  });
});

describe("Phase 35 · Destructive-flow ConfirmModal parity (no Alert.alert)", () => {
  // Phase 30.4 mandated ConfirmModal for destructive/blocking flows.
  // The new finance pages must not regress by reintroducing Alert.alert.
  const filesWithDestructive = [
    "app/finance/recurring-jobs.tsx",
    "app/finance/autobilling-runs.tsx",
    "app/finance/master-invoices/[id].tsx",
  ];

  for (const f of filesWithDestructive) {
    it(`${f} imports showConfirm and does NOT use Alert.alert`, () => {
      const p = resolve(MOBILE, f);
      const src = existsSync(p) ? readFileSync(p, "utf8") : "";
      expect(src).toMatch(/from "@\/src\/components\/ConfirmModal"/);
      expect(src).toMatch(/showConfirm\(/);
      expect(src).not.toMatch(/Alert\.alert\(/);
    });
  }
});
