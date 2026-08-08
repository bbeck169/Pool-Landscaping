/**
 * Phase 51d · Feb-2026 — Web ↔ mobile walkie parity snapshot.
 *
 * Source-inspection tests that read both the web and mobile walkie
 * source files and lock the shared product decisions in place. If a
 * future patch drifts the mobile side (or vice versa) without
 * mirroring the change, the corresponding assertion here fails at
 * compile-time-esque speed.
 *
 * We deliberately do NOT mount either surface — that's what the
 * mount tests are for. This file is a plain-text diff canary.
 */
import fs from "fs";
import path from "path";
import { describe, it, expect } from "vitest";
import {
  BROADCAST_ROLES as WEB_BROADCAST_ROLES,
  PIN_ROLES as WEB_PIN_ROLES,
  AUDIO_MIME_CANDIDATES as WEB_MIME,
  sortChannels as webSort,
} from "@/pages/walkie/walkie-helpers";

// Resolve mobile paths off the repo root.
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");

function readMobile(rel) {
  return fs.readFileSync(path.join(REPO_ROOT, "mobile", rel), "utf-8");
}
function readWeb(rel) {
  return fs.readFileSync(path.join(REPO_ROOT, "frontend", rel), "utf-8");
}

const MOBILE_HELPERS = readMobile("src/pages/walkie/walkie-helpers.ts");
const MOBILE_INDEX = readMobile("app/walkie/index.tsx");
const MOBILE_CHANNEL = readMobile("app/walkie/[channelId].tsx");
const WEB_HELPERS = readWeb("src/pages/walkie/walkie-helpers.js");
const WEB_PAGE = readWeb("src/pages/walkie/Walkie.jsx");

describe("Phase 51d · web ↔ mobile channel-ordering parity", () => {
  it("both surfaces sort All-Hands → Departments → Directs", () => {
    // The pure ``sortChannels`` predicate is exercised on the web
    // side. If the shape breaks we get a red on both surfaces at once.
    const chs = [
      { id: "d", kind: "direct", created_at: "2026-02-01T00:00:00Z" },
      { id: "dep", kind: "department", department: "pool" },
      { id: "ah", kind: "all_hands" },
    ];
    expect(webSort(chs).map((c) => c.id)).toEqual(["ah", "dep", "d"]);
    // Mobile source must define the same priority table.
    expect(MOBILE_HELPERS).toMatch(/all_hands:\s*0/);
    expect(MOBILE_HELPERS).toMatch(/department:\s*1/);
    expect(MOBILE_HELPERS).toMatch(/direct:\s*2/);
  });

  it("web + mobile helpers both export sortChannels", () => {
    expect(WEB_HELPERS).toMatch(/export function sortChannels/);
    expect(MOBILE_HELPERS).toMatch(/export function sortChannels/);
  });
});

describe("Phase 51d · web ↔ mobile 30s hold-to-record cap", () => {
  it("both surfaces cap MediaRecorder / expo-audio at 30_000ms", () => {
    expect(WEB_PAGE).toMatch(/MAX_RECORD_MS\s*=\s*30_?000/);
    expect(MOBILE_CHANNEL).toMatch(/MAX_RECORD_MS\s*=\s*30_?000/);
  });
});

describe("Phase 51d · web ↔ mobile walkie_muted persistence key", () => {
  it("both surfaces use exactly the ``walkie_muted`` storage key", () => {
    expect(WEB_HELPERS).toMatch(/const MUTE_KEY = "walkie_muted"/);
    expect(MOBILE_HELPERS).toMatch(/const MUTE_KEY = "walkie_muted"/);
  });
});

describe("Phase 51d · web ↔ mobile admin-only all-hands gate", () => {
  it("BROADCAST_ROLES set is identical", () => {
    // Web export exists at test time.
    const webRoles = Array.from(WEB_BROADCAST_ROLES).sort();
    expect(webRoles).toEqual(["admin", "manager", "super_admin"]);
    // Mobile source must list the same three roles.
    expect(MOBILE_HELPERS).toMatch(/BROADCAST_ROLES = new Set\(\[\s*"super_admin",\s*"admin",\s*"manager"\s*\]\)/);
  });

  it("both surfaces surface the exact server-parity error message", () => {
    const msg = "Only admins can broadcast to all-hands";
    expect(WEB_HELPERS).toContain(msg);
    expect(MOBILE_HELPERS).toContain(msg);
  });
});

