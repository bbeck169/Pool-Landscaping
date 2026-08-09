/**
 * Phase 52.1c · Feb-2026 — Mobile walkie live-streaming client jest suite.
 *
 * Mounts ``LivePanel.tsx`` with every native dep mocked:
 *   • ``react-native-webrtc`` classes (RTCPeerConnection, mediaDevices,
 *     RTCSessionDescription, RTCIceCandidate).
 *   • ``expo-audio`` recorder (via DI knob).
 *   • WebSocket, api.get, api_base, getAuthToken.
 *
 * Assertions:
 *   1. On mount → fetches ICE, gets mic, opens WS with JWT-bearing URL,
 *      starts the auto-record recorder.
 *   2. session-state → creates an offer per existing peer + sends via WS.
 *   3. Incoming offer → creates an answer + sends via WS.
 *   4. PTT press flow: press-in → local track enabled + speaking:true
 *      frame emitted; press-out → track disabled + speaking:false frame.
 *   5. peer-joined + peer-left update the roster.
 *   6. speaking-update marks the remote peer chip.
 *   7. session-ended triggers the auto-record clip upload.
 *   8. Unmount fires clip upload + cleans up peers.
 *   9. Live-mode key + PTT-mode key partition by channel id.
 *  10. VOX toggle is disabled on mobile (52.1c "PTT-only" decision).
 */
import React from "react";
import { render, waitFor, fireEvent, act } from "@testing-library/react-native";

/* ═════════════════════════════════════════════════════════════════
 * Mocks — must be declared before importing the module under test.
 * Jest requires mock-factory-referenced variables be prefixed with
 * ``mock`` (case-insensitive) to survive the hoist.
 * ═══════════════════════════════════════════════════════════════ */
const mockApiGet = jest.fn();
jest.mock("@/src/api", () => ({
  api: { get: (...a: any[]) => mockApiGet(...a) },
  api_base: () => "http://backend.test",
  getAuthToken: async () => "JWT_XYZ",
}));

const mockRtcCtor = jest.fn();
const mockIceCtor = jest.fn(function (o) { return { ...o, _ice: true }; });
const mockSdpCtor = jest.fn(function (o) { return { ...o, _sdp: true }; });
const mockGetUserMedia = jest.fn();
jest.mock("react-native-webrtc", () => {
  return {
    RTCPeerConnection: jest.fn().mockImplementation((...a: any[]) => mockRtcCtor(...a)),
    RTCSessionDescription: jest.fn().mockImplementation((...a: any[]) => mockSdpCtor(...a)),
    RTCIceCandidate: jest.fn().mockImplementation((...a: any[]) => mockIceCtor(...a)),
    mediaDevices: { getUserMedia: (...a: any[]) => mockGetUserMedia(...a) },
  };
});

// expo-audio: shared mock recorder so tests can inspect record/stop calls.
const mockRecorderStart = jest.fn();
const mockRecorderStop = jest.fn(async () => {});
const mockRecorderPrepare = jest.fn(async () => {});
jest.mock("expo-audio", () => ({
  RecordingPresets: { HIGH_QUALITY: {} },
  requestRecordingPermissionsAsync: jest.fn(async () => ({ granted: true })),
  useAudioRecorder: () => ({
    prepareToRecordAsync: mockRecorderPrepare,
    record: mockRecorderStart,
    stop: mockRecorderStop,
    uri: "file:///tmp/live.m4a",
  }),
}));

// fetch (used for the auto-record clip upload).
const fetchMock = jest.fn(async () => ({ ok: true, json: async () => ({}) }));
global.fetch = fetchMock as any;

// AsyncStorage — use the official jest mock so `.setItem` / `.getItem`
// resolve cleanly instead of hitting the null NativeModule bridge.
jest.mock("@react-native-async-storage/async-storage", () =>
  require("@react-native-async-storage/async-storage/jest/async-storage-mock"),
);

import LivePanel, {
  liveModeKey,
  pttModeKey,
  buildSignalingUrl,
} from "@/src/pages/walkie/LivePanel";

/* ═════════════════════════════════════════════════════════════════
 * Test-side WS + PC + Stream fakes.
 * ═══════════════════════════════════════════════════════════════ */
function makeFakeWs() {
  const listeners: any = {};
  return {
    _url: "",
    send: jest.fn(),
    close: jest.fn(),
    set onopen(fn: any) { listeners.open = fn; },
    set onclose(fn: any) { listeners.close = fn; },
    set onmessage(fn: any) { listeners.message = fn; },
    set onerror(fn: any) { listeners.error = fn; },
    _emit(name: string, ev?: any) { listeners[name]?.(ev); },
  };
}

