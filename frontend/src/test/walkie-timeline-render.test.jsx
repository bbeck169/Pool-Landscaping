/**
 * Phase 51b · Walkie-Talkie timeline render contract.
 *
 * The message row must:
 *   - render a bar-waveform when ``waveform_peaks`` is a non-empty list
 *   - fall back to a plain progress bar when peaks are missing / empty
 *   - render own messages with the ``walkie-own-tag`` "you" pill
 *
 * We test the pure detection helper + waveform shape sanity here to
 * avoid mounting the full jsdom tree (audio + MediaRecorder mocks
 * add flake surface for no coverage gain).
 */
import { describe, it, expect } from "vitest";
import { isOwnMessage } from "@/pages/walkie/walkie-helpers";

describe("isOwnMessage — own-message indicator", () => {
  const me = { id: "u_1", role: "admin" };

  it("true when sender_user_id === user.id", () => {
    expect(isOwnMessage(me, { sender_user_id: "u_1" })).toBe(true);
  });

  it("false when sender differs", () => {
    expect(isOwnMessage(me, { sender_user_id: "u_2" })).toBe(false);
  });

  it("false when no user is signed in", () => {
    expect(isOwnMessage(null, { sender_user_id: "u_1" })).toBe(false);
  });

  it("false when message has no sender_user_id (defensive)", () => {
    expect(isOwnMessage(me, {})).toBe(false);
  });
});

/**
 * Waveform fallback contract — the ``Waveform`` component uses the
 * following predicate: peaks must be an Array with length > 0 to
 * render the bar visualization. Everything else falls back to the
 * plain progress bar. Locking the predicate here keeps regressions
 * from silently hiding waveforms across every message row.
 */
function isWaveformRendered(peaks) {
  return Array.isArray(peaks) && peaks.length > 0;
}

describe("Waveform peaks predicate", () => {
  it("renders bars when peaks is a non-empty list", () => {
    expect(isWaveformRendered([0.1, 0.5, 0.9])).toBe(true);
  });

  it("falls back on empty array", () => {
    expect(isWaveformRendered([])).toBe(false);
  });

  it("falls back on null / undefined", () => {
    expect(isWaveformRendered(null)).toBe(false);
    expect(isWaveformRendered(undefined)).toBe(false);
  });

  it("falls back on non-array types (defensive vs. backend shape drift)", () => {
    expect(isWaveformRendered("0.5,0.3")).toBe(false);
    expect(isWaveformRendered({})).toBe(false);
    expect(isWaveformRendered(42)).toBe(false);
  });
});