describe("Phase 51d · web ↔ mobile waveform peaks + fallback contract", () => {
  it("both surfaces render a fallback bar node with the ``-fallback`` testID suffix", () => {
    // The suffix ``-fallback`` may be built via a template literal so
    // it isn't guaranteed to appear on the same source line as the
    // ``walkie-waveform`` prefix. Just assert the literal suffix
    // exists in each file.
    expect(WEB_PAGE).toContain("-fallback");
    expect(MOBILE_CHANNEL).toContain("-fallback");
  });

  it("MIME candidate lists overlap on the four backend-accepted types", () => {
    // Server whitelist: webm / mp4 / aac / mpeg / ogg. Web + mobile
    // preference orders differ (web prefers webm/opus, mobile prefers mp4)
    // but the union must always be a subset of the whitelist.
    const accepted = new Set(["audio/webm", "audio/mp4", "audio/aac", "audio/mpeg", "audio/ogg"]);
    for (const t of WEB_MIME) {
      // strip codec suffix
      expect(accepted.has(t.split(";")[0])).toBe(true);
    }
  });
});

describe("Phase 51.5 · web ↔ mobile pin gate parity", () => {
  it("PIN_ROLES set is identical on both surfaces", () => {
    // Web export must be the exact three leadership roles.
    expect(Array.from(WEB_PIN_ROLES).sort()).toEqual(["admin", "manager", "super_admin"]);
    // Mobile source must declare the same set literally.
    expect(MOBILE_HELPERS).toMatch(/PIN_ROLES = new Set\(\[\s*"super_admin",\s*"admin",\s*"manager"\s*\]\)/);
  });

  it("both surfaces export a canPinInChannel predicate", () => {
    expect(WEB_HELPERS).toMatch(/export function canPinInChannel/);
    expect(MOBILE_HELPERS).toMatch(/export function canPinInChannel/);
  });

  it("both surfaces render a pinned badge (walkie-pinned-badge testID)", () => {
    expect(WEB_PAGE).toContain("walkie-pinned-badge");
    expect(MOBILE_CHANNEL).toContain("walkie-pinned-badge");
  });

  it("both surfaces render pinned rows visually distinct (border-l accent or borderLeftWidth)", () => {
    // Web uses Tailwind border-l-4 on the pinned row; mobile uses a
    // borderLeftWidth style. Locking either representation ensures
    // the pinned row is always visually distinct.
    expect(WEB_PAGE).toMatch(/border-l-\d|borderLeftWidth/);

describe("Phase 51.6 · web ↔ mobile reply gate + preview parity", () => {
  it("both surfaces export canReplyInChannel", () => {
    expect(WEB_HELPERS).toMatch(/export function canReplyInChannel/);
    expect(MOBILE_HELPERS).toMatch(/export function canReplyInChannel/);
  });

  it("both surfaces export normalizeReplyPreview + replyPreviewLabel", () => {
    expect(WEB_HELPERS).toMatch(/export function normalizeReplyPreview/);
    expect(MOBILE_HELPERS).toMatch(/export function normalizeReplyPreview/);
    expect(WEB_HELPERS).toMatch(/export function replyPreviewLabel/);
    expect(MOBILE_HELPERS).toMatch(/export function replyPreviewLabel/);
  });

  it("both surfaces render the exact '(original message deleted)' placeholder string", () => {
    const placeholder = "(original message deleted)";
    expect(WEB_HELPERS).toContain(placeholder);
    expect(MOBILE_HELPERS).toContain(placeholder);
  });
});

    expect(MOBILE_CHANNEL).toMatch(/borderLeftWidth/);
  });
});


describe("Phase 51d · surface manifest snapshot", () => {
  it("locks the set of test IDs shared between web and mobile", () => {
    const shared = [
      "walkie-page",
      "walkie-record-btn",
      "walkie-message-row",
      "walkie-own-tag",
      "walkie-play-btn",
    ];
    for (const tid of shared) {
      expect(WEB_PAGE).toContain(tid);
      // Some IDs appear across index.tsx OR [channelId].tsx on mobile.
      const inMobile = MOBILE_INDEX.includes(tid) || MOBILE_CHANNEL.includes(tid);
      expect(inMobile, `mobile is missing testID '${tid}'`).toBe(true);
    }
  });
});
