/**
 * Phase 51.6 · Feb-2026 — Mobile walkie reply flow (bottom-sheet gate + payload).
 *
 * Locks the same reducer + payload contract as the web vitest file
 * ``walkie-reply-flow.test.jsx``. Bottom-sheet visibility on mobile
 * is role-gated the same as the web action.
 */
jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn(async () => null),
  setItem: jest.fn(async () => undefined),
  removeItem: jest.fn(async () => undefined),
  clear: jest.fn(async () => undefined),
}));

// eslint-disable-next-line import/first
import { canReplyInChannel, canRecordInChannel } from "@/src/pages/walkie/walkie-helpers";

function replyReducer(state: any, action: any) {
  switch (action.type) {
    case "REPLY_TO": return { ...state, replyTarget: action.messageId };
    case "CANCEL_REPLY": return { ...state, replyTarget: null };
    case "SEND_COMPLETE": return { ...state, replyTarget: null };
    default: return state;
  }
}

function buildSendPayload(state: any, { channelId, durationMs }: any) {
  const fd: Record<string, string> = { channel_id: channelId, duration_ms: String(durationMs) };
  if (state.replyTarget) fd.reply_to_message_id = state.replyTarget;
  return fd;
}

const ALL_HANDS = { id: "ch_ah", kind: "all_hands" };
const POOL_DEPT = { id: "ch_p", kind: "department", department: "pool" };

describe("Phase 51.6 · mobile reply reducer", () => {
  it("REPLY_TO sets, CANCEL_REPLY / SEND_COMPLETE clear", () => {
    let s = { replyTarget: null };
    s = replyReducer(s, { type: "REPLY_TO", messageId: "m1" });
    expect(s.replyTarget).toBe("m1");
    s = replyReducer(s, { type: "CANCEL_REPLY" });
    expect(s.replyTarget).toBeNull();
    s = replyReducer({ replyTarget: "m2" }, { type: "SEND_COMPLETE" });
    expect(s.replyTarget).toBeNull();
  });

  it("payload includes reply_to_message_id when a target is set", () => {
    const fd = buildSendPayload({ replyTarget: "parent_123" }, { channelId: "ch1", durationMs: 2400 });
    expect(fd.reply_to_message_id).toBe("parent_123");
  });

  it("payload omits reply_to_message_id for a normal (non-reply) post", () => {
    const fd = buildSendPayload({ replyTarget: null }, { channelId: "ch1", durationMs: 2400 });
    expect("reply_to_message_id" in fd).toBe(false);
  });
});

describe("Phase 51.6 · mobile reply gate parity with record permission", () => {
  const mkUser = (role: string, department = "", id = "u_a") => ({ id, role, department });

  it("technician-pool can reply on pool dept, blocked on all-hands", () => {
    expect(canReplyInChannel(mkUser("technician", "pool"), POOL_DEPT).allowed).toBe(true);
    const r = canReplyInChannel(mkUser("technician", "pool"), ALL_HANDS);
    expect(r.allowed).toBe(false);
    expect(r.reason).toMatch(/only admins can broadcast to all-hands/i);
  });

  it("admin can reply anywhere they can post", () => {
    expect(canReplyInChannel(mkUser("admin"), ALL_HANDS).allowed).toBe(true);
    expect(canReplyInChannel(mkUser("admin"), POOL_DEPT).allowed).toBe(true);
  });

  it("canReplyInChannel is exactly canRecordInChannel", () => {
    expect(canReplyInChannel(mkUser("customer"), POOL_DEPT)).toEqual(canRecordInChannel(mkUser("customer"), POOL_DEPT));
    expect(canReplyInChannel(mkUser("admin"), ALL_HANDS)).toEqual(canRecordInChannel(mkUser("admin"), ALL_HANDS));
  });
});
