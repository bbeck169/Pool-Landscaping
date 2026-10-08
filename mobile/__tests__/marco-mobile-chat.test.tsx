/**
 * MARCO-AI-CHAT mobile (dc7d6eaf6) — wake-word routing, inline confirm, mic dictation.
 */
import React from "react";
import { render, fireEvent, waitFor, act, renderHook } from "@testing-library/react-native";

let mockSegments: string[] = ["(app)", "schedule"];
jest.mock("expo-router", () => ({ useSegments: () => mockSegments }));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0 }) }));
jest.mock("@/src/auth", () => ({ useAuth: () => ({ user: { role: "technician" } }) }));
jest.mock("@/src/services/marco/voicePreferences", () => ({ getWakeWordEnabled: async () => true, getVoiceResponseEnabled: async () => true }));
// Minimal mock with the REAL expo-audio 1.x export surface (no expo-av `Recording` class).
const mockRecorder = { prepareToRecordAsync: jest.fn(async () => {}), record: jest.fn(), stop: jest.fn(async () => {}), uri: "file://a.m4a" };
jest.mock("expo-audio", () => ({
  useAudioRecorder: () => mockRecorder,
  RecordingPresets: { HIGH_QUALITY: {} },
  setAudioModeAsync: jest.fn(async () => {}),
  getRecordingPermissionsAsync: jest.fn(async () => ({ granted: true })),
  requestRecordingPermissionsAsync: jest.fn(async () => ({ granted: true })),
}));
// Mirrors wakeWordService: callback stored once, `if (_running) return true`.
let mockOnWake: any = null;
jest.mock("@/src/services/marco/wakeWordService", () => ({
  startWakeWord: jest.fn(async (cb: any) => { if (!mockOnWake) mockOnWake = cb; return true; }),
  stopWakeWord: jest.fn(),
  isWakeWordRunning: () => !!mockOnWake,
}));
const mockTranscribe = jest.fn();
jest.mock("@/src/services/marco/executeMarco", () => ({ transcribeAudio: (...a: any[]) => mockTranscribe(...a), executeMarco: jest.fn() }));
const mockSend = jest.fn();
jest.mock("@/src/api/aiDock", () => ({
  listAIEmployees: async () => [{ id: "e1", key: "marco", name: "Marco", role: "Ops" }],
  getAICreditsBalance: async () => ({ balance: 10 }),
  listPendingActions: async () => [],
  createConversation: async () => ({ id: "c1" }),
  sendConversationMessage: (...a: any[]) => mockSend(...a),
  approveAction: jest.fn(), rejectAction: jest.fn(),
}));

import { useMarcoWakeWord } from "@/src/hooks/useMarcoWakeWord";
import { getRecordingPermissionsAsync } from "expo-audio";
import AIDockDrawer from "@/src/components/ai/AIDockDrawer";

beforeEach(() => { mockOnWake = null; jest.clearAllMocks(); });

async function startHook(segs: string[]) {
  mockSegments = segs;
  const onOpenDock = jest.fn();
  const hook = renderHook(() => useMarcoWakeWord(onOpenDock));
  await waitFor(() => expect(mockOnWake).not.toBeNull());
  return { onOpenDock, hook };
}

describe("wake-word routing", () => {
  it("non-job route → opens the dock, no voice pipeline", async () => {
    const { onOpenDock } = await startHook(["(app)", "schedule"]);
    await act(async () => { await mockOnWake(); });
    expect(onOpenDock).toHaveBeenCalledTimes(1);
    expect(getRecordingPermissionsAsync).not.toHaveBeenCalled();
  });

  it("job route → voice-command pipeline, dock NOT opened", async () => {
    const { onOpenDock } = await startHook(["job", "[id]"]);
    act(() => { mockOnWake(); });
    await waitFor(() => expect(mockRecorder.record).toHaveBeenCalled());
    expect(onOpenDock).not.toHaveBeenCalled();
  });

  it("boundary: navigating schedule → job AFTER start still routes to voice pipeline", async () => {
    const { onOpenDock, hook } = await startHook(["(app)", "schedule"]);
    mockSegments = ["job", "[id]"];
    hook.rerender({});
    act(() => { mockOnWake(); });
    await waitFor(() => expect(getRecordingPermissionsAsync).toHaveBeenCalled());
    expect(onOpenDock).not.toHaveBeenCalled();
  });
});

async function openMarcoChat() {
  const r = render(<AIDockDrawer visible onClose={jest.fn()} />);
  fireEvent.press(await r.findByTestId("ai-employee-marco"));
  await waitFor(() => expect(r.getByTestId("ai-dock-send")).toBeTruthy());
  return r;
}

describe("AI dock chat", () => {
  it("renders inline Confirm card inside the Marco bubble when an action is returned", async () => {
    mockSend.mockResolvedValue({
      user_message: { id: "u1", text: "move job" },
      assistant_message: { id: "m1", text: "Want me to reschedule?" },
      action: { id: "a1", title: "Reschedule job", summary: "Tue → Wed", status: "pending" },
    });
    const r = await openMarcoChat();
    fireEvent.changeText(r.getByTestId("ai-dock-input"), "move job");
    await waitFor(() => fireEvent.press(r.getByTestId("ai-dock-send")));
    expect(await r.findByTestId("ai-inline-confirm-a1")).toBeTruthy();
    expect(r.getByTestId("ai-inline-approve-a1")).toBeTruthy();
  });

  it("mic: start → stop appends transcript to input and does NOT auto-send", async () => {
    mockTranscribe.mockResolvedValue({ transcript: "for tomorrow" });
    const r = await openMarcoChat();
    fireEvent.changeText(r.getByTestId("ai-dock-input"), "move job");
    await act(async () => { fireEvent.press(r.getByTestId("ai-dock-mic")); });
    await act(async () => { fireEvent.press(r.getByTestId("ai-dock-mic")); });
    await waitFor(() => expect(r.getByTestId("ai-dock-input").props.value).toBe("move job for tomorrow"));
    expect(mockSend).not.toHaveBeenCalled();
  });
});
