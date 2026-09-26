/**
 * MarcoVoiceButton unit tests — MA2+MA3.
 *
 * Mocks expo-audio permissions + recorder, fetch for transcribe/execute.
 */
import React from "react";
import { render, act, waitFor, fireEvent } from "@testing-library/react-native";
import { Alert, Linking } from "react-native";

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

jest.spyOn(Alert, "alert");
jest.spyOn(Linking, "openSettings").mockImplementation(() => Promise.resolve());

/* ── global fetch mock ─────────────────────────────────────────── */
const originalFetch = global.fetch;
let fetchMock: jest.Mock;

beforeEach(() => {
  fetchMock = jest.fn();
  global.fetch = fetchMock;
  jest.clearAllMocks();
  mockRecorderUri = "file:///tmp/test.m4a";
});

afterAll(() => {
  global.fetch = originalFetch;
});

/* ── import ────────────────────────────────────────────────────── */
import MarcoVoiceButton from "@/src/components/marco/MarcoVoiceButton";
const { requestRecordingPermissionsAsync, getRecordingPermissionsAsync } = require("expo-audio");

/* ── helpers ───────────────────────────────────────────────────── */
function mockTranscribeAndExecute(
  transcribeResp: { ok: boolean; status?: number; body?: any },
  executeResp?: { ok: boolean; status?: number; body?: any },
) {
  fetchMock
    .mockImplementationOnce(() =>
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
describe("MarcoVoiceButton", () => {
  it("renders in idle state with correct styling and testID", () => {
    const { getByTestId } = render(
      <MarcoVoiceButton screen="job_detail" entityId="job-123" />,
    );
    expect(getByTestId("marco-voice-btn")).toBeTruthy();
    expect(getByTestId("marco-fab-wrap")).toBeTruthy();
  });

  it("is disabled when entityId is null", () => {
    const { getByTestId } = render(
      <MarcoVoiceButton screen="job_detail" entityId={null} />,
    );
    const btn = getByTestId("marco-voice-btn");
    expect(btn.props.accessibilityState?.disabled || btn.props.disabled).toBeTruthy();
  });

  it("tap → recording state (starts recorder)", async () => {
    const { getByTestId } = render(
      <MarcoVoiceButton screen="job_detail" entityId="job-123" />,
    );

    await act(async () => {
      fireEvent.press(getByTestId("marco-voice-btn"));
    });

    expect(mockRecord).toHaveBeenCalled();
  });

  it("second tap → processing → successful transcribe+execute → success toast", async () => {
    mockTranscribeAndExecute(
      { ok: true, body: { transcript: "clock me in", language: "en", duration_sec: null, model: "whisper-1" } },
      { ok: true, body: { action: "clock_in", ok: true, message: "Clocked in", meta: {} } },
    );

    const { getByTestId } = render(
      <MarcoVoiceButton screen="job_detail" entityId="job-123" />,
    );

    // First tap: start recording
    await act(async () => {
      fireEvent.press(getByTestId("marco-voice-btn"));
    });

    // Second tap: stop + submit
    await act(async () => {
      fireEvent.press(getByTestId("marco-voice-btn"));
    });

    await waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith("MARCO · Clocked in", "success", 3000);
    });
  });

  it("ok: false from execute → red toast with backend message", async () => {
    mockTranscribeAndExecute(
      { ok: true, body: { transcript: "add chlorene tabz", language: "en", duration_sec: null, model: "whisper-1" } },
      { ok: true, body: { action: "add_line_item", ok: false, message: "No pricebook item matches 'chlorene tabz'.", meta: {} } },
    );

    const { getByTestId } = render(
      <MarcoVoiceButton screen="service_report" entityId="sr-456" />,
    );

    await act(async () => { fireEvent.press(getByTestId("marco-voice-btn")); });
    await act(async () => { fireEvent.press(getByTestId("marco-voice-btn")); });

    await waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith(
        "MARCO couldn't do that. No pricebook item matches 'chlorene tabz'.",
        "error",
        5000,
      );
    });
  });

  it("transcribe 413 → red toast 'Audio too long'", async () => {
    mockTranscribeAndExecute(
      { ok: false, status: 413, body: { detail: { code: "AUDIO_TOO_LARGE" } } },
    );

    const { getByTestId } = render(
      <MarcoVoiceButton screen="job_detail" entityId="job-123" />,
    );

    await act(async () => { fireEvent.press(getByTestId("marco-voice-btn")); });
    await act(async () => { fireEvent.press(getByTestId("marco-voice-btn")); });

    await waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith(
        "Audio too long. Keep it under 25 MB.",
        "error",
        5000,
      );
    });
  });

  it("transcribe 502 → red toast upstream error", async () => {
    mockTranscribeAndExecute(
      { ok: false, status: 502, body: { detail: { code: "WHISPER_UPSTREAM_ERROR" } } },
    );

    const { getByTestId } = render(
      <MarcoVoiceButton screen="job_detail" entityId="job-123" />,
    );

    await act(async () => { fireEvent.press(getByTestId("marco-voice-btn")); });
    await act(async () => { fireEvent.press(getByTestId("marco-voice-btn")); });

    await waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith(
        "MARCO couldn't hear that. Try again.",
        "error",
        5000,
      );
    });
  });

  it("execute 502 → red toast connection issue", async () => {
    mockTranscribeAndExecute(
      { ok: true, body: { transcript: "clock out", language: "en", duration_sec: null, model: "whisper-1" } },
      { ok: false, status: 502 },
    );

    const { getByTestId } = render(
      <MarcoVoiceButton screen="job_detail" entityId="job-123" />,
    );

    await act(async () => { fireEvent.press(getByTestId("marco-voice-btn")); });
    await act(async () => { fireEvent.press(getByTestId("marco-voice-btn")); });

    await waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith(
        "MARCO connection issue. Try again.",
        "error",
        5000,
      );
    });
  });

  it("no audio URI → error toast about empty recording", async () => {
    mockRecorderUri = null;

    const { getByTestId } = render(
      <MarcoVoiceButton screen="job_detail" entityId="job-123" />,
    );

    await act(async () => { fireEvent.press(getByTestId("marco-voice-btn")); });
    await act(async () => { fireEvent.press(getByTestId("marco-voice-btn")); });

    await waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith(
        "No audio recorded. Tap and speak, then tap again.",
        "error",
        5000,
      );
    });
  });

  it("mic permission denied with canAskAgain=false → Alert with Open Settings", async () => {
    getRecordingPermissionsAsync.mockResolvedValueOnce({ granted: false, canAskAgain: true, status: "denied" });
    requestRecordingPermissionsAsync.mockResolvedValueOnce({ granted: false, canAskAgain: false, status: "denied" });

    const { getByTestId } = render(
      <MarcoVoiceButton screen="job_detail" entityId="job-123" />,
    );

    await act(async () => { fireEvent.press(getByTestId("marco-voice-btn")); });

    await waitFor(() => {
      expect(Alert.alert).toHaveBeenCalledWith(
        "Microphone access required",
        expect.stringContaining("Settings"),
        expect.arrayContaining([
          expect.objectContaining({ text: "Open Settings" }),
        ]),
      );
    });
  });
});
