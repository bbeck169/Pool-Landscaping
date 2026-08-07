/**
 * Phase 51c · Feb 2026 — Walkie-Talkie channel timeline (mobile).
 *
 * Message timeline + hold-to-record footer using ``expo-audio``.
 * Mirrors the web ``Walkie.jsx`` right pane: admin gate up-front,
 * auto-play new arrivals in-focus (mute-aware), waveform bars with
 * fallback, 30s hard-cap on the recorder.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useLocalSearchParams, useRouter } from "expo-router";
import {
  RecordingPresets,
  requestRecordingPermissionsAsync,
  useAudioPlayer,
  useAudioRecorder,
  useAudioRecorderState,
} from "expo-audio";

import { api, api_base, getAuthToken } from "@/src/api";
import { colors, spacing, fontSize, radius } from "@/src/theme";
import { EmptyState, Loading } from "@/src/components/ui";
import { Header } from "@/src/components/widgets";
import { useAuth } from "@/src/auth";
import {
  canRecordInChannel,
  extForMime,
  isMuted,
  isOwnMessage,
  setMuted,
  shouldAutoPlay,
} from "@/src/pages/walkie/walkie-helpers";

const POLL_MS = 15_000;
const MAX_RECORD_MS = 30_000;

type Msg = {
  id: string;
  channel_id: string;
  sender_user_id: string;
  sender_name?: string;
  audio_url: string;
  duration_ms: number;
  waveform_peaks?: number[] | null;
  created_at: string;
  listened_at?: string | null;
  autoplay?: boolean;
};

function fmtTime(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function Waveform({ peaks, playing, testID }: { peaks?: number[] | null; playing: boolean; testID?: string }) {
  const list = Array.isArray(peaks) && peaks.length > 0 ? peaks : null;
  if (!list) {
    return (
      <View
        testID={`${testID || "walkie-waveform"}-fallback`}
        style={[wave.fallback, { backgroundColor: playing ? colors.successAlpha || "#86efac" : colors.borderMuted }]}
      />
    );
  }
  return (
    <View testID={testID || "walkie-waveform"} style={wave.row}>
      {list.slice(0, 48).map((p, i) => (
        <View
          key={i}
          style={{
            width: 3,
            marginHorizontal: 1,
            height: Math.max(4, Math.min(22, Number(p) * 22 || 6)),
            backgroundColor: playing ? colors.success : colors.onSurfaceSecondary,
            borderRadius: 2,
          }}
        />
      ))}
    </View>
  );
}

function MessageRow({ msg, user, mutedRef, onListened }: { msg: Msg; user: any; mutedRef: React.MutableRefObject<boolean>; onListened: (id: string) => void }) {
  const own = isOwnMessage(user, msg);
  const url = `${api_base()}${msg.audio_url}`.replace("/api/api/", "/api/");
  const player = useAudioPlayer(url);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    // Fire auto-play only when the message is freshly-arrived,
    // unmuted, and not our own outgoing clip.
    if (!msg.autoplay) return;
    if (!shouldAutoPlay({ user, message: msg, muted: mutedRef.current })) return;
    try {
      player.play?.();
      setPlaying(true);
    } catch { /* silent */ }
  }, [msg.autoplay, msg, user, mutedRef, player]);

  const toggle = () => {
    if (playing) {
      player.pause?.();
      setPlaying(false);
    } else {
      player.play?.();
      setPlaying(true);
    }
  };

  // Fire listened receipt on natural completion (own messages excluded).
  useEffect(() => {
    if (!player) return;
    const status = (player as any).addListener?.("playbackStatusUpdate", (s: any) => {
      if (s?.didJustFinish) {
        setPlaying(false);
        if (!own && !msg.listened_at) {
          api.post(`/walkie/messages/${msg.id}/listened`).then(() => onListened(msg.id)).catch(() => {});
        }
      }
    });
    return () => { try { status?.remove?.(); } catch { /* noop */ } };
  }, [player, own, msg.id, msg.listened_at, onListened]);

  const secs = Math.max(1, Math.round((msg.duration_ms || 0) / 1000));

  return (
    <View
      testID="walkie-message-row"
      style={[styles.msgRow, own && styles.msgRowOwn]}
    >
      <TouchableOpacity onPress={toggle} style={styles.playBtn} testID="walkie-play-btn">
        <Ionicons name={playing ? "pause" : "play"} size={16} color="#fff" />
      </TouchableOpacity>
      <View style={styles.msgBody}>
        <View style={styles.msgMeta}>
          <Text style={styles.msgSender} numberOfLines={1}>
            {msg.sender_name || (own ? "you" : "teammate")}
          </Text>
          {own && <Text style={styles.ownTag} testID="walkie-own-tag">you</Text>}
          <Text style={styles.msgTime}>· {fmtTime(msg.created_at)} · {secs}s</Text>
          {msg.listened_at && !own && (
            <Ionicons name="checkmark-circle" size={12} color={colors.success} testID="walkie-listened-check" />
          )}
        </View>
        <Waveform peaks={msg.waveform_peaks} playing={playing} />
      </View>
    </View>
  );
}

