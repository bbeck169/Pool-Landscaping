/**
 * Phase 52.1c · Feb-2026 — Mobile walkie live-streaming client.
 *
 * Mirrors ``frontend/src/pages/walkie/LivePanel.jsx`` for the Expo
 * app. Signaling flows through the Phase 52.1a WebSocket; media flows
 * P2P via ``react-native-webrtc`` (STUN today, TURN in Phase 52.1d).
 *
 * ── Product decisions locked (matches web 52.1b) ────────────────────
 *   • PTT default. Big "Hold to talk" button (onPressIn/onPressOut).
 *   • Multi-speaker mixing: every peer's remote track auto-plays on
 *     iOS/Android via ``RTCPeerConnection.ontrack`` — the OS mixer
 *     handles multiple concurrent audio sinks.
 *   • Auto-record active session via ``expo-audio`` running in
 *     parallel with the RTC session (records the LOCAL mic). On
 *     session end, upload to ``POST /api/walkie/messages`` with
 *     ``metadata: {source: "live_session", session_id}``.
 *
 * ── VOX deferred (documented decision) ─────────────────────────────
 *   ``react-native-webrtc`` does NOT expose a WebAudio-equivalent
 *   AnalyserNode. VOX would require either:
 *     a. Native energy metering via ``expo-audio``'s
 *        ``recording.getStatus().metering`` on a parallel recorder,
 *        adding CPU + battery cost; or
 *     b. A native VAD module (not available in Expo Go).
 *   Locked user decision #1 permitted user-selectable PTT/VOX; user
 *   picked "PTT default, VOX optional". Mobile ships PTT-only in
 *   52.1c to avoid a native module + battery hit; VOX moves to a
 *   Phase 52.1e follow-up. The VOX toggle is intentionally disabled
 *   with an "on desktop" hint.
 *
 * ── Android foreground service ─────────────────────────────────────
 *   Android 14+ requires ``FOREGROUND_SERVICE_MICROPHONE`` for mic
 *   access with the app backgrounded. Permission added to app.json;
 *   this component keeps the RTCPeerConnection + recorder alive
 *   while the panel is mounted (foregrounded). Full background-mic
 *   support (screen-off) needs a native module — deferred to 52.1e.
 *   For the current UX, users hold the phone during a live session
 *   (PTT flow) so foregrounded is the expected state.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import AsyncStorage from "@react-native-async-storage/async-storage";
import {
  RecordingPresets,
  requestRecordingPermissionsAsync,
  useAudioRecorder,
} from "expo-audio";

import { api, api_base, getAuthToken } from "@/src/api";
import { colors, spacing, fontSize, radius, font } from "@/src/theme";

// react-native-webrtc: imported lazily so the jest mock can catch it.
import {
  RTCPeerConnection,
  RTCIceCandidate,
  RTCSessionDescription,
  mediaDevices,
} from "react-native-webrtc";

/* ═══════════════════════════════════════════════════════════════════
 * AsyncStorage keys
 * ═══════════════════════════════════════════════════════════════════ */
export function liveModeKey(channelId: string): string { return `walkie_live_mode_${channelId}`; }
export function pttModeKey(channelId: string): string { return `walkie_ptt_mode_${channelId}`; }

/* ═══════════════════════════════════════════════════════════════════
 * Signaling URL builder — mirrors LivePanel.jsx buildSignalingUrl.
 * ═══════════════════════════════════════════════════════════════════ */
export function buildSignalingUrl(channelId: string, token: string): string {
  const raw = typeof api_base === "function" ? api_base() : String(api_base || "");
  const httpBase = String(raw).replace(/\/?api\/?$/i, "");
  const wsBase = httpBase.replace(/^http/i, "ws");
  return `${wsBase}/api/ws/walkie/${channelId}?token=${encodeURIComponent(token || "")}`;
}

/* ═══════════════════════════════════════════════════════════════════
 * Live panel component
 * ═══════════════════════════════════════════════════════════════════ */
type Channel = { id: string; kind?: string; supports_live?: boolean };
type User = { id: string; role?: string };
type Factories = {
  _wsFactory?: (url: string) => WebSocket;
  _rtcFactory?: (cfg: any) => any;
  _getUserMedia?: (c: any) => Promise<any>;
  _tokenGetter?: () => Promise<string> | string;
  _recorderOverride?: any;
};

