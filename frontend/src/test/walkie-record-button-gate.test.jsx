/**
 * Phase 51b · Walkie-Talkie record-button gate.
 *
 * Server-side ``routers/walkie.py`` returns 403 when a non-admin posts
 * to the all-hands channel. The UI must mirror that gate up-front:
 * greying out the record button and surfacing the "Only admins can
 * broadcast to all-hands" tooltip instead of failing at send-time.
 *
 * The gate lives in ``pages/walkie/walkie-helpers.js#canRecordInChannel``.
 * This test locks the contract in place — regressions in either
 * direction (tech gaining broadcast, admin losing it) trip here.
 */
import { describe, it, expect } from "vitest";
import { canRecordInChannel } from "@/pages/walkie/walkie-helpers";

const ALL_HANDS = { id: "ch_ah", kind: "all_hands" };
const POOL_DEPT = { id: "ch_p", kind: "department", department: "pool" };
const LAND_DEPT = { id: "ch_l", kind: "department", department: "landscape" };
const DIRECT = { id: "ch_d", kind: "direct", member_user_ids: ["u_a", "u_b"] };

const mkUser = (role, department = "", id = "u_a") => ({ id, role, department });

describe("canRecordInChannel — all-hands broadcast gate", () => {
  it("blocks technician-pool with the exact server error message", () => {
    const r = canRecordInChannel(mkUser("technician", "pool"), ALL_HANDS);
    expect(r.allowed).toBe(false);
    expect(r.reason).toMatch(/only admins can broadcast to all-hands/i);
  });

  it("blocks technician-landscape", () => {
    const r = canRecordInChannel(mkUser("technician", "landscaping"), ALL_HANDS);
    expect(r.allowed).toBe(false);
  });

  it("blocks dispatcher (still staff, not leadership)", () => {
    const r = canRecordInChannel(mkUser("dispatcher"), ALL_HANDS);
    expect(r.allowed).toBe(false);
  });

  it("blocks customer up-front (no walkie access at all)", () => {
    const r = canRecordInChannel(mkUser("customer"), ALL_HANDS);
    expect(r.allowed).toBe(false);
    expect(r.reason).toBe("not_staff");
  });

  it("allows admin, super_admin, manager", () => {
    for (const role of ["admin", "super_admin", "manager"]) {
      expect(canRecordInChannel(mkUser(role), ALL_HANDS)).toEqual({ allowed: true });
    }
  });
});

describe("canRecordInChannel — department + direct passthrough", () => {
  it("pool tech CAN post to their own pool department", () => {
    expect(canRecordInChannel(mkUser("technician", "pool"), POOL_DEPT)).toEqual({ allowed: true });
  });

  it("landscape tech CAN post to landscape department (landscaping alias)", () => {
    expect(canRecordInChannel(mkUser("technician", "landscaping"), LAND_DEPT)).toEqual({ allowed: true });
  });

  it("pool tech BLOCKED from landscape dept (server also enforces)", () => {
    const r = canRecordInChannel(mkUser("technician", "pool"), LAND_DEPT);
    expect(r.allowed).toBe(false);
  });

  it("admin can post to any department", () => {
    expect(canRecordInChannel(mkUser("admin"), POOL_DEPT)).toEqual({ allowed: true });
    expect(canRecordInChannel(mkUser("admin"), LAND_DEPT)).toEqual({ allowed: true });
  });

  it("direct: allowed only when caller is in member_user_ids", () => {
    expect(canRecordInChannel(mkUser("technician", "pool", "u_a"), DIRECT)).toEqual({ allowed: true });
    expect(canRecordInChannel(mkUser("technician", "pool", "u_z"), DIRECT).allowed).toBe(false);
  });
});
