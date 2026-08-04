/**
 * Phase 49 · Feb 2026 — Lana voice + confirm modal + todo panel guards.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect } from "vitest";

const LANA = resolve(__dirname, "../../../mobile/app/os/lana.tsx");
const _src = readFileSync(LANA, "utf8");

describe("Phase 49 · mobile Lana surface", () => {
  it("dynamic-imports expo-speech-recognition (dev-client-only, Expo Go safe)", () => {
    expect(_src).toMatch(/require\(["']expo-speech-recognition["']\)/);
    expect(_src).toMatch(/try\s*\{[\s\S]*?_speech\s*=\s*require/);
    // Regression guard: must NOT top-level import speech-recognition
    // (that would crash Expo Go on module load).
    expect(_src).not.toMatch(/^\s*import[^;]*expo-speech-recognition/m);
  });

  it("renders a mic button with the phase49 testID", () => {
    expect(_src).toContain('testID="os-lana-mic"');
    // Toggles between mic-outline and stop-circle-outline.
    expect(_src).toContain('"mic-outline"');
    expect(_src).toContain('"stop-circle-outline"');
  });

  it("renders the schedule-confirmation card when a preview is pending", () => {
    expect(_src).toContain('testID="os-lana-schedule-confirm"');
    expect(_src).toContain('testID="os-lana-schedule-confirm-yes"');
    expect(_src).toContain('testID="os-lana-schedule-confirm-no"');
    expect(_src).toContain("/business-os/lana/schedule/commit");
  });

  it("renders a todo list panel bound to /lana/todos", () => {
    expect(_src).toContain('testID="os-lana-todos"');
    expect(_src).toContain('api.get("/lana/todos")');
    expect(_src).toContain("api.patch(`/lana/todos/${t.id}`");
  });

  it("gracefully falls back when speech-recognition is unavailable", () => {
    // Alert.alert("Voice unavailable", …) is the Expo-Go fallback path.
    expect(_src).toContain('"Voice unavailable"');
    expect(_src).toContain("dev-client build");
  });
});
