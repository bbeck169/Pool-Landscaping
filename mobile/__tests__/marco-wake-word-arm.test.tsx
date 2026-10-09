/**
 * Phase 8M · "Hey Marco" wake-word — arm-on-click (mobile parity with
 * web Phase 8 · 143c1f10f).
 *
 * Covers:
 *   1. hook does NOT start the listener on mount
 *   2. arm() starts the listener (explicit opt-in bypasses prefs gate)
 *   3. disarm() stops the listener
 *   4. toggle() flips armed ⇄ disarmed
 *   5. 10-min idle → auto-disarm + "auto-disarmed" toast
 *   6. wake detection resets the idle timer
 *   7. AppState background / inactive → disarm
 *   8. zero audible feedback on arm / disarm / detect
 *   9. MicToggleButton role gate + speech-primitive gate + armed visuals
 */
import React from "react";
import { AppState } from "react-native";
import { render, fireEvent, act, renderHook } from "@testing-library/react-native";

jest.mock("@expo/vector-icons", () => ({ Ionicons: () => null }));
jest.mock("expo-router", () => ({ useSegments: () => ["(app)", "schedule"] }));

let mockRole = "admin";
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: mockRole } }) }));

const mockShowToast = jest.fn();
jest.mock("@/src/components/ToastProvider", () => ({ useToast: () => ({ showToast: mockShowToast }) }));

jest.mock("@/src/services/marco/voicePreferences", () => ({ getVoiceResponseEnabled: async () => true }));
const mockRecorder = { prepareToRecordAsync: jest.fn(), record: jest.fn(), stop: jest.fn(), uri: null };
jest.mock("expo-audio", () => ({
  useAudioRecorder: () => mockRecorder,
  RecordingPresets: { HIGH_QUALITY: {} },
  setAudioModeAsync: jest.fn(),
  getRecordingPermissionsAsync: jest.fn(async () => ({ granted: true })),
  requestRecordingPermissionsAsync: jest.fn(async () => ({ granted: true })),
  createAudioPlayer: jest.fn(),
  useAudioPlayer: jest.fn(),
}));
const mockSpeak = jest.fn();
jest.mock("expo-speech", () => ({ speak: (...a: any[]) => mockSpeak(...a) }));
jest.mock("@/src/services/marco/executeMarco", () => ({ transcribeAudio: jest.fn(), executeMarco: jest.fn() }));

let mockSupported = true;
let mockOnWake: any = null;
const mockStart = jest.fn(async (cb: any, _opts?: any) => { mockOnWake = cb; return true; });
const mockStop = jest.fn(() => { mockOnWake = null; });
jest.mock("@/src/services/marco/wakeWordService", () => ({
  startWakeWord: (cb: any, opts?: any) => mockStart(cb, opts),
  stopWakeWord: () => mockStop(),
  getWakeWordStatus: () => "listening",
  isWakeWordSupported: () => mockSupported,
}));

const mockEmitOpen = jest.fn();
jest.mock("@/src/events/aiDockEvents", () => ({ aiDockEvents: { emitOpen: () => mockEmitOpen() } }));

import { useMarcoWakeWord } from "@/src/hooks/useMarcoWakeWord";
import {
  MarcoMicProvider,
  MicToggleButton,
  useMarcoMic,
  IDLE_AUTO_DISARM_MS,
} from "@/src/components/marco/MarcoMicController";
import { createAudioPlayer, useAudioPlayer } from "expo-audio";

let appStateCb: ((s: string) => void) | null = null;
beforeEach(() => {
  jest.clearAllMocks();
  mockRole = "admin";
  mockSupported = true;
  mockOnWake = null;
  appStateCb = null;
  jest.spyOn(AppState, "addEventListener").mockImplementation(((_: string, cb: any) => {
    appStateCb = cb;
    return { remove: jest.fn() };
  }) as any);
});
afterEach(() => { jest.useRealTimers(); jest.restoreAllMocks(); });

let ctxRef: any = null;
function Probe() { ctxRef = useMarcoMic(); return null; }
function renderController() {
  return render(<MarcoMicProvider><Probe /><MicToggleButton /></MarcoMicProvider>);
}
async function press(r: any) {
  await act(async () => { fireEvent.press(r.getByTestId("marco-mic-toggle-btn")); });
}

