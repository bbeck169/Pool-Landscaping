/**
 * Phase 51c · Feb-2026 — Walkie-Talkie mobile pure-logic tests.
 *
 * Mirrors the four web vitest files at
 * ``frontend/src/test/walkie-*.test.jsx``. The record-button gate,
 * unread badge maths, own-message detection, and mute persistence
 * behaviour MUST match the web surface — every regression in
 * either direction trips here.
 */
import {
  BROADCAST_ROLES,
  canRecordInChannel,
  extForMime,
  isMuted,
  isOwnMessage,
  setMuted,
  shouldAutoPlay,
  sortChannels,
  totalUnread,
  AUDIO_MIME_CANDIDATES,
} from "@/src/pages/walkie/walkie-helpers";

// In-memory AsyncStorage mock (parity with GpsTracker.test.ts).
const _store: Record<string, string> = {};
jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn((key: string) => Promise.resolve(_store[key] ?? null)),
  setItem: jest.fn((key: string, val: string) => { _store[key] = val; return Promise.resolve(); }),
  removeItem: jest.fn((key: string) => { delete _store[key]; return Promise.resolve(); }),
  clear: jest.fn(() => { Object.keys(_store).forEach(k => delete _store[k]); return Promise.resolve(); }),
}));

const ALL_HANDS = { id: "ch_ah", kind: "all_hands" };
const POOL_DEPT = { id: "ch_p", kind: "department", department: "pool" };
const LAND_DEPT = { id: "ch_l", kind: "department", department: "landscape" };
const DIRECT = { id: "ch_d", kind: "direct", member_user_ids: ["u_a", "u_b"] };

const mkUser = (role: string, department = "", id = "u_a") => ({ id, role, department });

describe("Phase 51c · walkie broadcast gate (parity with web + server)", () => {
  it("blocks technician-pool from all-hands with the exact server message", () => {
    const r = canRecordInChannel(mkUser("technician", "pool"), ALL_HANDS);
    expect(r.allowed).toBe(false);
    expect(r.reason).toMatch(/only admins can broadcast to all-hands/i);
  });

  it("blocks technician-landscape (landscaping alias too)", () => {
    expect(canRecordInChannel(mkUser("technician", "landscape"), ALL_HANDS).allowed).toBe(false);
    expect(canRecordInChannel(mkUser("technician", "landscaping"), ALL_HANDS).allowed).toBe(false);
  });

  it("blocks dispatcher (staff, but not broadcast leadership)", () => {
    expect(canRecordInChannel(mkUser("dispatcher"), ALL_HANDS).allowed).toBe(false);
  });

  it("blocks customer up-front (not_staff)", () => {
    const r = canRecordInChannel(mkUser("customer"), ALL_HANDS);
    expect(r.allowed).toBe(false);
    expect(r.reason).toBe("not_staff");
  });

  it("allows admin / super_admin / manager", () => {
    for (const role of Array.from(BROADCAST_ROLES)) {
      expect(canRecordInChannel(mkUser(role), ALL_HANDS)).toEqual({ allowed: true });
    }
  });

  it("pool tech CAN post to pool dept + direct they're a member of", () => {
    expect(canRecordInChannel(mkUser("technician", "pool"), POOL_DEPT)).toEqual({ allowed: true });
    expect(canRecordInChannel(mkUser("technician", "pool", "u_a"), DIRECT)).toEqual({ allowed: true });
  });

  it("pool tech BLOCKED from landscape dept + directs they're not in", () => {
    expect(canRecordInChannel(mkUser("technician", "pool"), LAND_DEPT).allowed).toBe(false);
    expect(canRecordInChannel(mkUser("technician", "pool", "u_z"), DIRECT).allowed).toBe(false);
  });
});

describe("Phase 51c · walkie unread badge + sort", () => {
  it("totalUnread sums correctly + coerces strings + treats missing as 0", () => {
    expect(totalUnread([])).toBe(0);
    expect(totalUnread(null as any)).toBe(0);
    expect(totalUnread([{ unread_count: 3 }, { unread_count: "2" }, {}] as any)).toBe(5);
  });

  it("sortChannels puts all_hands → dept (alpha) → direct (newest first)", () => {
    const chs = [
      { id: "d2", kind: "direct", created_at: "2026-02-05T10:00:00Z" },
      { id: "dep_pool", kind: "department", department: "pool" },
      { id: "d1", kind: "direct", created_at: "2026-02-06T10:00:00Z" },
      { id: "ah", kind: "all_hands" },
      { id: "dep_land", kind: "department", department: "landscape" },
    ];
    expect(sortChannels(chs as any).map((c) => c.id)).toEqual([
      "ah", "dep_land", "dep_pool", "d1", "d2",
    ]);
  });
});

describe("Phase 51c · walkie own-message detection", () => {
  const me = { id: "u_1" };

  it("true when sender matches", () => {
    expect(isOwnMessage(me, { sender_user_id: "u_1" })).toBe(true);
  });

  it("false when sender differs / user missing / message missing", () => {
    expect(isOwnMessage(me, { sender_user_id: "u_2" })).toBe(false);
    expect(isOwnMessage(null, { sender_user_id: "u_1" })).toBe(false);
    expect(isOwnMessage(me, {})).toBe(false);
  });
});

describe("Phase 51c · walkie mute persistence · AsyncStorage", () => {
  beforeEach(async () => {
    const AsyncStorage = require("@react-native-async-storage/async-storage");
    await AsyncStorage.clear();
  });

  it("defaults to unmuted", async () => {
    await expect(isMuted()).resolves.toBe(false);
  });

  it("setMuted(true) writes '1'", async () => {
    await setMuted(true);
    await expect(isMuted()).resolves.toBe(true);
  });

  it("setMuted(false) removes the key entirely (no lingering '0')", async () => {
    const AsyncStorage = require("@react-native-async-storage/async-storage");
    await setMuted(true);
    await setMuted(false);
    await expect(AsyncStorage.getItem("walkie_muted")).resolves.toBeNull();
    await expect(isMuted()).resolves.toBe(false);
  });
});

describe("Phase 51c · walkie shouldAutoPlay gate", () => {
  const me = { id: "u_1" };
  const other = { id: "u_2" };
  const msg = (uid: string) => ({ id: "m", sender_user_id: uid });

  it("plays incoming teammate clips when unmuted", () => {
    expect(shouldAutoPlay({ user: me, message: msg(other.id), muted: false })).toBe(true);
  });
  it("suppresses when muted", () => {
    expect(shouldAutoPlay({ user: me, message: msg(other.id), muted: true })).toBe(false);
  });
  it("suppresses own outgoing clips even if unmuted", () => {
    expect(shouldAutoPlay({ user: me, message: msg(me.id), muted: false })).toBe(false);
  });
});

describe("Phase 51c · walkie MIME + extension mapping (expo-audio outputs)", () => {
  it("candidate list starts with mp4 (iOS + modern Android default)", () => {
    expect(AUDIO_MIME_CANDIDATES[0]).toBe("audio/mp4");
  });

  it("extForMime maps expo-audio outputs to sane file extensions", () => {
    expect(extForMime("audio/mp4")).toBe("m4a");
    expect(extForMime("audio/aac")).toBe("aac");
    expect(extForMime("audio/webm")).toBe("webm");
    expect(extForMime("audio/mpeg")).toBe("mp3");
    expect(extForMime("audio/ogg")).toBe("ogg");
    expect(extForMime("application/octet-stream")).toBe("m4a"); // safe default
  });
});
