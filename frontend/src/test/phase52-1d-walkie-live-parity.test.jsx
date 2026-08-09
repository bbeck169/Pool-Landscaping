/**
 * Phase 52.1d · Feb-2026 — Web ↔ Mobile walkie live parity snapshot.
 *
 * Locks the contract points the two client implementations MUST share:
 *   1. Signaling URL builder pattern — same ws-scheme rewrite, same
 *      /api/ws/walkie/{cid}?token=<jwt> path.
 *   2. localStorage key convention on web + AsyncStorage on mobile
 *      (this test asserts the web side; the mobile side is asserted
 *      by ``phase52-1d-walkie-live-parity.test.ts``).
 *   3. PTT default. VOX active on web (functional). VOX active on
 *      mobile is DEFERRED — web must still expose VOX_THRESHOLD_RMS
 *      + VOX_WINDOW_MS constants.
 *   4. Auto-record trigger points: session-ended message → upload +
 *      unmount → upload. Both surfaces must POST to
 *      /api/walkie/messages with metadata:{source:"live_session"}.
 *   5. Both surfaces MUST consume /api/walkie/ice-servers rather
 *      than hard-coding STUN URLs (so Phase 52.1d TURN wiring flows
 *      through automatically).
 */
import { describe, it, expect, vi } from "vitest";
import fs from "fs";
import path from "path";

vi.mock("@/api", () => ({
  api: { get: vi.fn(), post: vi.fn() },
  api_base: "http://backend.test",
  TOKEN_KEY: "walkie_test_token",
}));

import {
  buildSignalingUrl,
  liveModeKey,
  pttModeKey,
  VOX_THRESHOLD_RMS,
  VOX_WINDOW_MS,
} from "@/pages/walkie/LivePanel";

const WEB_SRC = fs.readFileSync(
  path.resolve(__dirname, "../pages/walkie/LivePanel.jsx"), "utf8",
);
const MOBILE_SRC = fs.readFileSync(
  path.resolve(__dirname, "../../../mobile/src/pages/walkie/LivePanel.tsx"), "utf8",
);

describe("Phase 52.1d · web + mobile walkie live parity", () => {
  it("both surfaces share the same signaling URL pattern", () => {
    expect(buildSignalingUrl("ch1", "TKN"))
      .toBe("ws://backend.test/api/ws/walkie/ch1?token=TKN");
    // The mobile module builds the URL the same way.
    expect(MOBILE_SRC).toMatch(/\/api\/ws\/walkie\/\$\{channelId\}\?token=/);
    expect(MOBILE_SRC).toMatch(/replace\(\/\^http\/i,\s*"ws"\)/);
  });

  it("localStorage key convention matches AsyncStorage key convention", () => {
    expect(liveModeKey("chX")).toBe("walkie_live_mode_chX");
    expect(pttModeKey("chX")).toBe("walkie_ptt_mode_chX");
    expect(MOBILE_SRC).toMatch(/walkie_live_mode_\$\{channelId\}/);
    expect(MOBILE_SRC).toMatch(/walkie_ptt_mode_\$\{channelId\}/);
  });

  it("web exposes functional VOX constants; mobile documents defer", () => {
    expect(VOX_THRESHOLD_RMS).toBeGreaterThan(0);
    expect(VOX_THRESHOLD_RMS).toBeLessThan(0.01);
    expect(VOX_WINDOW_MS).toBe(200);
    // The mobile file must render a DISABLED VOX pill (52.1c decision).
    expect(MOBILE_SRC).toMatch(/walkie-live-mode-vox-disabled/);
    expect(MOBILE_SRC).toMatch(/PTT-only/i);
  });

  it("both surfaces POST /walkie/messages on session-ended with the live_session metadata", () => {
    // Web: /walkie/messages fires with FormData carrying the
    // metadata:{source:"live_session"} envelope on session-ended.
    expect(WEB_SRC).toMatch(/\/walkie\/messages/);
    expect(WEB_SRC).toMatch(/source["']?\s*:\s*["']live_session/);
    // Mobile mirrors the same envelope.
    expect(MOBILE_SRC).toMatch(/\/walkie\/messages/);
    expect(MOBILE_SRC).toMatch(/source["']?\s*:\s*["']live_session/);
  });

  it("both surfaces consume /api/walkie/ice-servers (no hard-coded STUN)", () => {
    expect(WEB_SRC).toMatch(/\/walkie\/ice-servers/);
    expect(MOBILE_SRC).toMatch(/\/walkie\/ice-servers/);
    // Neither should embed the metered.ca TURN URL directly — that
    // MUST come from the backend endpoint via env config.
    expect(WEB_SRC).not.toMatch(/metered\.live/i);
    expect(MOBILE_SRC).not.toMatch(/metered\.live/i);
  });

  it("PTT-default is asserted on both surfaces", () => {
    // Web: localStorage default reads "ptt" (defaults inline).
    expect(WEB_SRC).toMatch(/localStorage\.getItem\(pttModeKey.*\)\s*\|\|\s*["']ptt["']/);
    // Mobile: always writes "ptt" (VOX deferred).
    expect(MOBILE_SRC).toMatch(/AsyncStorage\.setItem\(pttModeKey\(channelId\),\s*["']ptt["']/);
  });

  it("both surfaces broadcast a `speaking` frame on transmit toggle", () => {
    expect(WEB_SRC).toMatch(/type:\s*["']speaking["']/);
    expect(MOBILE_SRC).toMatch(/type:\s*["']speaking["']/);
  });

  it("both surfaces handle the same server→client frame set", () => {
    const wantFrames = [
      "session-state",
      "peer-joined",
      "peer-left",
      "offer",
      "answer",
      "ice-candidate",
      "speaking-update",
      "session-ended",
    ];
    for (const f of wantFrames) {
      expect(WEB_SRC).toMatch(new RegExp(`["']${f}["']`));
      expect(MOBILE_SRC).toMatch(new RegExp(`["']${f}["']`));
    }
  });
});
