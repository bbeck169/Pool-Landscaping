/**
 * Phase 52.1b · Feb-2026 — Walkie live-streaming client (web) vitest suite.
 *
 * Covers the pure helpers + the LivePanel component using
 * dependency-injected fakes for WebSocket / RTCPeerConnection /
 * MediaRecorder / AudioContext / getUserMedia. Real browser globals
 * are never touched — jsdom doesn't ship any of these.
 */
import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup, act, fireEvent, waitFor } from "@testing-library/react";

const apiGet = vi.fn();
const apiPost = vi.fn();
vi.mock("@/api", () => ({
  api: { get: (...a) => apiGet(...a), post: (...a) => apiPost(...a) },
  api_base: "http://backend.test",
  TOKEN_KEY: "walkie_test_token",
}));

import LivePanel, {
  rmsFromTimeDomain,
  VOX_THRESHOLD_RMS,
  VOX_WINDOW_MS,
  liveModeKey,
  pttModeKey,
  buildSignalingUrl,
} from "@/pages/walkie/LivePanel";

const CHANNEL = { id: "ch1", kind: "department", department: "pool", supports_live: true };
const USER = { id: "u_local", role: "technician", department: "pool" };

/* ═════════════════════════════════════════════════════════════════
 * Fakes
 * ═══════════════════════════════════════════════════════════════ */
function makeFakeStream() {
  const track = { enabled: false, kind: "audio", stop: vi.fn() };
  return {
    getAudioTracks: () => [track],
    getTracks: () => [track],
    _track: track,
  };
}

function makeFakeWS() {
  const listeners = {};
  const ws = {
    readyState: 0,
    send: vi.fn(),
    close: vi.fn(),
    set onopen(fn) { listeners.open = fn; },
    set onclose(fn) { listeners.close = fn; },
    set onmessage(fn) { listeners.message = fn; },
    set onerror(fn) { listeners.error = fn; },
    _emit: (evt, data) => listeners[evt]?.(data),
  };
  return ws;
}

function makeFakePC() {
  const pc = {
    _handlers: {},
    addTrack: vi.fn(() => ({})),
    createOffer: vi.fn(async () => ({ type: "offer", sdp: "OFFER-SDP" })),
    createAnswer: vi.fn(async () => ({ type: "answer", sdp: "ANSWER-SDP" })),
    setLocalDescription: vi.fn(async () => {}),
    setRemoteDescription: vi.fn(async () => {}),
    addIceCandidate: vi.fn(async () => {}),
    close: vi.fn(),
    set onicecandidate(fn) { pc._handlers.ice = fn; },
    set ontrack(fn) { pc._handlers.track = fn; },
  };
  return pc;
}

function makeFakeRecorder(stream) {
  const rec = {
    state: "inactive",
    ondataavailable: null,
    onstop: null,
    start: vi.fn(function (interval) { rec.state = "recording"; rec._interval = interval; }),
    stop: vi.fn(function () {
      rec.state = "inactive";
      // Emit a chunk before stopping so flushRecordingToClip has bytes.
      try { rec.ondataavailable?.({ data: new Blob(["fake-audio"], { type: "audio/webm" }) }); } catch { /* ignore */ }
      try { rec.onstop?.(); } catch { /* ignore */ }
    }),
  };
  return rec;
}

/* ═════════════════════════════════════════════════════════════════
 * Pure-helper tests
 * ═══════════════════════════════════════════════════════════════ */
describe("Phase 52.1b · helpers", () => {
  it("rmsFromTimeDomain returns 0 for empty input", () => {
    expect(rmsFromTimeDomain(new Uint8Array(0))).toBe(0);
    expect(rmsFromTimeDomain(null)).toBe(0);
  });

  it("rmsFromTimeDomain returns 0 for silence (all 128)", () => {
    const buf = new Uint8Array(256).fill(128);
    expect(rmsFromTimeDomain(buf)).toBe(0);
  });

  it("rmsFromTimeDomain rises above VOX threshold on a loud waveform", () => {
    // ±0.5 amplitude → RMS ~ 0.5 >> threshold
    const buf = new Uint8Array(256);
    for (let i = 0; i < buf.length; i++) buf[i] = i % 2 ? 192 : 64;
    expect(rmsFromTimeDomain(buf)).toBeGreaterThan(VOX_THRESHOLD_RMS * 10);
  });

  it("liveModeKey / pttModeKey partition by channel id", () => {
    expect(liveModeKey("ch1")).toBe("walkie_live_mode_ch1");
    expect(pttModeKey("ch1")).toBe("walkie_ptt_mode_ch1");
    expect(liveModeKey("ch1")).not.toBe(liveModeKey("ch2"));
  });

  it("buildSignalingUrl rewrites http→ws and encodes the token", () => {
    const u = buildSignalingUrl("ch1", "abc def");
    expect(u).toBe("ws://backend.test/api/ws/walkie/ch1?token=abc%20def");
  });

  it("VOX_WINDOW_MS is the 200ms hysteresis the spec calls for", () => {
    expect(VOX_WINDOW_MS).toBe(200);
  });
});

