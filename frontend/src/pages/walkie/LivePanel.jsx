/**
 * Phase 52.1b · Feb-2026 — Walkie live-streaming client panel (web).
 *
 * When the user flips "Live channel" ON in a walkie channel that
 * supports it, this component takes over the footer: it connects to
 * the Phase 52.1a signaling WebSocket, dials every joining peer via
 * ``RTCPeerConnection``, plays each remote track through a hidden
 * ``<audio autoplay>``, gates local mic capture by PTT or VOX, and
 * records the whole session so the closing peer can post it back as
 * an async clip (24h TTL).
 *
 * ── Contract ───────────────────────────────────────────────────────
 *   Props:
 *     channel       — the walkie channel dict from /api/walkie/channels
 *     user          — the current authenticated user
 *     onExit        — called when the panel wants to fold back into
 *                     async mode (user closes live).
 *     factories     — OPTIONAL dependency-injection knobs used by the
 *                     vitest suite to swap in fakes for the browser
 *                     WebSocket / RTCPeerConnection / MediaRecorder /
 *                     AudioContext / getUserMedia. Every knob has a
 *                     sensible browser-native default.
 *
 * ── PTT vs VOX ─────────────────────────────────────────────────────
 *   Default is PTT (spacebar-hold on desktop, mouse-hold on the big
 *   "Talk" button). VOX opts into a WebAudio AnalyserNode RMS-over-
 *   200ms detector. Choice is persisted in
 *     localStorage["walkie_ptt_mode_{channel_id}"] ∈ {"ptt","vox"}
 *
 * ── Auto-record ────────────────────────────────────────────────────
 *   A MediaRecorder is spun up when the panel mounts (recording the
 *   local mic + the mixed remote audio when browser supports capturing
 *   from an AudioContext destination). When the session ends we POST
 *   the blob to /api/walkie/messages with
 *     metadata: { source: "live_session", session_id }
 *   so the file surfaces in the channel timeline like any other clip.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Mic, MicOff, Radio, X, Zap, ZapOff } from "lucide-react";
import { toast } from "sonner";

import { api, api_base, TOKEN_KEY } from "@/api";

/* ═══════════════════════════════════════════════════════════════════
 * localStorage keys
 * ═════════════════════════════════════════════════════════════════ */
export function liveModeKey(channelId) {
  return `walkie_live_mode_${channelId}`;
}
export function pttModeKey(channelId) {
  return `walkie_ptt_mode_${channelId}`;
}

/* ═══════════════════════════════════════════════════════════════════
 * VOX detector — RMS over a 200ms window against a -50dB threshold.
 * Exported for unit-testability.
 * ═════════════════════════════════════════════════════════════════ */
export function rmsFromTimeDomain(buf) {
  if (!buf || !buf.length) return 0;
  let s = 0;
  for (let i = 0; i < buf.length; i++) {
    const v = buf[i] / 128 - 1; // Uint8 → [-1, 1]
    s += v * v;
  }
  return Math.sqrt(s / buf.length);
}

// -50 dBFS → 10 ** (-50/20) ≈ 0.00316
export const VOX_THRESHOLD_RMS = 0.00316;
export const VOX_WINDOW_MS = 200;

/* ═══════════════════════════════════════════════════════════════════
 * Signaling URL builder (exposed for tests)
 * ═════════════════════════════════════════════════════════════════ */
export function buildSignalingUrl(channelId, token) {
  // ``api_base`` is a function in production (returns the FastAPI
  // root URL with the ``/api`` suffix). Tests may mock it as a
  // string via vi.mock; accept both shapes.
  const raw = typeof api_base === "function" ? api_base() : (api_base || "");
  const httpBase = String(raw).replace(/\/?api\/?$/i, "");
  const wsBase = httpBase.replace(/^http/i, "ws");
  return `${wsBase}/api/ws/walkie/${channelId}?token=${encodeURIComponent(token || "")}`;
}

/* ═══════════════════════════════════════════════════════════════════
 * LivePanel
 * ═════════════════════════════════════════════════════════════════ */