function RecordFooter({ disabled, disabledReason, onSend }: {
  disabled: boolean;
  disabledReason?: string;
  onSend: (opts: { uri: string; duration_ms: number; mime: string }) => Promise<void>;
}) {
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const state = useAudioRecorderState(recorder, 200);
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const startedAt = useRef(0);
  const timerRef = useRef<any>(null);
  const cancelledRef = useRef(false);

  const stop = useCallback(async (cancel = false) => {
    cancelledRef.current = cancel;
    try { await recorder.stop(); } catch { /* noop */ }
    clearInterval(timerRef.current);
    setRecording(false);
    const duration = Math.max(500, Date.now() - startedAt.current);
    setElapsed(0);
    if (cancel) return;
    const uri = recorder.uri;
    if (!uri) return;
    const mime = uri.endsWith(".m4a") ? "audio/mp4" : uri.endsWith(".webm") ? "audio/webm" : "audio/mp4";
    await onSend({ uri, duration_ms: duration, mime });
  }, [recorder, onSend]);

  const start = async () => {
    if (disabled) return;
    try {
      const perm = await requestRecordingPermissionsAsync();
      if (!perm.granted) return;
      cancelledRef.current = false;
      await recorder.prepareToRecordAsync();
      recorder.record();
      startedAt.current = Date.now();
      setRecording(true);
      setElapsed(0);
      timerRef.current = setInterval(() => {
        const e = Date.now() - startedAt.current;
        setElapsed(e);
        if (e >= MAX_RECORD_MS) stop(false);
      }, 100);
    } catch { /* noop */ }
  };

  if (disabled) {
    return (
      <View style={styles.footer}>
        <View style={[styles.recordBtn, styles.recordBtnDisabled]} testID="walkie-record-btn">
          <Ionicons name="mic-off-outline" size={22} color={colors.onSurfaceSecondary} />
        </View>
        <Text style={styles.disabledReason} testID="walkie-record-locked-reason" numberOfLines={2}>
          {disabledReason || "You can't broadcast here"}
        </Text>
      </View>
    );
  }

  return (
    <View style={styles.footer}>
      <Pressable
        onPressIn={start}
        onPressOut={() => stop(false)}
        style={({ pressed }) => [styles.recordBtn, (recording || pressed) && styles.recordBtnActive]}
        testID="walkie-record-btn"
      >
        <Ionicons name="mic-outline" size={28} color="#fff" />
      </Pressable>
      {recording ? (
        <View style={styles.recordMeta} testID="walkie-record-elapsed">
          <Text style={styles.recordTimer}>{(elapsed / 1000).toFixed(1)}s</Text>
          <TouchableOpacity onPress={() => stop(true)} testID="walkie-record-cancel">
            <Text style={styles.cancelLabel}>cancel</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <Text style={styles.footerHint}>Hold to record · max 30s</Text>
      )}
      {state.isRecording && !recording && <ActivityIndicator size="small" />}
    </View>
  );
}

