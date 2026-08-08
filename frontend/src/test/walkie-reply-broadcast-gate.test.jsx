/**
 * Phase 51.6 · Feb 2026 — Walkie reply broadcast-gate parity.
 *
 * Locks the invariant that the Reply action inherits the record
 * permission gate. If you can't record a fresh clip in a channel,
 * you can't reply to a clip there either — the backend enforces
 * the same 403 on POST /messages regardless of whether
 * ``reply_to_message_id`` is set.
 */
import { describe, it, expect } from "vitest";
import { canRecordInChannel, canReplyInChannel } from "@/pages/walkie/walkie-helpers";

const ALL_HANDS = { id: "ch_ah", kind: "all_hands" };
const POOL_DEPT = { id: "ch_p", kind: "department", department: "pool" };
const DIRECT = { id: "ch_d", kind: "direct", member_user_ids: ["u_a", "u_b"] };

const mkUser = (role, department = "", id = "u_a") => ({ id, role, department });

describe("Phase 51.6 · canReplyInChannel parity with canRecordInChannel", () => {
  it("technician-pool CAN reply on pool dept (has record permission)", () => {
    expect(canReplyInChannel(mkUser("technician", "pool"), POOL_DEPT).allowed).toBe(true);
  });

  it("technician-pool CANNOT reply on all-hands (broadcast gate mirrors record)", () => {
    const r = canReplyInChannel(mkUser("technician", "pool"), ALL_HANDS);
    expect(r.allowed).toBe(false);
    expect(r.reason).toMatch(/only admins can broadcast to all-hands/i);
  });

  it("admin CAN reply anywhere (all-hands / dept / direct they're in)", () => {
    expect(canReplyInChannel(mkUser("admin"), ALL_HANDS).allowed).toBe(true);
    expect(canReplyInChannel(mkUser("admin"), POOL_DEPT).allowed).toBe(true);
    expect(canReplyInChannel(mkUser("admin", "", "u_a"), DIRECT).allowed).toBe(true);
  });

  it("customer CANNOT reply anywhere", () => {
    expect(canReplyInChannel(mkUser("customer"), POOL_DEPT).allowed).toBe(false);
  });

  it("canReplyInChannel is exactly canRecordInChannel — same predicate, same reason", () => {
    const cases = [
      [mkUser("admin"), ALL_HANDS],
      [mkUser("technician", "pool"), ALL_HANDS],
      [mkUser("technician", "pool"), POOL_DEPT],
      [mkUser("customer"), POOL_DEPT],
    ];
    for (const [u, c] of cases) {
      expect(canReplyInChannel(u, c)).toEqual(canRecordInChannel(u, c));
    }
  });
});