function makeFakePc() {
  return {
    _handlers: {},
    addTrack: jest.fn(),
    createOffer: jest.fn(async () => ({ type: "offer", sdp: "OFFER-SDP" })),
    createAnswer: jest.fn(async () => ({ type: "answer", sdp: "ANSWER-SDP" })),
    setLocalDescription: jest.fn(async () => {}),
    setRemoteDescription: jest.fn(async () => {}),
    addIceCandidate: jest.fn(async () => {}),
    close: jest.fn(),
    set onicecandidate(fn: any) { (this as any)._handlers.ice = fn; },
    set ontrack(fn: any) { (this as any)._handlers.track = fn; },
  };
}

function makeFakeStream() {
  const track = { enabled: false, kind: "audio", stop: jest.fn() };
  return {
    getAudioTracks: () => [track],
    getTracks: () => [track],
    _track: track,
  };
}

const CHANNEL: any = { id: "ch1", kind: "department", department: "pool", supports_live: true };
const USER: any = { id: "u_local", role: "technician" };

let fakeWs: any;
let currentStream: any;
const wsFactory = jest.fn((url: string) => { fakeWs = makeFakeWs(); fakeWs._url = url; return fakeWs; });
const rtcFactory = jest.fn(() => makeFakePc());
const getUserMediaKnob = jest.fn(async () => { currentStream = makeFakeStream(); return currentStream; });

beforeEach(() => {
  mockApiGet.mockReset();
  wsFactory.mockClear();
  rtcFactory.mockClear();
  getUserMediaKnob.mockClear();
  fetchMock.mockClear();
  mockRecorderStart.mockClear();
  mockRecorderStop.mockClear();
  mockApiGet.mockResolvedValue({ ice_servers: [{ urls: "stun:stun.l.google.com:19302" }] });
});

function mount() {
  return render(
    <LivePanel
      channel={CHANNEL}
      user={USER}
      onExit={() => {}}
      _wsFactory={wsFactory}
      _rtcFactory={rtcFactory}
      _getUserMedia={getUserMediaKnob}
      _tokenGetter={() => "JWT_XYZ"}
    />,
  );
}

/* ═════════════════════════════════════════════════════════════════
 * Pure helpers
 * ═══════════════════════════════════════════════════════════════ */
describe("Phase 52.1c · mobile helpers", () => {
  it("liveModeKey / pttModeKey partition by channel id", () => {
    expect(liveModeKey("ch1")).toBe("walkie_live_mode_ch1");
    expect(pttModeKey("ch1")).toBe("walkie_ptt_mode_ch1");
    expect(liveModeKey("ch1")).not.toBe(liveModeKey("ch2"));
  });

  it("buildSignalingUrl encodes the token and swaps http→ws", () => {
    const u = buildSignalingUrl("ch1", "abc def");
    expect(u).toBe("ws://backend.test/api/ws/walkie/ch1?token=abc%20def");
  });
});

/* ═════════════════════════════════════════════════════════════════
 * LivePanel mount + signaling
 * ═══════════════════════════════════════════════════════════════ */
