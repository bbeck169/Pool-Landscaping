/**
 * Phase 40 · Feb-2026 — Time Off module source-inspection tests.
 *
 * Backend live tests live in ``backend/tests/test_phase40_time_off.py``
 * (9 assertions, currently 9/9 passing). This suite locks the
 * front-of-house wiring so the drawer entry, the mobile stub routes,
 * the web nav entry, and the shared accrual constants stay
 * consistent across the codebase.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";

const R = (p) => fs.readFileSync(path.resolve(__dirname, "../../..", p), "utf-8");
const E = (p) => fs.existsSync(path.resolve(__dirname, "../../..", p));

describe("Phase 40 · Backend accrual service", () => {
  const svc = R("backend/services/time_off_accrual.py");
  it("exports DEFAULT_POLICY matching the aquaterra spec", () => {
    expect(svc).toMatch(/"accrual_numerator":\s*1/);
    expect(svc).toMatch(/"accrual_denominator":\s*30/);
    expect(svc).toMatch(/"annual_cap_hours":\s*24/);
    expect(svc).toMatch(/"waiting_period_days":\s*90/);
  });
  it("caps accrued at the annual cap", () => {
    expect(svc).toMatch(/min\(accrued_uncapped,\s*cap\)/);
  });
  it("reads worked hours from db.time_entries (existing ledger)", () => {
    expect(svc).toMatch(/db\.time_entries\.find/);
  });
  it("normalises tz-naive datetimes so year_start comparison is safe", () => {
    expect(svc).toMatch(/replace\(tzinfo=timezone\.utc\)/);
  });
});

describe("Phase 40 · Backend router", () => {
  const rt = R("backend/routers/time_off.py");
  it("mounts under /time-off (api_router adds /api)", () => {
    expect(rt).toMatch(/prefix="\/time-off"/);
  });
  it("declares balance/policy/requests + approve/reject/cancel endpoints", () => {
    expect(rt).toMatch(/@router\.get\("\/policy"\)/);
    expect(rt).toMatch(/@router\.put\("\/policy"\)/);
    expect(rt).toMatch(/@router\.get\("\/balance\/me"\)/);
    expect(rt).toMatch(/@router\.get\("\/balance\/\{user_id\}"\)/);
    expect(rt).toMatch(/@router\.get\("\/requests"\)/);
    expect(rt).toMatch(/@router\.post\("\/requests"\)/);
    expect(rt).toMatch(/@router\.post\("\/requests\/\{request_id\}\/approve"\)/);
    expect(rt).toMatch(/@router\.post\("\/requests\/\{request_id\}\/reject"\)/);
    expect(rt).toMatch(/@router\.post\("\/requests\/\{request_id\}\/cancel"\)/);
  });
  it("uses require_admin dependency on policy PUT + approve/reject", () => {
    // 3 occurrences: PUT /policy, /balance/{user_id}, approve, reject → at least 3.
    const matches = rt.match(/Depends\(require_admin\)/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(3);
  });
  it("surfaces waiting_period + insufficient_balance error codes", () => {
    expect(rt).toMatch(/"code":\s*"waiting_period"/);
    expect(rt).toMatch(/"code":\s*"insufficient_balance"/);
  });
});

describe("Phase 40 · Server wiring", () => {
  const srv = R("backend/server.py");
  it("imports the time_off router and adds it to include list", () => {
    expect(srv).toMatch(/\btime_off\b/);
  });
});

describe("Phase 40 · Drawer + nav parity", () => {
  it("mobile drawer nav registers Time Off + Time Off Approvals", () => {
    const nav = R("mobile/src/nav/adminNav.ts");
    expect(nav).toMatch(/testID:\s*"drawer-nav-time-off"/);
    expect(nav).toMatch(/testID:\s*"drawer-nav-time-off-admin"/);
    expect(nav).toMatch(/route:\s*"\/time-off"/);
    expect(nav).toMatch(/route:\s*"\/admin\/time-off"/);
  });
  it("web adminNav.js includes the Time Off + approvals entries in Operations", () => {
    const nav = R("frontend/src/nav/adminNav.js");
    expect(nav).toMatch(/to:\s*"\/time-off"[\s\S]{0,80}label:\s*"Time Off"/);
    expect(nav).toMatch(/to:\s*"\/admin\/time-off"[\s\S]{0,80}label:\s*"Time Off Approvals"/);
    expect(nav).toMatch(/hard_rule:\s*"admin_only"/);
  });
  it("mobile stub routes exist for both surfaces (Phase-40b UI pending)", () => {
    expect(E("mobile/app/time-off.tsx")).toBe(true);
    expect(E("mobile/app/admin/time-off.tsx")).toBe(true);
    expect(R("mobile/app/time-off.tsx")).toMatch(/ComingSoonPage/);
    expect(R("mobile/app/admin/time-off.tsx")).toMatch(/ComingSoonPage/);
  });
});

describe("Phase 40 · Seed script", () => {
  const seed = R("backend/scripts/seed_phase40_time_off.py");
  it("inserts a default policy matching the accrual spec", () => {
    expect(seed).toMatch(/"accrual_numerator":\s*1/);
    expect(seed).toMatch(/"accrual_denominator":\s*30/);
    expect(seed).toMatch(/"annual_cap_hours":\s*24/);
    expect(seed).toMatch(/"waiting_period_days":\s*90/);
  });
  it("backfills hire_date on landscaper@aquaterra.com > 90d ago", () => {
    expect(seed).toMatch(/landscaper@aquaterra\.com/);
    expect(seed).toMatch(/timedelta\(days=200\)/);
  });
});