export default function WalkieChannel() {
  const { channelId } = useLocalSearchParams<{ channelId: string }>();
  const router = useRouter();
  const { user } = useAuth();
  const [channel, setChannel] = useState<any>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [loading, setLoading] = useState(true);
  const [muted, setMutedState] = useState(false);
  const mutedRef = useRef(false);
  const seenIdsRef = useRef<Set<string>>(new Set());

  useEffect(() => { (async () => { const v = await isMuted(); setMutedState(v); mutedRef.current = v; })(); }, []);

  const loadChannel = useCallback(async () => {
    try {
      const r = await api.get("/walkie/channels");
      const ch = (r.channels || []).find((c: any) => c.id === channelId);
      setChannel(ch || null);
    } catch { /* silent */ }
  }, [channelId]);

  const loadMessages = useCallback(async ({ markFresh = false } = {}) => {
    if (!channelId) return;
    try {
      const r = await api.get(`/walkie/messages?channel_id=${channelId}`);
      const rows: Msg[] = (r.messages || []).slice().reverse();
      const prev = seenIdsRef.current;
      rows.forEach((m) => { m.autoplay = markFresh && !prev.has(m.id); });
      seenIdsRef.current = new Set(rows.map((m) => m.id));
      setMessages(rows);
    } catch { /* silent */ } finally {
      setLoading(false);
    }
  }, [channelId]);

  useFocusEffect(useCallback(() => {
    setLoading(true);
    seenIdsRef.current = new Set();
    loadChannel();
    loadMessages({ markFresh: false });
    const iv = setInterval(() => { loadChannel(); loadMessages({ markFresh: true }); }, POLL_MS);
    return () => clearInterval(iv);
  }, [loadChannel, loadMessages]));

  const toggleMute = async () => {
    const next = !muted;
    await setMuted(next);
    setMutedState(next);
    mutedRef.current = next;
  };

  const recordGate = canRecordInChannel(user, channel);

  const send = async ({ uri, duration_ms, mime }: { uri: string; duration_ms: number; mime: string }) => {
    const ext = extForMime(mime);
    const fd = new FormData();
    fd.append("channel_id", channelId as string);
    fd.append("duration_ms", String(duration_ms));
    fd.append("audio_file", { uri, name: `clip.${ext}`, type: mime } as any);
    const token = await getAuthToken();
    try {
      const res = await fetch(`${api_base()}/walkie/messages`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      if (res.ok) {
        loadMessages({ markFresh: false });
      }
    } catch { /* silent */ }
  };

  const title = channel?.kind === "all_hands"
    ? "All-Hands"
    : channel?.kind === "department"
      ? `${(channel.department || "").replace(/^\w/, (m: string) => m.toUpperCase())} Team`
      : "Direct";

  return (
    <View style={styles.container} testID="walkie-channel-page">
      <Header
        title={title}
        left={
          <TouchableOpacity onPress={() => router.back()} testID="walkie-back-btn">
            <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
          </TouchableOpacity>
        }
        right={
          <TouchableOpacity onPress={toggleMute} testID="walkie-mute-toggle" accessibilityState={{ selected: muted }}>
            <Ionicons name={muted ? "volume-mute-outline" : "volume-high-outline"} size={22} color={colors.onSurface} />
          </TouchableOpacity>
        }
      />
      <ScrollView contentContainerStyle={styles.body} testID="walkie-timeline">
        {loading ? (
          <Loading />
        ) : messages.length === 0 ? (
          <EmptyState
            icon="radio-outline"
            title="No clips yet"
            subtitle="Hold the mic below to send the first one."
            testID="walkie-empty-messages"
          />
        ) : (
          messages.map((m) => (
            <MessageRow
              key={m.id}
              msg={m}
              user={user}
              mutedRef={mutedRef}
              onListened={(id) => setMessages((cur) => cur.map((x) => x.id === id ? { ...x, listened_at: new Date().toISOString() } : x))}
            />
          ))
        )}
      </ScrollView>
      <RecordFooter
        disabled={!recordGate.allowed}
        disabledReason={recordGate.reason}
        onSend={send}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.surface },
  body: { padding: spacing.md, gap: spacing.sm, paddingBottom: spacing["3xl"] },
  msgRow: {
    flexDirection: "row",
    gap: spacing.sm,
    padding: spacing.sm,
    backgroundColor: colors.surfaceElevated,
    borderRadius: radius.md,
    alignItems: "center",
  },
  msgRowOwn: {
    backgroundColor: colors.surfaceTertiary,
    flexDirection: "row-reverse",
  },
  playBtn: {
    height: 36, width: 36, borderRadius: 999,
    alignItems: "center", justifyContent: "center",
    backgroundColor: colors.onSurface,
  },
  msgBody: { flex: 1, minWidth: 0, gap: 4 },
  msgMeta: { flexDirection: "row", alignItems: "center", gap: 4 },
  msgSender: { fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  msgTime: { fontSize: fontSize.sm, color: colors.onSurfaceSecondary },
  ownTag: {
    fontSize: 10, paddingHorizontal: 4, paddingVertical: 1,
    backgroundColor: colors.borderMuted, color: colors.onSurface,
    borderRadius: 4,
  },
  footer: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    padding: spacing.lg,
    borderTopWidth: 1,
    borderTopColor: colors.borderMuted,
    backgroundColor: colors.surfaceElevated,
  },
  recordBtn: {
    height: 56, width: 56, borderRadius: 999,
    alignItems: "center", justifyContent: "center",
    backgroundColor: colors.onSurface,
  },
  recordBtnActive: { backgroundColor: colors.error },
  recordBtnDisabled: { backgroundColor: colors.borderMuted },
  recordMeta: { flex: 1, flexDirection: "row", gap: spacing.md, alignItems: "center" },
  recordTimer: { color: colors.error, fontWeight: "700", fontSize: fontSize.base },
  cancelLabel: { color: colors.onSurfaceSecondary, fontSize: fontSize.sm, textDecorationLine: "underline" },
  footerHint: { color: colors.onSurfaceSecondary, fontSize: fontSize.sm, flex: 1 },
  disabledReason: { color: colors.onSurfaceSecondary, fontSize: fontSize.sm, flex: 1 },
});

const wave = StyleSheet.create({
  row: { height: 24, flex: 1, flexDirection: "row", alignItems: "center" },
  fallback: { height: 6, flex: 1, borderRadius: 999 },
});
