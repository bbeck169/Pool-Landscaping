/**
 * TB-1 · useMarcoWakeWord hook
 *
 * Starts the wake-word listener when the user is a tech and
 * wakeWordEnabled + voiceResponseEnabled are both true.
 *
 * On wake detection, triggers the existing MARCO voice pipeline
 * (record → transcribe → execute → TTS).
 *
 * Mount this in the root layout alongside useFleetEmitter.
 */
import { useEffect, useRef, useCallback, useMemo } from "react";
import { useSegments } from "expo-router";
import {
  useAudioRecorder,
  RecordingPresets,
  getRecordingPermissionsAsync,
  requestRecordingPermissionsAsync,
} from "expo-audio";
import * as ExpoSpeech from "expo-speech";

import { useAuth } from "@/src/auth";
import {
  getWakeWordEnabled,
  getVoiceResponseEnabled,
} from "@/src/services/marco/voicePreferences";
import {
  startWakeWord,
  stopWakeWord,
  isWakeWordRunning,
} from "@/src/services/marco/wakeWordService";
import {
  transcribeAudio,
  executeMarco,
} from "@/src/services/marco/executeMarco";

/* ── TTS ─────────────────────────────────────────────────────────── */
const _Speech: any = ExpoSpeech;

const RECORD_DURATION_MS = 8000; // Max 8s recording after wake

export function useMarcoWakeWord(onOpenDock?: () => void) {
  const { user } = useAuth();
  const startedRef = useRef(false);
  const segments = useSegments();

  // We need a recorder for the wake-triggered flow
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);

  // MARCO-AI-CHAT Phase B — determine if we're on a voice-command screen
  // (job/service) or a general screen where wake-word should open the dock.
  const isVoiceCommandScreen = useMemo(() => {
    const path = segments.join("/");
    return path.includes("job/") || path.includes("service-report/");
  }, [segments]);

  const handleWakeDetected = useCallback(async () => {
    // Option A: on a job/service screen, fire the voice-command pipeline.
    // On any other screen, open the AI chat dock.
    if (!isVoiceCommandScreen && onOpenDock) {
      onOpenDock();
      return;
    }
    // Wake-word detected — start the MARCO voice pipeline
    try {
      // 1. Check mic permission
      const perms = await getRecordingPermissionsAsync();
      if (!perms.granted) {
        const req = await requestRecordingPermissionsAsync();
        if (!req.granted) return;
      }

      // 2. Record for a fixed duration
      await recorder.prepareToRecordAsync();
      recorder.record();

      // 3. Stop after RECORD_DURATION_MS
      await new Promise((r) => setTimeout(r, RECORD_DURATION_MS));
      await recorder.stop();

      const uri = recorder.uri;
      if (!uri) return;

      // 4. Transcribe
      const transcription = await transcribeAudio(uri);
      if (!transcription.transcript?.trim()) return;

      // 5. Execute — we don't have a specific screen/entity context
      // from wake-word, so use "job_detail" with empty entity
      // The backend handles missing entity_id gracefully
      const result = await executeMarco(transcription.transcript, "job_detail", "");

      // 6. Speak the response
      const speakText = result.speak || result.message;
      if (speakText && _Speech) {
        const ttsEnabled = await getVoiceResponseEnabled();
        if (ttsEnabled) {
          _Speech.speak(speakText, {
            rate: 0.95,
            pitch: 1.0,
            language: "en-US",
          });
        }
      }
    } catch {
      // Swallow — wake-word pipeline errors shouldn't crash the app
    }
  }, [recorder, isVoiceCommandScreen, onOpenDock]);

  // Latest-ref: the wake service registers its callback once, so hand it a
  // stable wrapper that always calls the current (route-aware) handler.
  const handleWakeRef = useRef(handleWakeDetected);
  handleWakeRef.current = handleWakeDetected;
  const onWake = useCallback(() => handleWakeRef.current(), []);

  useEffect(() => {
    if (!user) {
      if (startedRef.current) {
        stopWakeWord();
        startedRef.current = false;
      }
      return;
    }

    const role = (user.role || "") as string;
    const isTech = role === "technician" || role === "tech";

    if (!isTech) {
      if (startedRef.current) {
        stopWakeWord();
        startedRef.current = false;
      }
      return;
    }

    const init = async () => {
      const [wakeEnabled, ttsEnabled] = await Promise.all([
        getWakeWordEnabled(),
        getVoiceResponseEnabled(),
      ]);
      if (!wakeEnabled || !ttsEnabled) return;

      if (!isWakeWordRunning()) {
        const ok = await startWakeWord(onWake);
        if (ok) startedRef.current = true;
      }
    };

    init().catch(() => {});

    return () => {
      // Don't stop on unmount since this is root-level
    };
  }, [user, onWake]);
}
