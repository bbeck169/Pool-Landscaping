/**
 * TB-1 · useMarcoWakeWord hook — Phase 8M ARM-ON-CLICK refit.
 *
 * Mobile parity with web ``useWebWakeWord`` (Phase 8):
 *   * Does NOT start on mount.  The listener only runs while
 *     ``isArmed === true``, driven by ``arm()`` / ``disarm()`` /
 *     ``toggle()`` (owned by MarcoMicProvider + MicToggleButton).
 *   * Uses the existing speech primitive (expo-speech-recognition via
 *     ``wakeWordService``) — no new native dependencies.
 *   * ``onPhraseDetected`` fires on every accepted wake event so the
 *     controller can reset its 10-min idle-disarm timer.
 *   * ZERO audible feedback on arm / disarm / detect — no beeps, no
 *     sounds.  (Marco's spoken *answer* on job screens is the existing
 *     voice-command pipeline and is gated by voiceResponseEnabled.)
 *
 * Routing on detection (unchanged):
 *   * job / service-report screens → record → transcribe → execute → TTS.
 *   * any other screen → open the AI chat dock.
 */
import { useEffect, useRef, useCallback, useMemo, useState } from "react";
import { useSegments } from "expo-router";
import {
  useAudioRecorder,
  RecordingPresets,
  getRecordingPermissionsAsync,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
} from "expo-audio";
import * as ExpoSpeech from "expo-speech";

import { getVoiceResponseEnabled } from "@/src/services/marco/voicePreferences";
import {
  startWakeWord,
  stopWakeWord,
  getWakeWordStatus,
  isWakeWordSupported,
} from "@/src/services/marco/wakeWordService";
import {
  transcribeAudio,
  executeMarco,
} from "@/src/services/marco/executeMarco";

const _Speech: any = ExpoSpeech;

const RECORD_DURATION_MS = 8000; // Max 8s recording after wake

export type MarcoWakeWordState = {
  supported: boolean;
  permitted: boolean | null;
  listening: boolean;
  isArmed: boolean;
  arm: () => Promise<void>;
  disarm: () => void;
  toggle: () => void;
};

export function useMarcoWakeWord(
  onOpenDock?: () => void,
  opts?: { onPhraseDetected?: () => void },
): MarcoWakeWordState {
  const segments = useSegments();
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);

  const [supported] = useState<boolean>(() => isWakeWordSupported());
  const [permitted, setPermitted] = useState<boolean | null>(null);
  const [listening, setListening] = useState(false);
  const [isArmed, setIsArmed] = useState(false);
  const armedRef = useRef(false);

  const onDetectedRef = useRef(opts?.onPhraseDetected);
  onDetectedRef.current = opts?.onPhraseDetected;

  const isVoiceCommandScreen = useMemo(() => {
    const path = segments.join("/");
    return path.includes("job/") || path.includes("service-report/");
  }, [segments]);

  const handleWakeDetected = useCallback(async () => {
    try { onDetectedRef.current?.(); } catch { /* caller errors must not kill mic */ }
    if (!isVoiceCommandScreen && onOpenDock) {
      onOpenDock();
      return;
    }
    try {
      const perms = await getRecordingPermissionsAsync();
      if (!perms.granted) {
        const req = await requestRecordingPermissionsAsync();
        if (!req.granted) return;
      }
      await setAudioModeAsync({ playsInSilentMode: true, allowsRecording: true });
      await recorder.prepareToRecordAsync();
      recorder.record();
      await new Promise((r) => setTimeout(r, RECORD_DURATION_MS));
      await recorder.stop();
      const uri = recorder.uri;
      if (!uri) return;
      const transcription = await transcribeAudio(uri);
      if (!transcription.transcript?.trim()) return;
      const result = await executeMarco(transcription.transcript, "job_detail", "");
      const speakText = result.speak || result.message;
      if (speakText && _Speech && (await getVoiceResponseEnabled())) {
        _Speech.speak(speakText, { rate: 0.95, pitch: 1.0, language: "en-US" });
      }
    } catch {
      // Swallow — wake-word pipeline errors shouldn't crash the app
    }
  }, [recorder, isVoiceCommandScreen, onOpenDock]);

  // Latest-ref: the service registers its callback once per start.
  const handleWakeRef = useRef(handleWakeDetected);
  handleWakeRef.current = handleWakeDetected;
  const onWake = useCallback(() => { handleWakeRef.current(); }, []);

  const disarm = useCallback(() => {
    armedRef.current = false;
    setIsArmed(false);
    setListening(false);
    stopWakeWord();
  }, []);

  const arm = useCallback(async () => {
    if (armedRef.current || !isWakeWordSupported()) return;
    armedRef.current = true;
    setIsArmed(true);
    // The explicit click IS the opt-in — skip the stored-preference gate.
    const ok = await startWakeWord(onWake, { requirePrefs: false });
    if (!armedRef.current) {
      // Disarmed while start was in flight — release the mic.
      stopWakeWord();
      return;
    }
    if (!ok) {
      armedRef.current = false;
      setIsArmed(false);
      setListening(false);
      if (getWakeWordStatus() === "unavailable") setPermitted(false);
      return;
    }
    setPermitted(true);
    setListening(true);
  }, [onWake]);

  const toggle = useCallback(() => {
    if (armedRef.current) disarm();
    else arm();
  }, [arm, disarm]);

  // Unmount → release the mic if still armed.
  useEffect(() => () => {
    if (armedRef.current) {
      armedRef.current = false;
      stopWakeWord();
    }
  }, []);

  return { supported, permitted, listening, isArmed, arm, disarm, toggle };
}