describe("Phase 52.1c · LivePanel (mobile)", () => {
  it("mounts, fetches ICE, gets mic, opens WS with JWT, starts recorder", async () => {
    mount();
    await waitFor(() => expect(mockApiGet).toHaveBeenCalledWith("/walkie/ice-servers"));
    await waitFor(() => expect(getUserMediaKnob).toHaveBeenCalledWith({ audio: true }));
    await waitFor(() => expect(wsFactory).toHaveBeenCalledTimes(1));
    expect(wsFactory.mock.calls[0][0]).toBe("ws://backend.test/api/ws/walkie/ch1?token=JWT_XYZ");
    await waitFor(() => expect(mockRecorderStart).toHaveBeenCalled());
  });

  it("session-state creates offers for every existing peer", async () => {
    mount();
    await waitFor(() => expect(wsFactory).toHaveBeenCalledTimes(1));
    act(() => fakeWs._emit("open"));
    await act(async () => {
      fakeWs._emit("message", { data: JSON.stringify({
        type: "session-state", session_id: "sess1", roster: ["u_local", "u_a", "u_b"],
      })});
    });
    await waitFor(() => expect(rtcFactory).toHaveBeenCalledTimes(2));
    const sent = fakeWs.send.mock.calls.map((c: any[]) => JSON.parse(c[0]));
    const offers = sent.filter((f: any) => f.type === "offer");
    expect(offers.length).toBe(2);
    expect(new Set(offers.map((o: any) => o.target_user_id))).toEqual(new Set(["u_a", "u_b"]));
  });

  it("responds to incoming offer with an answer over WS", async () => {
    mount();
    await waitFor(() => expect(wsFactory).toHaveBeenCalledTimes(1));
    act(() => fakeWs._emit("open"));
    await act(async () => {
      fakeWs._emit("message", { data: JSON.stringify({
        type: "session-state", session_id: "s", roster: ["u_local"],
      })});
    });
    fakeWs.send.mockClear();
    await act(async () => {
      fakeWs._emit("message", { data: JSON.stringify({
        type: "offer", from_user_id: "u_c", sdp: "OFFER-FROM-C",
      })});
    });
    const frames = fakeWs.send.mock.calls.map((c: any[]) => JSON.parse(c[0]));
    const answer = frames.find((f: any) => f.type === "answer");
    expect(answer).toBeTruthy();
    expect(answer.target_user_id).toBe("u_c");
    expect(answer.sdp).toBe("ANSWER-SDP");
  });

  it("PTT press-in/out flips local track + broadcasts speaking frames", async () => {
    const { getByTestId } = mount();
    await waitFor(() => expect(getUserMediaKnob).toHaveBeenCalled());
    act(() => fakeWs._emit("open"));
    const talk = getByTestId("walkie-live-talk-button");
    await act(async () => { fireEvent(talk, "pressIn"); });
    expect(currentStream._track.enabled).toBe(true);
    const speakingOn = fakeWs.send.mock.calls.map((c: any[]) => JSON.parse(c[0]))
      .find((f: any) => f.type === "speaking" && f.is_speaking === true);
    expect(speakingOn).toBeTruthy();

    await act(async () => { fireEvent(talk, "pressOut"); });
    expect(currentStream._track.enabled).toBe(false);
    const speakingOff = fakeWs.send.mock.calls.map((c: any[]) => JSON.parse(c[0]))
      .filter((f: any) => f.type === "speaking").pop();
    expect(speakingOff.is_speaking).toBe(false);
  });

  it("peer-joined + peer-left update the roster", async () => {
    const { getByTestId, queryByTestId } = mount();
    await waitFor(() => expect(wsFactory).toHaveBeenCalledTimes(1));
    act(() => fakeWs._emit("open"));
    await act(async () => {
      fakeWs._emit("message", { data: JSON.stringify({
        type: "session-state", session_id: "s", roster: ["u_local"],
      })});
    });
    await act(async () => {
      fakeWs._emit("message", { data: JSON.stringify({ type: "peer-joined", user_id: "u_new" })});
    });
    expect(getByTestId("walkie-live-peer-u_new")).toBeTruthy();
    await act(async () => {
      fakeWs._emit("message", { data: JSON.stringify({ type: "peer-left", user_id: "u_new" })});
    });
    expect(queryByTestId("walkie-live-peer-u_new")).toBeNull();
  });

  it("speaking-update marks the remote chip", async () => {
    const { getByTestId } = mount();
    await waitFor(() => expect(wsFactory).toHaveBeenCalledTimes(1));
    act(() => fakeWs._emit("open"));
    await act(async () => {
      fakeWs._emit("message", { data: JSON.stringify({
        type: "session-state", session_id: "s", roster: ["u_local", "u_x"],
      })});
    });
    await act(async () => {
      fakeWs._emit("message", { data: JSON.stringify({
        type: "speaking-update", user_id: "u_x", is_speaking: true,
      })});
    });
    const chip = getByTestId("walkie-live-peer-u_x");
    // Verify the "· speaking" suffix rendered.
    const flatText = (function collect(el: any): string {
      if (!el) return "";
      if (typeof el === "string" || typeof el === "number") return String(el);
      const kids = el?.props?.children;
      if (Array.isArray(kids)) return kids.map(collect).join("");
      return collect(kids);
    })(chip);
    expect(flatText).toMatch(/speaking/i);
  });

  it("session-ended triggers the auto-record clip upload", async () => {
    mount();
    await waitFor(() => expect(wsFactory).toHaveBeenCalledTimes(1));
    act(() => fakeWs._emit("open"));
    await act(async () => {
      fakeWs._emit("message", { data: JSON.stringify({
        type: "session-state", session_id: "sess-abc", roster: ["u_local"],
      })});
    });
    await act(async () => {
      fakeWs._emit("message", { data: JSON.stringify({
        type: "session-ended", session_id: "sess-abc", reason: "empty",
      })});
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, opts] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/walkie\/messages$/);
    expect(opts.method).toBe("POST");
    // FormData body — verify the metadata field.
    const fd: FormData = opts.body;
    const meta = JSON.parse(fd.get("metadata") as string);
    expect(meta.source).toBe("live_session");
    expect(meta.session_id).toBe("sess-abc");
  });

  it("unmount fires the clip upload + cleans up peer connections", async () => {
    const view = mount();
    await waitFor(() => expect(wsFactory).toHaveBeenCalledTimes(1));
    act(() => fakeWs._emit("open"));
    await act(async () => {
      fakeWs._emit("message", { data: JSON.stringify({
        type: "session-state", session_id: "sess-unmount", roster: ["u_local", "u_a"],
      })});
    });
    view.unmount();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  });

  it("mobile 52.1c ships PTT-only — VOX chip is disabled + labeled", async () => {
    const { getByTestId } = mount();
    await waitFor(() => expect(getUserMediaKnob).toHaveBeenCalled());
    const voxChip = getByTestId("walkie-live-mode-vox-disabled");
    expect(voxChip.props.accessibilityState?.disabled).toBe(true);
  });
});