export default function LivePanel({
  channel,
  user,
  onExit,
  // ── DI knobs (all optional; defaults use browser globals) ──
  _wsFactory,
  _rtcFactory,
  _audioContextFactory,
  _mediaRecorderFactory,
  _getUserMedia,
  _tokenGetter,
}) {
  const channelId = channel?.id;

  const [pttMode, setPttMode] = useState(() => {
    try { return localStorage.getItem(pttModeKey(channelId)) || "ptt"; } catch { return "ptt"; }
  });
  const [status, setStatus] = useState("idle");       // "idle" | "connecting" | "live" | "closed" | "error"
  const [transmitting, setTransmitting] = useState(false);
  const [peers, setPeers] = useState([]);              // roster user_ids
  const [speakingSet, setSpeakingSet] = useState(new Set()); // remote user_ids

  const wsRef = useRef(null);
  const localStreamRef = useRef(null);
  const localSenderMapRef = useRef(new Map());         // user_id → RTCRtpSender
  const rtcMapRef = useRef(new Map());                 // user_id → RTCPeerConnection
  const audioElsRef = useRef(new Map());               // user_id → <audio>
  const sessionIdRef = useRef(null);
  const iceServersRef = useRef([{ urls: "stun:stun.l.google.com:19302" }]);
  const recorderRef = useRef(null);
  const recorderChunksRef = useRef([]);
  const audioCtxRef = useRef(null);
  const analyserRef = useRef(null);
  const voxRafRef = useRef(null);
  const voxAboveSinceRef = useRef(0);
  const voxBelowSinceRef = useRef(0);

  // ── Token / factories with sensible defaults ────────────────────
  const tokenGetter = _tokenGetter || (() => {
    try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; }
  });
  const WSCtor = _wsFactory || ((url) => new WebSocket(url));
  const RTCCtor = useMemo(
    () => _rtcFactory || ((cfg) => new RTCPeerConnection(cfg)),
    [_rtcFactory],
  );
  const AudioCtxCtor = useMemo(
    () => _audioContextFactory || (() => new (window.AudioContext || window.webkitAudioContext)()),
    [_audioContextFactory],
  );
  const MediaRecCtor = useMemo(
    () => _mediaRecorderFactory || ((stream, opts) => new MediaRecorder(stream, opts)),
    [_mediaRecorderFactory],
  );
  const getUserMediaFn = _getUserMedia || ((constraints) => navigator.mediaDevices.getUserMedia(constraints));

  // ── Persist PTT/VOX mode ──────────────────────────────────────
  useEffect(() => {
    if (!channelId) return;
    try { localStorage.setItem(pttModeKey(channelId), pttMode); } catch { /* ignore */ }
  }, [pttMode, channelId]);

  // ── Transmit gate: mute/unmute local audio track ──────────────
  const setTransmit = useCallback((on) => {
    const s = localStreamRef.current;
    if (!s) return;
    s.getAudioTracks().forEach((t) => { t.enabled = !!on; });
    setTransmitting(!!on);
    // Broadcast to peers so their UI can highlight who's speaking.
    try {
      wsRef.current?.send(JSON.stringify({ type: "speaking", is_speaking: !!on }));
    } catch { /* ws closed */ }
  }, []);

  // ── VOX loop ──────────────────────────────────────────────────
  const startVox = useCallback(() => {
    if (analyserRef.current || !localStreamRef.current) return;
    try {
      const ctx = AudioCtxCtor();
      audioCtxRef.current = ctx;
      const src = ctx.createMediaStreamSource(localStreamRef.current);
      const an = ctx.createAnalyser();
      an.fftSize = 512;
      src.connect(an);
      analyserRef.current = an;
      const buf = new Uint8Array(an.fftSize);
      const tick = () => {
        if (!analyserRef.current) return;
        an.getByteTimeDomainData(buf);
        const rms = rmsFromTimeDomain(buf);
        const now = performance.now();
        if (rms > VOX_THRESHOLD_RMS) {
          if (!voxAboveSinceRef.current) voxAboveSinceRef.current = now;
          voxBelowSinceRef.current = 0;
          if (!transmittingRef.current && now - voxAboveSinceRef.current >= VOX_WINDOW_MS) {
            setTransmit(true);
          }
        } else {
          if (!voxBelowSinceRef.current) voxBelowSinceRef.current = now;
          voxAboveSinceRef.current = 0;
          if (transmittingRef.current && now - voxBelowSinceRef.current >= VOX_WINDOW_MS) {
            setTransmit(false);
          }
        }
        voxRafRef.current = requestAnimationFrame(tick);
      };
      voxRafRef.current = requestAnimationFrame(tick);
    } catch (e) {
      console.warn("[walkie.live] VOX init failed:", e);
    }
  }, [AudioCtxCtor, setTransmit]);

  const stopVox = useCallback(() => {
    if (voxRafRef.current) cancelAnimationFrame(voxRafRef.current);
    voxRafRef.current = null;
    try { analyserRef.current?.disconnect(); } catch { /* ignore */ }
    analyserRef.current = null;
    try { audioCtxRef.current?.close(); } catch { /* ignore */ }
    audioCtxRef.current = null;
  }, []);

  const transmittingRef = useRef(false);
  useEffect(() => { transmittingRef.current = transmitting; }, [transmitting]);

  // ── PTT keyboard hold (spacebar) ──────────────────────────────
  useEffect(() => {
    if (pttMode !== "ptt" || status !== "live") return undefined;
    const down = (e) => {
      if (e.code !== "Space" || e.repeat) return;
      if (["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
      e.preventDefault();
      setTransmit(true);
    };
    const up = (e) => {
      if (e.code !== "Space") return;
      setTransmit(false);
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [pttMode, status, setTransmit]);

  // ── Switch PTT/VOX mode side-effects ──────────────────────────
  useEffect(() => {
    if (status !== "live") return;
    if (pttMode === "vox") {
      startVox();
    } else {
      stopVox();
      if (transmittingRef.current) setTransmit(false);
    }
    return () => stopVox();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pttMode, status]);

  // ── Peer management helpers ───────────────────────────────────
  const createPeer = useCallback(async (remoteUid, initiator) => {
    if (rtcMapRef.current.has(remoteUid)) return rtcMapRef.current.get(remoteUid);
    const pc = RTCCtor({ iceServers: iceServersRef.current });
    rtcMapRef.current.set(remoteUid, pc);
    pc.onicecandidate = (ev) => {
      if (ev.candidate) {
        try {
          wsRef.current?.send(JSON.stringify({
            type: "ice-candidate",
            target_user_id: remoteUid,
            candidate: ev.candidate,
          }));
        } catch { /* ws closed */ }
      }
    };
    pc.ontrack = (ev) => {
      // Play the remote track through a hidden autoplay <audio>. The
      // browser mixes multiple tracks automatically when we mount
      // multiple audio elements.
      const el = document.createElement("audio");
      el.autoplay = true;
      el.setAttribute("data-testid", `walkie-live-remote-audio-${remoteUid}`);
      el.srcObject = ev.streams?.[0] || new MediaStream([ev.track]);
      audioElsRef.current.set(remoteUid, el);
      document.body.appendChild(el);
    };
    // Add our local mic track (may be muted-until-transmit).
    if (localStreamRef.current) {
      for (const t of localStreamRef.current.getAudioTracks()) {
        try {
          const sender = pc.addTrack(t, localStreamRef.current);
          if (sender) localSenderMapRef.current.set(remoteUid, sender);
        } catch { /* dupe track */ }
      }
    }
    if (initiator) {
      try {
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        wsRef.current?.send(JSON.stringify({
          type: "offer",
          target_user_id: remoteUid,
          sdp: offer.sdp,
        }));
      } catch (e) {
        console.warn("[walkie.live] createOffer failed:", e);
      }
    }
    return pc;
  }, [RTCCtor]);

  const teardownPeer = useCallback((remoteUid) => {
    const pc = rtcMapRef.current.get(remoteUid);
    if (pc) { try { pc.close(); } catch { /* ignore */ } }
    rtcMapRef.current.delete(remoteUid);
    const el = audioElsRef.current.get(remoteUid);
    if (el) { try { el.pause(); el.remove(); } catch { /* ignore */ } }
    audioElsRef.current.delete(remoteUid);
    localSenderMapRef.current.delete(remoteUid);
  }, []);

  // ── Auto-record: MediaRecorder over the local mic stream ─────
  const startRecording = useCallback((stream) => {
    if (recorderRef.current) return;
    try {
      const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"]
        .find((m) => (typeof MediaRecorder === "undefined" || !MediaRecorder.isTypeSupported) ? true : MediaRecorder.isTypeSupported(m))
        || "audio/webm";
      const rec = MediaRecCtor(stream, { mimeType: mime });
      recorderRef.current = rec;
      recorderChunksRef.current = [];
      rec.ondataavailable = (ev) => {
        if (ev?.data && ev.data.size > 0) recorderChunksRef.current.push(ev.data);
      };
      rec.start(1000);
    } catch (e) {
      console.warn("[walkie.live] MediaRecorder init failed:", e);
    }
  }, [MediaRecCtor]);

  const flushRecordingToClip = useCallback(async () => {
    const rec = recorderRef.current;
    const sid = sessionIdRef.current;
    if (!rec || !sid || !channelId) return;
    await new Promise((resolve) => {
      rec.onstop = () => resolve();
      try { rec.stop(); } catch { resolve(); }
    });
    const chunks = recorderChunksRef.current || [];
    recorderChunksRef.current = [];
    recorderRef.current = null;
    if (chunks.length === 0) return;

    const blob = new Blob(chunks, { type: chunks[0]?.type || "audio/webm" });
    const filename = `live-session-${sid}.webm`;
    const fd = new FormData();
    fd.append("channel_id", channelId);
    fd.append("audio", blob, filename);
    fd.append("duration_ms", String(Math.max(1000, blob.size)));
    fd.append("metadata", JSON.stringify({ source: "live_session", session_id: sid }));
    try {
      await api.post("/walkie/messages", fd, { isForm: true });
    } catch (e) {
      console.warn("[walkie.live] upload live clip failed:", e);
    }
  }, [channelId]);

  // ── Boot the panel: fetch ICE, get mic, open WS ─────────────
  useEffect(() => {
    let cancelled = false;
    if (!channelId) return () => { cancelled = true; };
    setStatus("connecting");

    (async () => {
      // 1. ICE config
      try {
        const r = await api.get("/walkie/ice-servers");
        if (Array.isArray(r?.ice_servers) && r.ice_servers.length > 0) {
          iceServersRef.current = r.ice_servers;
        }
      } catch { /* keep static default */ }
      if (cancelled) return;

      // 2. Mic
      let stream;
      try {
        stream = await getUserMediaFn({ audio: true });
      } catch (_micErr) {
        setStatus("error");
        toast.error("Microphone permission required for live channel");
        return;
      }
      if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return; }
      stream.getAudioTracks().forEach((t) => { t.enabled = false; }); // start muted
      localStreamRef.current = stream;
      startRecording(stream);

      // 3. WebSocket
      const url = buildSignalingUrl(channelId, tokenGetter());
      const ws = WSCtor(url);
      wsRef.current = ws;
      ws.onopen = () => setStatus("live");
      ws.onerror = () => setStatus("error");
      ws.onclose = () => setStatus((s) => (s === "closed" ? "closed" : "closed"));
      ws.onmessage = async (ev) => {
        let frame;
        try { frame = JSON.parse(typeof ev.data === "string" ? ev.data : ""); } catch { return; }
        const t = frame?.type;
        if (t === "session-state") {
          sessionIdRef.current = frame.session_id;
          setPeers((frame.roster || []).filter((uid) => uid !== user?.id));
          // Existing peers → we initiate offers.
          for (const uid of frame.roster || []) {
            if (uid !== user?.id) await createPeer(uid, true);
          }
        } else if (t === "peer-joined") {
          setPeers((cur) => (cur.includes(frame.user_id) ? cur : [...cur, frame.user_id]));
          // Newcomer will send us the offer — we just wait.
        } else if (t === "peer-left") {
          setPeers((cur) => cur.filter((u) => u !== frame.user_id));
          teardownPeer(frame.user_id);
        } else if (t === "offer") {
          const pc = await createPeer(frame.from_user_id, false);
          try {
            await pc.setRemoteDescription({ type: "offer", sdp: frame.sdp });
            const answer = await pc.createAnswer();
            await pc.setLocalDescription(answer);
            ws.send(JSON.stringify({ type: "answer", target_user_id: frame.from_user_id, sdp: answer.sdp }));
          } catch (e) { console.warn("[walkie.live] offer handling failed", e); }
        } else if (t === "answer") {
          const pc = rtcMapRef.current.get(frame.from_user_id);
          try { await pc?.setRemoteDescription({ type: "answer", sdp: frame.sdp }); }
          catch (e) { console.warn("[walkie.live] answer handling failed", e); }
        } else if (t === "ice-candidate") {
          const pc = rtcMapRef.current.get(frame.from_user_id);
          try { await pc?.addIceCandidate(frame.candidate); }
          catch (_iceErr) { /* invalid candidate — ignore */ }
        } else if (t === "speaking-update") {
          setSpeakingSet((cur) => {
            const n = new Set(cur);
            if (frame.is_speaking) n.add(frame.user_id); else n.delete(frame.user_id);
            return n;
          });
        } else if (t === "session-ended") {
          await flushRecordingToClip();
          setStatus("closed");
        }
      };
    })();

    return () => {
      cancelled = true;
      // Best-effort teardown — order matters: stop VOX first, then
      // upload recording, then close peers + ws.
      stopVox();
      // eslint-disable-next-line react-hooks/exhaustive-deps
      const rtcMap = rtcMapRef.current;
      (async () => {
        try { await flushRecordingToClip(); } catch { /* ignore */ }
        try { wsRef.current?.send(JSON.stringify({ type: "leave" })); } catch { /* ignore */ }
        try { wsRef.current?.close(); } catch { /* ignore */ }
        for (const uid of Array.from(rtcMap.keys())) teardownPeer(uid);
        try { localStreamRef.current?.getTracks().forEach((t) => t.stop()); } catch { /* ignore */ }
        localStreamRef.current = null;
      })();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelId]);

  // ── Big "Talk" button handlers ────────────────────────────────
  const onTalkDown = useCallback(() => { if (pttMode === "ptt") setTransmit(true); }, [pttMode, setTransmit]);
  const onTalkUp = useCallback(() => { if (pttMode === "ptt") setTransmit(false); }, [pttMode, setTransmit]);

  const statusLabel = useMemo(() => {
    if (status === "connecting") return "Connecting…";
    if (status === "live") return `Live · ${peers.length + 1} on channel`;
    if (status === "closed") return "Session ended";
    if (status === "error") return "Live unavailable";
    return "";
  }, [status, peers.length]);

  return (
    <div className="flex flex-col gap-2 w-full" data-testid="walkie-live-panel">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm">
          <Radio className="h-4 w-4 text-emerald-600" />
          <span data-testid="walkie-live-status" className="font-medium text-slate-700">
            {statusLabel}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-testid="walkie-live-mode-ptt"
            onClick={() => setPttMode("ptt")}
            aria-pressed={pttMode === "ptt"}
            className={`px-2 py-1 rounded text-xs border ${pttMode === "ptt" ? "bg-slate-900 text-white border-slate-900" : "bg-white text-slate-700 border-slate-300"}`}
          >
            PTT
          </button>
          <button
            type="button"
            data-testid="walkie-live-mode-vox"
            onClick={() => setPttMode("vox")}
            aria-pressed={pttMode === "vox"}
            className={`px-2 py-1 rounded text-xs border ${pttMode === "vox" ? "bg-emerald-600 text-white border-emerald-600" : "bg-white text-slate-700 border-slate-300"}`}
          >
            VOX
          </button>
          <button
            type="button"
            data-testid="walkie-live-exit"
            onClick={() => onExit?.()}
            title="Exit live"
            className="h-7 w-7 rounded grid place-items-center text-slate-500 hover:text-slate-900 hover:bg-slate-100"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          data-testid="walkie-live-talk-button"
          disabled={pttMode !== "ptt" || status !== "live"}
          onMouseDown={onTalkDown}
          onMouseUp={onTalkUp}
          onMouseLeave={onTalkUp}
          onTouchStart={(e) => { e.preventDefault(); onTalkDown(); }}
          onTouchEnd={(e) => { e.preventDefault(); onTalkUp(); }}
          className={`px-5 py-3 rounded-full text-sm font-medium flex items-center gap-2 border transition
            ${transmitting
              ? "bg-emerald-600 text-white border-emerald-700"
              : "bg-white text-slate-800 border-slate-300 hover:bg-slate-50"}
            ${pttMode !== "ptt" || status !== "live" ? "opacity-50 cursor-not-allowed" : ""}`}
          aria-pressed={transmitting}
        >
          {transmitting ? <Mic className="h-4 w-4" /> : <MicOff className="h-4 w-4" />}
          {pttMode === "ptt"
            ? (transmitting ? "Transmitting…" : "Hold to talk (Space)")
            : (transmitting ? "VOX transmitting" : "VOX listening")}
        </button>

        <div className="flex items-center gap-1 text-xs text-slate-500" data-testid="walkie-live-vox-indicator">
          {pttMode === "vox"
            ? <Zap className="h-3 w-3 text-emerald-600" />
            : <ZapOff className="h-3 w-3" />}
          <span>{pttMode === "vox" ? "voice-activated" : "push-to-talk"}</span>
        </div>
      </div>

      {peers.length > 0 && (
        <ul className="flex flex-wrap gap-1 text-xs" data-testid="walkie-live-roster">
          {peers.map((uid) => (
            <li
              key={uid}
              data-testid={`walkie-live-peer-${uid}`}
              className={`px-2 py-0.5 rounded-full border text-slate-700 ${speakingSet.has(uid) ? "bg-emerald-100 border-emerald-300 text-emerald-800" : "bg-slate-50 border-slate-200"}`}
            >
              {uid.slice(0, 8)}
              {speakingSet.has(uid) ? " · speaking" : ""}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