export default function LivePanel({
  channel,
  user,
  onExit,
  ..._factories
}: { channel: Channel; user: User; onExit?: () => void } & Factories) {
  const {
    _wsFactory,
    _rtcFactory,
    _getUserMedia,
    _tokenGetter,
    _recorderOverride,
  } = _factories;
  const channelId = channel?.id;

  const [status, setStatus] = useState<"idle" | "connecting" | "live" | "closed" | "error">("idle");
  const [transmitting, setTransmitting] = useState(false);
  const [peers, setPeers] = useState<string[]>([]);
  const [speakingSet, setSpeakingSet] = useState<Set<string>>(new Set());

  const wsRef = useRef<WebSocket | null>(null);
  const localStreamRef = useRef<any>(null);
  const rtcMapRef = useRef<Map<string, any>>(new Map());
  const sessionIdRef = useRef<string | null>(null);
  const iceServersRef = useRef<any[]>([{ urls: "stun:stun.l.google.com:19302" }]);

  // Parallel audio recorder for auto-record clip.
  const recorderDefault = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const recorder = _recorderOverride || recorderDefault;
  const recordingRef = useRef(false);

  const WSCtor = _wsFactory || ((url: string) => new WebSocket(url));
  const RTCCtor = useMemo(() => _rtcFactory || ((cfg: any) => new RTCPeerConnection(cfg)), [_rtcFactory]);
  const getUserMediaFn = _getUserMedia || (async (constraints: any) => mediaDevices.getUserMedia(constraints));
  const tokenGetter = _tokenGetter || (async () => (await getAuthToken()) || "");

  const setTransmit = useCallback((on: boolean) => {
    const s = localStreamRef.current;
    if (s) {
      const tracks = typeof s.getAudioTracks === "function" ? s.getAudioTracks() : [];
      for (const t of tracks) t.enabled = !!on;
    }
    setTransmitting(!!on);
    try { wsRef.current?.send(JSON.stringify({ type: "speaking", is_speaking: !!on })); } catch { /* ignore */ }
  }, []);

  const createPeer = useCallback(async (remoteUid: string, initiator: boolean) => {
    if (rtcMapRef.current.has(remoteUid)) return rtcMapRef.current.get(remoteUid);
    const pc = RTCCtor({ iceServers: iceServersRef.current });
    rtcMapRef.current.set(remoteUid, pc);
    pc.onicecandidate = (ev: any) => {
      if (ev?.candidate) {
        try {
          wsRef.current?.send(JSON.stringify({
            type: "ice-candidate",
            target_user_id: remoteUid,
            candidate: ev.candidate,
          }));
        } catch { /* ignore */ }
      }
    };
    // ontrack fires when the remote peer's audio arrives — RN-WebRTC
    // wires it into the OS audio session; the OS mixer handles
    // multiple concurrent tracks without any per-peer <audio> element.
    pc.ontrack = () => { /* remote audio auto-routes via native audio session */ };
    if (localStreamRef.current) {
      const tracks = typeof localStreamRef.current.getAudioTracks === "function"
        ? localStreamRef.current.getAudioTracks() : [];
      for (const t of tracks) {
        try { pc.addTrack(t, localStreamRef.current); } catch { /* dupe */ }
      }
    }
    if (initiator) {
      try {
        const offer = await pc.createOffer({});
        await pc.setLocalDescription(offer);
        wsRef.current?.send(JSON.stringify({
          type: "offer",
          target_user_id: remoteUid,
          sdp: offer.sdp,
        }));
      } catch (e) { /* offer failed — ignore */ }
    }
    return pc;
  }, [RTCCtor]);

  const teardownPeer = useCallback((remoteUid: string) => {
    const pc = rtcMapRef.current.get(remoteUid);
    if (pc) { try { pc.close(); } catch { /* ignore */ } }
    rtcMapRef.current.delete(remoteUid);
  }, []);

  // ── Auto-record: start expo-audio recorder alongside RTC ────────
  const startRecording = useCallback(async () => {
    if (recordingRef.current) return;
    try {
      const perm = await requestRecordingPermissionsAsync();
      if (!perm?.granted) return;
      await recorder.prepareToRecordAsync?.();
      recorder.record?.();
      recordingRef.current = true;
    } catch { /* recorder init failed — silent */ }
  }, [recorder]);

  const flushRecordingToClip = useCallback(async () => {
    if (!recordingRef.current) return;
    recordingRef.current = false;
    try { await recorder.stop?.(); } catch { /* ignore */ }
    const uri: string | undefined = recorder.uri;
    const sid = sessionIdRef.current;
    if (!uri || !sid || !channelId) return;
    const mime = uri.endsWith(".m4a") ? "audio/mp4"
              : uri.endsWith(".webm") ? "audio/webm"
              : "audio/mp4";
    const ext = mime === "audio/webm" ? "webm" : "m4a";
    const fd = new FormData();
    fd.append("channel_id", channelId);
    fd.append("duration_ms", String(1000));
    fd.append("metadata", JSON.stringify({ source: "live_session", session_id: sid }));
    // @ts-expect-error RN FormData accepts { uri, name, type }
    fd.append("audio_file", { uri, name: `live-session-${sid}.${ext}`, type: mime });
    const token = await tokenGetter();
    try {
      await fetch(`${typeof api_base === "function" ? api_base() : api_base}/walkie/messages`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd as any,
      });
    } catch { /* upload failed — silent (24h retry not implemented for MVP) */ }
  }, [recorder, channelId, tokenGetter]);

  // ── Boot ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!channelId) return;
    let cancelled = false;
    setStatus("connecting");

    (async () => {
      try {
        const r = await api.get("/walkie/ice-servers");
        if (Array.isArray(r?.ice_servers) && r.ice_servers.length > 0) {
          iceServersRef.current = r.ice_servers;
        }
      } catch { /* keep static default */ }
      if (cancelled) return;

      let stream: any;
      try {
        stream = await getUserMediaFn({ audio: true });
      } catch {
        setStatus("error");
        return;
      }
      if (cancelled) {
        try { stream?.getTracks?.().forEach((t: any) => t.stop?.()); } catch { /* ignore */ }
        return;
      }
      // Start muted; PTT press flips enabled=true.
      const tracks = typeof stream.getAudioTracks === "function" ? stream.getAudioTracks() : [];
      for (const t of tracks) t.enabled = false;
      localStreamRef.current = stream;
      startRecording();

      const token = await tokenGetter();
      const ws = WSCtor(buildSignalingUrl(channelId, token));
      wsRef.current = ws;
      ws.onopen = () => setStatus("live");
      ws.onerror = () => setStatus("error");
      ws.onclose = () => setStatus((s) => (s === "closed" ? "closed" : "closed"));
      ws.onmessage = async (ev: any) => {
        let frame: any;
        try { frame = JSON.parse(typeof ev.data === "string" ? ev.data : ""); } catch { return; }
        const t = frame?.type;
        if (t === "session-state") {
          sessionIdRef.current = frame.session_id;
          setPeers((frame.roster || []).filter((uid: string) => uid !== user?.id));
          for (const uid of frame.roster || []) {
            if (uid !== user?.id) await createPeer(uid, true);
          }
        } else if (t === "peer-joined") {
          setPeers((cur) => cur.includes(frame.user_id) ? cur : [...cur, frame.user_id]);
        } else if (t === "peer-left") {
          setPeers((cur) => cur.filter((u) => u !== frame.user_id));
          teardownPeer(frame.user_id);
        } else if (t === "offer") {
          const pc = await createPeer(frame.from_user_id, false);
          try {
            await pc.setRemoteDescription(new RTCSessionDescription({ type: "offer", sdp: frame.sdp }));
            const answer = await pc.createAnswer();
            await pc.setLocalDescription(answer);
            ws.send(JSON.stringify({ type: "answer", target_user_id: frame.from_user_id, sdp: answer.sdp }));
          } catch { /* offer handling failed */ }
        } else if (t === "answer") {
          const pc = rtcMapRef.current.get(frame.from_user_id);
          try { await pc?.setRemoteDescription(new RTCSessionDescription({ type: "answer", sdp: frame.sdp })); }
          catch { /* ignore */ }
        } else if (t === "ice-candidate") {
          const pc = rtcMapRef.current.get(frame.from_user_id);
          try { await pc?.addIceCandidate(new RTCIceCandidate(frame.candidate)); } catch { /* ignore */ }
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
      const rtcMap = rtcMapRef.current;
      (async () => {
        try { await flushRecordingToClip(); } catch { /* ignore */ }
        try { wsRef.current?.send(JSON.stringify({ type: "leave" })); } catch { /* ignore */ }
        try { wsRef.current?.close(); } catch { /* ignore */ }
        for (const uid of Array.from(rtcMap.keys())) teardownPeer(uid);
        try { localStreamRef.current?.getTracks?.().forEach((t: any) => t.stop?.()); } catch { /* ignore */ }
        localStreamRef.current = null;
      })();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelId]);

  // ── Persist PTT-mode (always "ptt" on mobile in 52.1c) ──────────
  useEffect(() => {
    if (!channelId) return;
    AsyncStorage.setItem(pttModeKey(channelId), "ptt").catch(() => { /* ignore */ });
  }, [channelId]);

  // ── UI ──────────────────────────────────────────────────────────
  const statusLabel = status === "connecting" ? "Connecting…"
    : status === "live" ? `Live · ${peers.length + 1} on channel`
    : status === "closed" ? "Session ended"
    : status === "error" ? "Live unavailable"
    : "";

  return (
    <View style={styles.panel} testID="walkie-live-panel">
      <View style={styles.header}>
        <View style={styles.headerLeft}>
          <Ionicons name="radio" size={16} color={colors.success || "#16A34A"} />
          <Text style={styles.statusText} testID="walkie-live-status">{statusLabel}</Text>
        </View>
        <View style={styles.headerRight}>
          <View style={[styles.modeChip, styles.modeChipActive]}>
            <Text style={styles.modeChipTextActive}>PTT</Text>
          </View>
          <TouchableOpacity
            testID="walkie-live-mode-vox-disabled"
            disabled
            style={[styles.modeChip, styles.modeChipDisabled]}
            accessibilityLabel="VOX voice-activated mode is desktop-only in 52.1c"
          >
            <Text style={styles.modeChipTextDisabled}>VOX</Text>
          </TouchableOpacity>
          <TouchableOpacity testID="walkie-live-exit" onPress={onExit} style={styles.exitBtn}>
            <Ionicons name="close" size={16} color={colors.onSurfaceSecondary} />
          </TouchableOpacity>
        </View>
      </View>

      <View style={styles.talkRow}>
        <Pressable
          testID="walkie-live-talk-button"
          disabled={status !== "live"}
          onPressIn={() => setTransmit(true)}
          onPressOut={() => setTransmit(false)}
          style={({ pressed }) => [
            styles.talkBtn,
            (transmitting || pressed) && styles.talkBtnActive,
            status !== "live" && styles.talkBtnDisabled,
          ]}
          accessibilityRole="button"
          accessibilityState={{ selected: transmitting, disabled: status !== "live" }}
        >
          <Ionicons name={transmitting ? "mic" : "mic-off"} size={18} color={transmitting ? "#fff" : colors.onSurface} />
          <Text style={[styles.talkLabel, transmitting && styles.talkLabelActive]} testID="walkie-live-talk-label">
            {transmitting ? "Transmitting…" : "Hold to talk"}
          </Text>
        </Pressable>
        <Text style={styles.voxHint}>push-to-talk</Text>
      </View>

      {peers.length > 0 && (
        <View style={styles.roster} testID="walkie-live-roster">
          {peers.map((uid) => (
            <View
              key={uid}
              testID={`walkie-live-peer-${uid}`}
              style={[styles.peerChip, speakingSet.has(uid) && styles.peerChipSpeaking]}
            >
              <Text style={[styles.peerChipText, speakingSet.has(uid) && styles.peerChipTextSpeaking]}>
                {uid.slice(0, 8)}{speakingSet.has(uid) ? " · speaking" : ""}
              </Text>
            </View>
          ))}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    padding: spacing.md,
    gap: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.borderMuted,
    backgroundColor: colors.surfaceElevated,
  },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  headerLeft: { flexDirection: "row", alignItems: "center", gap: 6 },
  headerRight: { flexDirection: "row", alignItems: "center", gap: 6 },
  statusText: { fontFamily: font?.semibold || undefined, fontSize: fontSize.sm, color: colors.onSurface },
  modeChip: {
    paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill || 999,
    borderWidth: 1, borderColor: colors.borderMuted,
  },
  modeChipActive: { backgroundColor: colors.onSurface, borderColor: colors.onSurface },
  modeChipDisabled: { opacity: 0.5 },
  modeChipTextActive: { color: "#fff", fontSize: 11, fontWeight: "700" },
  modeChipTextDisabled: { color: colors.onSurfaceSecondary, fontSize: 11, fontWeight: "600" },
  exitBtn: { padding: 6 },
  talkRow: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  talkBtn: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    borderRadius: radius.pill || 999,
    borderWidth: 1, borderColor: colors.borderMuted,
    backgroundColor: colors.surface,
  },
  talkBtnActive: { backgroundColor: colors.success || "#16A34A", borderColor: colors.success || "#16A34A" },
  talkBtnDisabled: { opacity: 0.5 },
  talkLabel: { fontSize: fontSize.sm, color: colors.onSurface, fontWeight: "600" },
  talkLabelActive: { color: "#fff" },
  voxHint: { fontSize: fontSize.xs || 11, color: colors.onSurfaceSecondary, flex: 1 },
  roster: { flexDirection: "row", flexWrap: "wrap", gap: 4 },
  peerChip: {
    paddingHorizontal: 8, paddingVertical: 2,
    borderRadius: radius.pill || 999,
    borderWidth: 1, borderColor: colors.borderMuted,
    backgroundColor: colors.surface,
  },
  peerChipSpeaking: {
    backgroundColor: (colors as any).successAlpha || "#DCFCE7",
    borderColor: colors.success || "#16A34A",
  },
  peerChipText: { fontSize: 11, color: colors.onSurface },
  peerChipTextSpeaking: { color: colors.success || "#16A34A", fontWeight: "700" },
});