describe("useMarcoWakeWord — arm-on-click", () => {
  it("1. does NOT start the listener on mount", async () => {
    const { result } = renderHook(() => useMarcoWakeWord(jest.fn()));
    await act(async () => {});
    expect(mockStart).not.toHaveBeenCalled();
    expect(result.current.isArmed).toBe(false);
    expect(result.current.listening).toBe(false);
  });

  it("2. arm() starts the listener and bypasses the stored-prefs gate", async () => {
    const { result } = renderHook(() => useMarcoWakeWord(jest.fn()));
    await act(async () => { await result.current.arm(); });
    expect(mockStart).toHaveBeenCalledTimes(1);
    expect(mockStart.mock.calls[0][1]).toEqual({ requirePrefs: false });
    expect(result.current.isArmed).toBe(true);
    expect(result.current.listening).toBe(true);
  });

  it("3. disarm() stops the listener", async () => {
    const { result } = renderHook(() => useMarcoWakeWord(jest.fn()));
    await act(async () => { await result.current.arm(); });
    act(() => { result.current.disarm(); });
    expect(mockStop).toHaveBeenCalled();
    expect(result.current.isArmed).toBe(false);
    expect(result.current.listening).toBe(false);
  });

  it("4. toggle() flips armed ⇄ disarmed", async () => {
    const { result } = renderHook(() => useMarcoWakeWord(jest.fn()));
    await act(async () => { result.current.toggle(); });
    expect(result.current.isArmed).toBe(true);
    await act(async () => { result.current.toggle(); });
    expect(result.current.isArmed).toBe(false);
    expect(mockStart).toHaveBeenCalledTimes(1);
    expect(mockStop).toHaveBeenCalledTimes(1);
  });
});

describe("MarcoMicProvider — idle / background / audio", () => {
  it("5. auto-disarms after 10 min idle and fires the auto-disarm toast", async () => {
    jest.useFakeTimers();
    const r = renderController();
    await press(r);
    expect(ctxRef.isArmed).toBe(true);
    expect(mockShowToast).toHaveBeenCalledWith("Marco wake-word armed", "success");
    await act(async () => { jest.advanceTimersByTime(IDLE_AUTO_DISARM_MS + 10); });
    expect(ctxRef.isArmed).toBe(false);
    expect(mockStop).toHaveBeenCalled();
    expect(mockShowToast).toHaveBeenCalledWith("Marco wake-word auto-disarmed (10 min idle)", "info");
  });

  it("6. a wake detection resets the idle timer", async () => {
    jest.useFakeTimers();
    const r = renderController();
    await press(r);
    await act(async () => { jest.advanceTimersByTime(9 * 60 * 1000); });
    await act(async () => { await mockOnWake(); });
    expect(mockEmitOpen).toHaveBeenCalledTimes(1);
    await act(async () => { jest.advanceTimersByTime(9 * 60 * 1000); });
    expect(ctxRef.isArmed).toBe(true);
    await act(async () => { jest.advanceTimersByTime(60 * 1000 + 10); });
    expect(ctxRef.isArmed).toBe(false);
  });

  it("7. app going to background / inactive disarms the mic", async () => {
    const r = renderController();
    await press(r);
    expect(ctxRef.isArmed).toBe(true);
    await act(async () => { appStateCb!("background"); });
    expect(ctxRef.isArmed).toBe(false);
    expect(mockStop).toHaveBeenCalled();
    expect(mockShowToast).toHaveBeenCalledWith("Marco wake-word disarmed (app in background)", "info");
    await press(r);
    await act(async () => { appStateCb!("inactive"); });
    expect(ctxRef.isArmed).toBe(false);
  });

  it("8. no audible feedback on arm / disarm / detect", async () => {
    const r = renderController();
    await press(r);
    await act(async () => { await mockOnWake(); });
    await press(r);
    expect(mockSpeak).not.toHaveBeenCalled();
    expect(createAudioPlayer).not.toHaveBeenCalled();
    expect(useAudioPlayer).not.toHaveBeenCalled();
    expect(mockRecorder.record).not.toHaveBeenCalled();
    expect(mockShowToast).toHaveBeenCalledWith("Marco wake-word disarmed", "info");
  });
});

describe("MicToggleButton — gating + visuals", () => {
  it("9a. hidden for non-Marco roles (technician)", () => {
    mockRole = "technician";
    const r = renderController();
    expect(r.queryByTestId("marco-mic-toggle-btn")).toBeNull();
    expect(ctxRef.canUseMarco).toBe(false);
  });

  it("9b. hidden when the speech primitive is unavailable", () => {
    mockSupported = false;
    const r = renderController();
    expect(r.queryByTestId("marco-mic-toggle-btn")).toBeNull();
  });

  it.each(["admin", "super_admin", "manager", "owner"])("9c. visible for %s with pulse ring only when armed", async (role) => {
    mockRole = role;
    const r = renderController();
    expect(r.getByTestId("marco-mic-icon-disarmed")).toBeTruthy();
    expect(r.queryByTestId("marco-mic-pulse-ring")).toBeNull();
    await press(r);
    expect(r.getByTestId("marco-mic-icon-armed")).toBeTruthy();
    expect(r.getByTestId("marco-mic-pulse-ring")).toBeTruthy();
    expect(r.getByTestId("marco-mic-toggle-btn").props.accessibilityLabel).toBe("Disarm Marco wake-word");
  });

  it("9d. renders nothing outside a provider (Header safety)", () => {
    const r = render(<MicToggleButton />);
    expect(r.queryByTestId("marco-mic-toggle-btn")).toBeNull();
  });
});
