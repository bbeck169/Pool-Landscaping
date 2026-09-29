/**
 * TB-1 · Wake-word service tests.
 *
 * Asserts:
 * 1. If wakeWordEnabled=false, no wake-word listener is registered.
 * 2. If wakeWordEnabled=true and speech-recognition is available, listener registers.
 * 3. On wake detection, the MARCO record flow fires exactly once.
 * 4. If speech-recognition permission denied, status is "unavailable".
 * 5. If TTS is disabled, wake-word does not start.
 */
import {
  startWakeWord,
  stopWakeWord,
  getWakeWordStatus,
  isWakeWordRunning,
} from "@/src/services/marco/wakeWordService";

/* ── mocks ─────────────────────────────────────────────────────── */

// Mock AsyncStorage
const mockAsyncStore: Record<string, string> = {};
jest.mock("@react-native-async-storage/async-storage", () => ({
  getItem: jest.fn((key: string) => Promise.resolve(mockAsyncStore[key] || null)),
  setItem: jest.fn((key: string, val: string) => {
    mockAsyncStore[key] = val;
    return Promise.resolve();
  }),
  removeItem: jest.fn((key: string) => {
    delete mockAsyncStore[key];
    return Promise.resolve();
  }),
}));

// Track speech recognition calls
const mockSpeechStart = jest.fn();
const mockSpeechStop = jest.fn();
const mockSpeechRequestPerms = jest.fn().mockResolvedValue({ granted: true });
const mockSpeechListeners: Record<string, Function[]> = {};
const mockAddListener = jest.fn((event: string, cb: Function) => {
  if (!mockSpeechListeners[event]) mockSpeechListeners[event] = [];
  mockSpeechListeners[event].push(cb);
});
const mockRemoveAllListeners = jest.fn((event: string) => {
  if (mockSpeechListeners[event]) mockSpeechListeners[event] = [];
});

jest.mock("expo-speech-recognition", () => ({
  start: (...args: any[]) => mockSpeechStart(...args),
  stop: (...args: any[]) => mockSpeechStop(...args),
  requestPermissionsAsync: (...args: any[]) => mockSpeechRequestPerms(...args),
  addListener: (...args: any[]) => mockAddListener(...args),
  removeAllListeners: (...args: any[]) => mockRemoveAllListeners(...args),
}));

/* ── setup / teardown ──────────────────────────────────────────── */
beforeEach(() => {
  jest.clearAllMocks();
  // Clear listener store
  Object.keys(mockSpeechListeners).forEach((k) => {
    mockSpeechListeners[k] = [];
  });
  // Reset module state
  stopWakeWord();
  // Clear AsyncStorage
  Object.keys(mockAsyncStore).forEach((k) => delete mockAsyncStore[k]);
});

/* ── tests ─────────────────────────────────────────────────────── */
describe("WakeWordService", () => {
  it("does NOT register listener if wakeWordEnabled=false", async () => {
    // Default: wakeWordEnabled is off (no key in storage)
    const mockWake = jest.fn();
    const started = await startWakeWord(mockWake);
    expect(started).toBe(false);
    expect(getWakeWordStatus()).toBe("disabled");
    expect(mockSpeechStart).not.toHaveBeenCalled();
  });

  it("registers listener when wakeWordEnabled=true and TTS enabled", async () => {
    // Enable both toggles
    mockAsyncStore["marco.wakeWordEnabled"] = "1";
    mockAsyncStore["marco.voiceResponseEnabled"] = "1";

    const mockWake = jest.fn();
    const started = await startWakeWord(mockWake);
    expect(started).toBe(true);
    expect(getWakeWordStatus()).toBe("listening");
    expect(mockSpeechStart).toHaveBeenCalledWith(
      expect.objectContaining({ lang: "en-US" }),
    );
    expect(isWakeWordRunning()).toBe(true);

    stopWakeWord();
  });

  it("fires wake callback exactly once on 'hey marco' detection", async () => {
    mockAsyncStore["marco.wakeWordEnabled"] = "1";
    mockAsyncStore["marco.voiceResponseEnabled"] = "1";

    const mockWake = jest.fn();
    await startWakeWord(mockWake);

    // Simulate a speech recognition result with "hey marco"
    const resultListeners = mockSpeechListeners["result"] || [];
    expect(resultListeners.length).toBeGreaterThan(0);

    // Fire result event
    resultListeners.forEach((cb) =>
      cb({ results: [{ transcript: "Hey MARCO what time is it" }] }),
    );

    expect(mockWake).toHaveBeenCalledTimes(1);
    expect(getWakeWordStatus()).toBe("detected");

    // A second immediate trigger should be blocked by cooldown
    resultListeners.forEach((cb) =>
      cb({ results: [{ transcript: "Hey MARCO again" }] }),
    );
    expect(mockWake).toHaveBeenCalledTimes(1); // Still 1 — cooldown active

    stopWakeWord();
  });

  it("shows 'unavailable' when speech-recognition permission denied", async () => {
    mockSpeechRequestPerms.mockResolvedValueOnce({ granted: false });

    mockAsyncStore["marco.wakeWordEnabled"] = "1";
    mockAsyncStore["marco.voiceResponseEnabled"] = "1";

    const mockWake = jest.fn();
    const started = await startWakeWord(mockWake);
    expect(started).toBe(false);
    expect(getWakeWordStatus()).toBe("unavailable");
  });

  it("does NOT register listener when TTS is disabled", async () => {
    mockAsyncStore["marco.wakeWordEnabled"] = "1";
    mockAsyncStore["marco.voiceResponseEnabled"] = "0";

    const mockWake = jest.fn();
    const started = await startWakeWord(mockWake);
    expect(started).toBe(false);
    expect(getWakeWordStatus()).toBe("disabled");
    expect(mockSpeechStart).not.toHaveBeenCalled();
  });
});
