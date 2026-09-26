/**
 * MarcoVoiceButton — navy floating action button for MARCO voice commands.
 *
 * Tap-to-toggle: first tap starts recording, second tap stops + submits.
 * Auto-stops at 60s. Countdown badge at 45s+.
 *
 * Props:
 *   screen     — "job_detail" | "service_report"
 *   entityId   — job_id or service_report_id (null → disabled/loading)
 */
import React, { useState, useRef, useEffect, useCallback } from "react";
import {
  View,
  Text,
  Pressable,
  StyleSheet,
  Animated,
  Alert,
  Linking,
  ActivityIndicator,
  Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import {
  useAudioRecorder,
  RecordingPresets,
  requestRecordingPermissionsAsync,
  getRecordingPermissionsAsync,
} from "expo-audio";
import { useToast } from "@/src/components/ToastProvider";
import {
  transcribeAudio,
  executeMarco,
  MarcoError,
  type MarcoScreen,
} from "@/src/services/marco/executeMarco";
import { colors, radius, font, fontSize } from "@/src/theme";

/* ── constants ─────────────────────────────────────────────────── */
const MAX_DURATION_S = 60;
const COUNTDOWN_START_S = 45;

type Phase = "idle" | "recording" | "processing";

/* ── component ─────────────────────────────────────────────────── */
export default function MarcoVoiceButton({
  screen,
  entityId,
}: {
  screen: MarcoScreen;
  entityId: string | null;
}) {
  const { showToast } = useToast();
  const [phase, setPhase] = useState<Phase>("idle");
  const [elapsed, setElapsed] = useState(0);
  const pulseAnim = useRef(new Animated.Value(1)).current;
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);

  /* ── pulse animation during recording ────────────────────────── */
  useEffect(() => {
    if (phase === "recording") {
      const loop = Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, { toValue: 1.08, duration: 400, useNativeDriver: true }),
          Animated.timing(pulseAnim, { toValue: 1, duration: 400, useNativeDriver: true }),
        ]),
      );
      loop.start();
      return () => loop.stop();
    } else {
      pulseAnim.setValue(1);
    }
  }, [phase, pulseAnim]);

  /* ── elapsed timer during recording ──────────────────────────── */
  useEffect(() => {
    if (phase === "recording") {
      setElapsed(0);
      timerRef.current = setInterval(() => {
        setElapsed((p) => p + 1);
      }, 1000);
      return () => {
        if (timerRef.current) clearInterval(timerRef.current);
      };
    }
  }, [phase]);

  /* ── auto-stop at MAX_DURATION_S ─────────────────────────────── */
  useEffect(() => {
    if (phase === "recording" && elapsed >= MAX_DURATION_S) {
      handleStopAndSubmit();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [elapsed, phase]);

  /* ── permission check ────────────────────────────────────────── */
  const ensureMicPermission = useCallback(async (): Promise<boolean> => {
    try {
      const current = await getRecordingPermissionsAsync();
      if (current.granted) return true;

      const result = await requestRecordingPermissionsAsync();
      if (result.granted) return true;

      if (!result.canAskAgain) {
        Alert.alert(
          "Microphone access required",
          "MARCO needs microphone access to hear your voice commands. Please enable it in Settings.",
          [
            { text: "Cancel", style: "cancel" },
            { text: "Open Settings", onPress: () => Linking.openSettings() },
          ],
        );
      }
      return false;
    } catch {
      return false;
    }
  }, []);

  /* ── start recording ─────────────────────────────────────────── */
  const handleStartRecording = useCallback(async () => {
    const ok = await ensureMicPermission();
    if (!ok) return;
    try {
      recorder.record();
      setPhase("recording");
    } catch {
      showToast("Could not start recording.", "error");
    }
  }, [ensureMicPermission, recorder, showToast]);

  /* ── stop + submit pipeline ──────────────────────────────────── */
  const handleStopAndSubmit = useCallback(async () => {
    if (phase !== "recording") return;
    setPhase("processing");
    if (timerRef.current) clearInterval(timerRef.current);

    try {
      await recorder.stop();
      const uri = recorder.uri;
      if (!uri) {
        showToast("No audio recorded. Tap and speak, then tap again.", "error", 5000);
        setPhase("idle");
        return;
      }

      // Step 1: Transcribe
      const transcription = await transcribeAudio(uri);
      if (!transcription.transcript?.trim()) {
        showToast("MARCO couldn't hear anything. Try again.", "error", 5000);
        setPhase("idle");
        return;
      }

      // Step 2: Execute
      const result = await executeMarco(transcription.transcript, screen, entityId!);
      if (result.ok) {
        showToast(`MARCO · ${result.message}`, "success", 3000);
      } else {
        showToast(`MARCO couldn't do that. ${result.message}`, "error", 5000);
      }
    } catch (e: any) {
      if (e instanceof MarcoError) {
        showToast(e.message, "error", 5000);
      } else {
        showToast("MARCO connection issue. Try again.", "error", 5000);
      }
    } finally {
      setPhase("idle");
    }
  }, [phase, recorder, screen, entityId, showToast]);

  /* ── tap handler ─────────────────────────────────────────────── */
  const handlePress = useCallback(() => {
    if (!entityId) return;
    if (phase === "idle") {
      handleStartRecording();
    } else if (phase === "recording") {
      handleStopAndSubmit();
    }
    // processing: ignore taps
  }, [phase, entityId, handleStartRecording, handleStopAndSubmit]);

  /* ── countdown ───────────────────────────────────────────────── */
  const remaining = MAX_DURATION_S - elapsed;
  const showCountdown = phase === "recording" && elapsed >= COUNTDOWN_START_S;

  /* ── disabled? ───────────────────────────────────────────────── */
  const disabled = !entityId || phase === "processing";

  /* ── render ──────────────────────────────────────────────────── */
  return (
    <View style={styles.wrap} pointerEvents="box-none" testID="marco-fab-wrap">
      {showCountdown && (
        <View style={styles.countdownBadge} testID="marco-countdown-badge">
          <Text style={styles.countdownText}>{remaining}s</Text>
        </View>
      )}
      <Animated.View style={{ transform: [{ scale: pulseAnim }] }}>
        <Pressable
          style={[
            styles.fab,
            phase === "recording" && styles.fabRecording,
            disabled && styles.fabDisabled,
          ]}
          onPress={handlePress}
          disabled={disabled}
          hitSlop={12}
          testID="marco-voice-btn"
          accessibilityLabel={
            phase === "idle"
              ? "MARCO voice command"
              : phase === "recording"
                ? "Stop recording"
                : "Processing voice command"
          }
          accessibilityRole="button"
        >
          {phase === "processing" ? (
            <ActivityIndicator size="small" color="#fff" testID="marco-spinner" />
          ) : (
            <Ionicons
              name={phase === "recording" ? "stop" : "mic"}
              size={26}
              color="#fff"
              testID="marco-mic-icon"
            />
          )}
        </Pressable>
      </Animated.View>
    </View>
  );
}

/* ── styles ────────────────────────────────────────────────────── */
const styles = StyleSheet.create({
  wrap: {
    position: "absolute",
    bottom: 24,
    right: 20,
    zIndex: 100,
    alignItems: "center",
  },
  fab: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.arNavy,
    alignItems: "center",
    justifyContent: "center",
    ...Platform.select({
      ios: {
        shadowColor: colors.arBlue,
        shadowOffset: { width: 0, height: 0 },
        shadowOpacity: 0.3,
        shadowRadius: 8,
      },
      android: { elevation: 6 },
      default: {},
    }),
  },
  fabRecording: {
    backgroundColor: "#DC2626",
    ...Platform.select({
      ios: {
        shadowColor: "#DC2626",
        shadowOpacity: 0.5,
        shadowRadius: 12,
      },
      android: { elevation: 8 },
      default: {},
    }),
  },
  fabDisabled: {
    opacity: 0.45,
  },
  countdownBadge: {
    position: "absolute",
    top: -24,
    backgroundColor: "rgba(0,0,0,0.75)",
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: radius.pill,
    marginBottom: 4,
  },
  countdownText: {
    fontFamily: font.bold,
    fontSize: fontSize.sm,
    color: "#FCA5A5",
  },
});
