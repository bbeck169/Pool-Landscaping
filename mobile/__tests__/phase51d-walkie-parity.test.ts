/**
 * Phase 51d · Feb-2026 — Mobile ↔ web walkie parity snapshot.
 *
 * Mirror of ``frontend/src/test/phase51d-web-mobile-parity.test.jsx``
 * on the mobile side — reads both trees at test-time and locks the
 * shared product decisions in place so parity can't silently drift.
 * If web changes a shared invariant without mirroring on mobile,
 * this file goes red.
 */
import * as fs from "fs";
import * as path from "path";

// AsyncStorage native module is not available in Jest — mock it
// before importing anything that touches walkie-helpers.
jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn(async () => null),
  setItem: jest.fn(async () => undefined),
  removeItem: jest.fn(async () => undefined),
  clear: jest.fn(async () => undefined),
}));

// eslint-disable-next-line import/first
import {
  BROADCAST_ROLES as MOBILE_BROADCAST_ROLES,
  AUDIO_MIME_CANDIDATES as MOBILE_MIME,
  sortChannels as mobileSort,
} from "@/src/pages/walkie/walkie-helpers";

const REPO_ROOT = path.resolve(__dirname, "..", "..");

function readWeb(rel: string) {
  return fs.readFileSync(path.join(REPO_ROOT, "frontend", rel), "utf-8");
}
function readMobile(rel: string) {
  return fs.readFileSync(path.join(REPO_ROOT, "mobile", rel), "utf-8");
}

const WEB_HELPERS = readWeb("src/pages/walkie/walkie-helpers.js");
const WEB_PAGE = readWeb("src/pages/walkie/Walkie.jsx");
const MOBILE_HELPERS = readMobile("src/pages/walkie/walkie-helpers.ts");
const MOBILE_INDEX = readMobile("app/walkie/index.tsx");
const MOBILE_CHANNEL = readMobile("app/walkie/[channelId].tsx");

describe("Phase 51d · mobile ↔ web channel-ordering parity", () => {
  it("mobile sortChannels agrees with the shared priority table", () => {
    const chs = [
      { id: "d", kind: "direct", created_at: "2026-02-01T00:00:00Z" },
      { id: "dep", kind: "department", department: "pool" },
      { id: "ah", kind: "all_hands" },
    ];
    expect(mobileSort(chs).map((c) => c.id)).toEqual(["ah", "dep", "d"]);
  });

  it("web helpers reference the same three-tier ordering (source snapshot)", () => {
    expect(WEB_HELPERS).toMatch(/all_hands:\s*0/);
    expect(WEB_HELPERS).toMatch(/department:\s*1/);
    expect(WEB_HELPERS).toMatch(/direct:\s*2/);
  });
});

describe("Phase 51d · mobile ↔ web 30s hold-to-record cap", () => {
  it("both surfaces cap at 30_000ms", () => {
    expect(WEB_PAGE).toMatch(/MAX_RECORD_MS\s*=\s*30_?000/);
    expect(MOBILE_CHANNEL).toMatch(/MAX_RECORD_MS\s*=\s*30_?000/);
  });
});

describe("Phase 51d · mobile ↔ web walkie_muted persistence key", () => {
  it("both surfaces use the exact ``walkie_muted`` key", () => {
    expect(WEB_HELPERS).toMatch(/const MUTE_KEY = "walkie_muted"/);
    expect(MOBILE_HELPERS).toMatch(/const MUTE_KEY = "walkie_muted"/);
  });
});

describe("Phase 51d · mobile ↔ web admin-only all-hands gate", () => {
  it("mobile BROADCAST_ROLES is the shared three-role set", () => {
    expect(Array.from(MOBILE_BROADCAST_ROLES).sort()).toEqual(["admin", "manager", "super_admin"]);
  });

  it("web helpers source declares the same three roles", () => {
    expect(WEB_HELPERS).toMatch(/BROADCAST_ROLES = new Set\(\[\s*"super_admin",\s*"admin",\s*"manager"\s*\]\)/);
  });

  it("both surfaces surface the exact server-parity error message", () => {
    const msg = "Only admins can broadcast to all-hands";
    expect(WEB_HELPERS).toContain(msg);
    expect(MOBILE_HELPERS).toContain(msg);
  });
});

describe("Phase 51d · mobile ↔ web waveform + MIME contract", () => {
  it("both surfaces render a fallback bar (``-fallback`` suffix)", () => {
    expect(WEB_PAGE).toContain("-fallback");
    expect(MOBILE_CHANNEL).toContain("-fallback");
  });

  it("mobile MIME candidates are a subset of the backend whitelist", () => {
    const accepted = new Set(["audio/webm", "audio/mp4", "audio/aac", "audio/mpeg", "audio/ogg"]);
    for (const t of MOBILE_MIME) {
      expect(accepted.has(t.split(";")[0])).toBe(true);
    }
  });
});

describe("Phase 51d · mobile ↔ web testID manifest", () => {
  it("the shared testID set is present on both surfaces", () => {
    const shared = [
      "walkie-page",
      "walkie-record-btn",
      "walkie-message-row",
      "walkie-own-tag",
      "walkie-play-btn",
    ];
    for (const tid of shared) {
      expect(WEB_PAGE).toContain(tid);
      const inMobile = MOBILE_INDEX.includes(tid) || MOBILE_CHANNEL.includes(tid);
      expect(inMobile).toBe(true);
    }
  });
});