/* ═════════════════════════════════════════════════════════════════
 * LivePanel mount + WebRTC handshake
 * ═══════════════════════════════════════════════════════════════ */
describe("Phase 52.1b · LivePanel", () => {
  let fakeWs;
  let fakeRec;
  let fakeStream;
  let created;

  const wsFactory = vi.fn((url) => { fakeWs = makeFakeWS(); fakeWs._url = url; return fakeWs; });
  const rtcFactory = vi.fn(() => { const p = makeFakePC(); created.push(p); return p; });
  const audioContextFactory = vi.fn(() => ({
    createMediaStreamSource: () => ({ connect: vi.fn() }),
    createAnalyser: () => ({ fftSize: 512, getByteTimeDomainData: (b) => b.fill(128), disconnect: vi.fn() }),
    close: vi.fn(),
  }));
  const mediaRecorderFactory = vi.fn((stream) => { fakeRec = makeFakeRecorder(stream); return fakeRec; });
  const getUserMedia = vi.fn(async () => { fakeStream = makeFakeStream(); return fakeStream; });
  const tokenGetter = () => "JWT_XYZ";

  beforeEach(() => {
    apiGet.mockReset();
    apiPost.mockReset();
    wsFactory.mockClear();
    rtcFactory.mockClear();
    mediaRecorderFactory.mockClear();
    getUserMedia.mockClear();
    created = [];
    // ICE server fetch → static default fine.
    apiGet.mockResolvedValue({ ice_servers: [{ urls: "stun:stun.l.google.com:19302" }] });
    apiPost.mockResolvedValue({});
    localStorage.clear();
  });
  afterEach(() => cleanup());

  function mount() {
    return render(
      <LivePanel
        channel={CHANNEL}
        user={USER}
        onExit={() => {}}
        _wsFactory={wsFactory}
        _rtcFactory={rtcFactory}
        _audioContextFactory={audioContextFactory}
        _mediaRecorderFactory={mediaRecorderFactory}
        _getUserMedia={getUserMedia}
        _tokenGetter={tokenGetter}
      />,
    );
  }

  it("mounts, requests ICE + mic, opens the signaling WS with a JWT", async () => {
    mount();
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith("/walkie/ice-servers"));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledWith({ audio: true }));
    await waitFor(() => expect(wsFactory).toHaveBeenCalledTimes(1));
    expect(wsFactory.mock.calls[0][0]).toBe("ws://backend.test/api/ws/walkie/ch1?token=JWT_XYZ");
    // MediaRecorder auto-started for the auto-record clip.
    expect(mediaRecorderFactory).toHaveBeenCalledTimes(1);
    expect(fakeRec.start).toHaveBeenCalled();
  });

  it("session-state creates an offer per existing peer", async () => {
    mount();
    await waitFor(() => expect(wsFactory).toHaveBeenCalledTimes(1));
    act(() => fakeWs._emit("open"));
    await act(async () => {
      fakeWs._emit("message", { data: JSON.stringify({
        type: "session-state", session_id: "sess1", roster: ["u_local", "u_a", "u_b"],
      })});
    });
    // Two peers → two PCs → two offers sent through WS.
    await waitFor(() => expect(rtcFactory).toHaveBeenCalledTimes(2));
    const sent = fakeWs.send.mock.calls.map((c) => JSON.parse(c[0]));
    const offers = sent.filter((f) => f.type === "offer");
    expect(offers.length).toBe(2);
    expect(new Set(offers.map((o) => o.target_user_id))).toEqual(new Set(["u_a", "u_b"]));
    for (const o of offers) expect(o.sdp).toBe("OFFER-SDP");
  });

  it("on incoming offer creates a PC, answers, and sends the answer", async () => {
    mount();
    await waitFor(() => expect(wsFactory).toHaveBeenCalledTimes(1));
    act(() => fakeWs._emit("open"));
    await act(async () => {
      fakeWs._emit("message", { data: JSON.stringify({
        type: "session-state", session_id: "sess1", roster: ["u_local"],
      })});
    });
    fakeWs.send.mockClear();
    rtcFactory.mockClear();
    await act(async () => {
      fakeWs._emit("message", { data: JSON.stringify({
        type: "offer", from_user_id: "u_c", sdp: "OFFER-FROM-C",
      })});
    });
    await waitFor(() => expect(rtcFactory).toHaveBeenCalledTimes(1));
    const answerFrame = fakeWs.send.mock.calls.map((c) => JSON.parse(c[0])).find((f) => f.type === "answer");
    expect(answerFrame).toBeTruthy();
    expect(answerFrame.target_user_id).toBe("u_c");
    expect(answerFrame.sdp).toBe("ANSWER-SDP");
  });

  it("PTT press enables local track and broadcasts speaking=true", async () => {
    mount();
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
    act(() => fakeWs._emit("open"));
    // Push the talk button — component uses onMouseDown to start.
    const talk = await screen.findByTestId("walkie-live-talk-button");
    await act(async () => { fireEvent.mouseDown(talk); });
    expect(fakeStream._track.enabled).toBe(true);
    const speaking = fakeWs.send.mock.calls.map((c) => JSON.parse(c[0]))
      .find((f) => f.type === "speaking");
    expect(speaking).toEqual({ type: "speaking", is_speaking: true });

    await act(async () => { fireEvent.mouseUp(talk); });
    expect(fakeStream._track.enabled).toBe(false);
    const stopSpeaking = fakeWs.send.mock.calls.map((c) => JSON.parse(c[0]))
      .filter((f) => f.type === "speaking").pop();
    expect(stopSpeaking).toEqual({ type: "speaking", is_speaking: false });
  });

  it("mode toggle persists PTT/VOX per channel to localStorage", async () => {
    mount();
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
    await act(async () => { fireEvent.click(await screen.findByTestId("walkie-live-mode-vox")); });
    expect(localStorage.getItem(pttModeKey("ch1"))).toBe("vox");
    await act(async () => { fireEvent.click(await screen.findByTestId("walkie-live-mode-ptt")); });
    expect(localStorage.getItem(pttModeKey("ch1"))).toBe("ptt");
  });

  it("peer-joined + peer-left update the roster", async () => {
    mount();
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
    expect(await screen.findByTestId("walkie-live-peer-u_new")).toBeInTheDocument();
    await act(async () => {
      fakeWs._emit("message", { data: JSON.stringify({ type: "peer-left", user_id: "u_new" })});
    });
    expect(screen.queryByTestId("walkie-live-peer-u_new")).toBeNull();
  });

  it("speaking-update marks the remote peer as speaking", async () => {
    mount();
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
    const chip = await screen.findByTestId("walkie-live-peer-u_x");
    expect(chip.className).toMatch(/emerald/);
    expect(chip.textContent).toMatch(/speaking/);
  });

  it("on unmount uploads the recorded clip to /walkie/messages", async () => {
    const { unmount } = mount();
    await waitFor(() => expect(wsFactory).toHaveBeenCalledTimes(1));
    act(() => fakeWs._emit("open"));
    // Ensure we have a session id so the flush upload fires.
    await act(async () => {
      fakeWs._emit("message", { data: JSON.stringify({
        type: "session-state", session_id: "sess-xyz", roster: ["u_local"],
      })});
    });
    unmount();
    await waitFor(() => expect(apiPost).toHaveBeenCalled());
    const [path, body, opts] = apiPost.mock.calls[0];
    expect(path).toBe("/walkie/messages");
    expect(body).toBeInstanceOf(FormData);
    expect(body.get("channel_id")).toBe("ch1");
    const meta = JSON.parse(body.get("metadata"));
    expect(meta.source).toBe("live_session");
    expect(meta.session_id).toBe("sess-xyz");
    expect(opts?.isForm).toBe(true);
  });

  it("session-ended message triggers the auto-record upload", async () => {
    mount();
    await waitFor(() => expect(wsFactory).toHaveBeenCalledTimes(1));
    act(() => fakeWs._emit("open"));
    await act(async () => {
      fakeWs._emit("message", { data: JSON.stringify({
        type: "session-state", session_id: "sess-ended", roster: ["u_local"],
      })});
    });
    await act(async () => {
      fakeWs._emit("message", { data: JSON.stringify({
        type: "session-ended", session_id: "sess-ended", reason: "empty",
      })});
    });
    await waitFor(() => expect(apiPost).toHaveBeenCalled());
    const body = apiPost.mock.calls[0][1];
    const meta = JSON.parse(body.get("metadata"));
    expect(meta.session_id).toBe("sess-ended");
  });

  it("exit button fires the onExit prop", async () => {
    const onExit = vi.fn();
    render(
      <LivePanel
        channel={CHANNEL}
        user={USER}
        onExit={onExit}
        _wsFactory={wsFactory}
        _rtcFactory={rtcFactory}
        _audioContextFactory={audioContextFactory}
        _mediaRecorderFactory={mediaRecorderFactory}
        _getUserMedia={getUserMedia}
        _tokenGetter={tokenGetter}
      />,
    );
    await waitFor(() => expect(wsFactory).toHaveBeenCalledTimes(1));
    await act(async () => { fireEvent.click(await screen.findByTestId("walkie-live-exit")); });
    expect(onExit).toHaveBeenCalled();
  });
});
