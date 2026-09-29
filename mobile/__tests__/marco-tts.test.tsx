/**
 * TB-1 · MarcoVoiceButton TTS tests.
 *
 * Asserts:
 * 1. On successful /api/marco/execute with `speak`, Speech.speak is called.
 * 2. If voiceResponseEnabled=false, Speech.speak is NOT called.
 * 3. If a new record starts while TTS is playing, Speech.stop is called.
 */
import React from "react";
import { render, act, waitFor, fireEvent } from "@testing-library/react-native";
import MarcoVoiceButton from "@/src/components/marco/MarcoVoiceButton";

/* ── mocks ─────────────────────────────────────────────────────── */
const mockRecord = jest.fn();
const mockStop = jest.fn();
let mockRecorderUri: string | null = "file:///tmp/test.m4a";

jest.mock("expo-audio", () => ({
  useAudioRecorder: () => ({
    record: mockRecord,
    stop: mockStop,
    get uri() { return mockRecorderUri; },
  }),
  RecordingPresets: { HIGH_QUALITY: {} },
  requestRecordingPermissionsAsync: jest.fn().mockResolvedValue({ granted: true, canAskAgain: true }),
  getRecordingPermissionsAsync: jest.fn().mockResolvedValue({ granted: true, canAskAgain: true, status: "granted" }),
}));

const mockSpeechSpeak = jest.fn();
const mockSpeechStop = jest.fn();
const mockSpeechIsSpeakingAsync = jest.fn().mockResolvedValue(false);

jest.mock("expo-speech", () => ({
  speak: (...args: any[]) => mockSpeechSpeak(...args),
  stop: (...args: any[]) => mockSpeechStop(...args),
  isSpeakingAsync: (...args: any[]) => mockSpeechIsSpeakingAsync(...args),
}));

jest.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => ({ top: 44, bottom: 34, left: 0, right: 0 }),
  SafeAreaProvider: ({ children }: any) => children,
}));

const mockShowToast = jest.fn();
jest.mock("@/src/components/ToastProvider", () => ({
  useToast: () => ({ showToast: mockShowToast }),
}));

jest.mock("@/src/api", () => ({
  getToken: jest.fn().mockResolvedValue("test-token"),
}));

// Default: TTS enabled
let mockVoiceResponseEnabled = true;
jest.mock("@/src/services/marco/voicePreferences", () => ({
  getVoiceResponseEnabled: jest.fn(() => Promise.resolve(mockVoiceResponseEnabled)),
  setVoiceResponseEnabled: jest.fn(),
  getWakeWordEnabled: jest.fn(() => Promise.resolve(false)),
  setWakeWordEnabled: jest.fn(),
}));

/* ── global fetch mock ─────────────────────────────────────────── */
const originalFetch = global.fetch;
let fetchMock: jest.Mock;

beforeEach(() => {
  fetchMock = jest.fn();
  global.fetch = fetchMock;
  jest.clearAllMocks();
  mockRecorderUri = "file:///tmp/test.m4a";
  mockVoiceResponseEnabled = true;
});

afterAll(() => {
  global.fetch = originalFetch;
});

/* ── helpers ───────────────────────────────────────────────────── */
function mockTranscribeAndExecute(
  transcribeResp: { ok: boolean; status?: number; body?: any },
  executeResp?: { ok: boolean; status?: number; body?: any },
) {
  fetchMock.mockImplementationOnce(() =>
    Promise.resolve({
      ok: transcribeResp.ok,
      status: transcribeResp.status || (transcribeResp.ok ? 200 : 500),
      json: () => Promise.resolve(transcribeResp.body || {}),
    }),
  );
  if (executeResp) {
    fetchMock.mockImplementationOnce(() =>
      Promise.resolve({
        ok: executeResp.ok,
        status: executeResp.status || (executeResp.ok ? 200 : 500),
        json: () => Promise.resolve(executeResp.body || {}),
      }),
    );
  }
}

/* ── tests ─────────────────────────────────────────────────────── */
describe("MarcoVoiceButton TTS", () => {
  it("calls Speech.speak when execute returns a speak field and TTS is enabled", async () => {
    mockVoiceResponseEnabled = true;
    mockTranscribeAndExecute(
      { ok: true, body: { transcript: "clock in", language: "en", duration_sec: null, model: "whisper-1" } },
      { ok: true, body: { action: "clock_in", ok: true, message: "Clocked in.", speak: "You are now clocked in.", meta: {} } },
    );

    const { getByTestId } = render(
      <MarcoVoiceButton screen="job_detail" entityId="job-123" />,
    );

    // Start recording
    await act(async () => { fireEvent.press(getByTestId("marco-voice-btn")); });
    // Stop + submit
    await act(async () => { fireEvent.press(getByTestId("marco-voice-btn")); });

    await waitFor(() => {
      expect(mockSpeechSpeak).toHaveBeenCalledWith(
        "You are now clocked in.",
        expect.objectContaining({ language: "en-US" }),
      );
    });
  });

  it("does NOT call Speech.speak when voiceResponseEnabled is false", async () => {
    mockVoiceResponseEnabled = false;
    mockTranscribeAndExecute(
      { ok: true, body: { transcript: "clock out", language: "en", duration_sec: null, model: "whisper-1" } },
      { ok: true, body: { action: "clock_out", ok: true, message: "Clocked out.", speak: "Clocked out.", meta: {} } },
    );

    const { getByTestId } = render(
      <MarcoVoiceButton screen="job_detail" entityId="job-456" />,
    );

    await act(async () => { fireEvent.press(getByTestId("marco-voice-btn")); });
    await act(async () => { fireEvent.press(getByTestId("marco-voice-btn")); });

    await waitFor(() => {
      expect(mockShowToast).toHaveBeenCalled();
    });

    // TTS should NOT have been called
    expect(mockSpeechSpeak).not.toHaveBeenCalled();
  });

  it("calls Speech.stop when a new recording starts while speaking", async () => {
    mockVoiceResponseEnabled = true;
    // First interaction: trigger TTS
    mockTranscribeAndExecute(
      { ok: true, body: { transcript: "clock in", language: "en", duration_sec: null, model: "whisper-1" } },
      { ok: true, body: { action: "clock_in", ok: true, message: "Clocked in.", speak: "Clocked in.", meta: {} } },
    );

    const { getByTestId } = render(
      <MarcoVoiceButton screen="job_detail" entityId="job-789" />,
    );

    // Record + submit → TTS starts
    await act(async () => { fireEvent.press(getByTestId("marco-voice-btn")); });
    await act(async () => { fireEvent.press(getByTestId("marco-voice-btn")); });

    await waitFor(() => {
      expect(mockSpeechSpeak).toHaveBeenCalled();
    });

    // Now tap again to start a new recording while TTS is "playing"
    // (The component should be in "speaking" phase and tapping should cancel TTS)
    mockSpeechStop.mockClear();
    await act(async () => { fireEvent.press(getByTestId("marco-voice-btn")); });

    // Speech.stop should have been called to cancel TTS
    expect(mockSpeechStop).toHaveBeenCalled();
  });
});
