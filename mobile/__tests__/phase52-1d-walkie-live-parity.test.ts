/**
 * Phase 52.1d · Feb-2026 — Mobile ↔ web walkie live parity snapshot.
 *
 * Mirror of ``frontend/src/test/phase52-1d-walkie-live-parity.test.jsx``.
 * Assertions live at the source level so this test can't be broken
 * by future component reshuffles that keep behavior identical.
 */
import fs from "fs";
import path from "path";

// AsyncStorage jest polyfill so LivePanel import doesn't blow up.
jest.mock("@react-native-async-storage/async-storage", () =>
  require("@react-native-async-storage/async-storage/jest/async-storage-mock"),
);
// Stub @/src/api so buildSignalingUrl can round-trip a known origin.
jest.mock("@/src/api", () => ({
  api: { get: jest.fn(), post: jest.fn() },
  api_base: () => "http://backend.test",
  getAuthToken: async () => "TKN",
}));
jest.mock("expo-audio", () => ({
  RecordingPresets: { HIGH_QUALITY: {} },
  requestRecordingPermissionsAsync: async () => ({ granted: true }),
  useAudioRecorder: () => ({
    prepareToRecordAsync: async () => {}, record: () => {}, stop: async () => {}, uri: "",
  }),
}));

import {
  buildSignalingUrl,
  liveModeKey,
  pttModeKey,
} from "@/src/pages/walkie/LivePanel";

const MOBILE_SRC = fs.readFileSync(
  path.resolve(__dirname, "../src/pages/walkie/LivePanel.tsx"), "utf8",
);
const WEB_SRC = fs.readFileSync(
  path.resolve(__dirname, "../../frontend/src/pages/walkie/LivePanel.jsx"), "utf8",
);

describe("Phase 52.1d · mobile + web walkie live parity", () => {
  it("shared signaling URL contract", () => {
    const u = buildSignalingUrl("chZ", "T K");
    expect(u).toBe("ws://backend.test/api/ws/walkie/chZ?token=T%20K");
  });

  it("localStorage / AsyncStorage key convention aligned", () => {
    expect(liveModeKey("chY")).toBe("walkie_live_mode_chY");
    expect(pttModeKey("chY")).toBe("walkie_ptt_mode_chY");
    expect(WEB_SRC).toMatch(/walkie_live_mode_/);
    expect(WEB_SRC).toMatch(/walkie_ptt_mode_/);
  });

  it("mobile 52.1c ships PTT-only — VOX pill disabled", () => {
    expect(MOBILE_SRC).toMatch(/walkie-live-mode-vox-disabled/);
    expect(MOBILE_SRC).toMatch(/PTT-only/i);
  });

  it("both surfaces target /walkie/messages with live_session metadata", () => {
    expect(MOBILE_SRC).toMatch(/\/walkie\/messages/);
    expect(MOBILE_SRC).toMatch(/source["']?\s*:\s*["']live_session/);
    expect(WEB_SRC).toMatch(/source["']?\s*:\s*["']live_session/);
  });

  it("both surfaces consume /api/walkie/ice-servers (TURN flows via backend env)", () => {
    expect(MOBILE_SRC).toMatch(/\/walkie\/ice-servers/);
    expect(WEB_SRC).toMatch(/\/walkie\/ice-servers/);
    expect(MOBILE_SRC).not.toMatch(/metered\.live/i);
    expect(WEB_SRC).not.toMatch(/metered\.live/i);
  });

  it("both surfaces broadcast a `speaking` frame on transmit toggle", () => {
    expect(MOBILE_SRC).toMatch(/type:\s*["']speaking["']/);
    expect(WEB_SRC).toMatch(/type:\s*["']speaking["']/);
  });

  it("mobile handles the full server→client frame set from Phase 52.1a", () => {
    const frames = [
      "session-state", "peer-joined", "peer-left",
      "offer", "answer", "ice-candidate",
      "speaking-update", "session-ended",
    ];
    for (const f of frames) {
      expect(MOBILE_SRC).toMatch(new RegExp(`["']${f}["']`));
    }
  });

  it("mobile installs react-native-webrtc (dev-client only)", () => {
    const pkg = JSON.parse(fs.readFileSync(
      path.resolve(__dirname, "../package.json"), "utf8"));
    expect(pkg.dependencies["react-native-webrtc"]).toBeDefined();
    expect(pkg.dependencies["@config-plugins/react-native-webrtc"]).toBeDefined();
  });
});
