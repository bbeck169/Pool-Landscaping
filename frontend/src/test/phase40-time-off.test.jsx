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
  it("mobile UI routes exist for both surfaces (Phase 40b UI)", () => {
    expect(E("mobile/app/time-off.tsx")).toBe(true);
    expect(E("mobile/app/admin/time-off.tsx")).toBe(true);
    // Real UI now — no longer ComingSoonPage re-exports.
    const m = R("mobile/app/time-off.tsx");
    const a = R("mobile/app/admin/time-off.tsx");
    expect(m).not.toMatch(/ComingSoonPage/);
    expect(a).not.toMatch(/ComingSoonPage/);
    // Employee mobile view hits the balance + own-requests endpoints
    expect(m).toMatch(/\/time-off\/balance\/me/);
    expect(m).toMatch(/\/time-off\/requests\?scope=me/);
    expect(m).toMatch(/testID="time-off-page"/);
    // Uses showConfirm (Phase 30.4) — NOT Alert.alert (broken on Android/Expo Go)
    expect(m).toMatch(/showConfirm/);
    expect(m).not.toMatch(/Alert\.alert\(/);
    // Admin mobile view hits pending + balances + policy endpoints
    expect(a).toMatch(/\/time-off\/requests\?scope=all&status=pending/);
    expect(a).toMatch(/\/time-off\/balances\/all/);
    expect(a).toMatch(/\/time-off\/policy/);
    expect(a).toMatch(/testID="admin-time-off-page"/);
    expect(a).not.toMatch(/Alert\.alert\(/);
  });
});

describe("Phase 40b · Web UI pages", () => {
  it("TimeOffPage.jsx exists and calls balance/me + submit + cancel endpoints", () => {
    const p = R("frontend/src/pages/TimeOffPage.jsx");
    expect(p).toMatch(/\/time-off\/balance\/me/);
    expect(p).toMatch(/\/time-off\/requests\?scope=me/);
    expect(p).toMatch(/api\.post\(\s*["'`]\/time-off\/requests["'`]/);
    expect(p).toMatch(/\/time-off\/requests\/\$\{id\}\/cancel/);
    // Error-code UX for the two structured backend errors
    expect(p).toMatch(/waiting_period/);
    expect(p).toMatch(/insufficient_balance/);
    expect(p).toMatch(/data-testid="time-off-page"/);
    expect(p).toMatch(/data-testid="tof-balance-card"/);
    expect(p).toMatch(/data-testid="tof-open-request"/);
    expect(p).toMatch(/data-testid="tof-submit"/);
    expect(p).toMatch(/data-testid="tof-error-banner"/);
  });

  it("AdminTimeOffPage.jsx exists and hits approve/reject + policy PUT + balances", () => {
    const p = R("frontend/src/pages/AdminTimeOffPage.jsx");
    expect(p).toMatch(/\/time-off\/requests\?/);
    expect(p).toMatch(/\/time-off\/balances\/all/);
    expect(p).toMatch(/\/time-off\/requests\/\$\{id\}\/approve/);
    expect(p).toMatch(/\/time-off\/requests\/\$\{reject\.id\}\/reject/);
    expect(p).toMatch(/api\.put\(\s*["'`]\/time-off\/policy["'`]/);
    expect(p).toMatch(/data-testid="admin-time-off-page"/);
    expect(p).toMatch(/data-testid="admin-tof-policy"/);
  });

  it("App.js routes /time-off and /admin/time-off (admin-gated)", () => {
    const app = R("frontend/src/App.js");
    expect(app).toMatch(/const\s+TimeOffPage\s*=\s*React\.lazy\(\s*\(\)\s*=>\s*import\([^)]*["']@\/pages\/TimeOffPage["']/);
    expect(app).toMatch(/const\s+AdminTimeOffPage\s*=\s*React\.lazy\(\s*\(\)\s*=>\s*import\([^)]*["']@\/pages\/AdminTimeOffPage["']/);
    expect(app).toMatch(/path="time-off"\s+element=\{<TimeOffPage/);
    expect(app).toMatch(/path="admin\/time-off"\s+element=\{<AdminOnly><AdminTimeOffPage/);
  });
});

describe("Phase 40b · Backend /balances/all admin endpoint", () => {
  const rt = R("backend/routers/time_off.py");
  it("declares /balances/all under require_admin", () => {
    expect(rt).toMatch(/@router\.get\("\/balances\/all"\)/);
    expect(rt).toMatch(/all_balances[\s\S]{0,150}Depends\(require_admin\)/);
  });
  it("enriches each row with user_name + avatar_url + role", () => {
    expect(rt).toMatch(/bal\["user_name"\]/);
    expect(rt).toMatch(/bal\["avatar_url"\]/);
    expect(rt).toMatch(/bal\["role"\]/);
  });
});

describe("Phase 40b · Seed enhancement (one pending per active tech)", () => {
  const seed = R("backend/scripts/seed_phase40_time_off.py");
  it("iterates over active tech-like users and inserts idempotent pending rows", () => {
    expect(seed).toMatch(/tor_seed_pending_\$\{u\['id'\]\}|tor_seed_pending_/);
    expect(seed).toMatch(/pending-per-tech backfill/);
    expect(seed).toMatch(/find_one\(\{"id":\s*marker\}\)/);
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
