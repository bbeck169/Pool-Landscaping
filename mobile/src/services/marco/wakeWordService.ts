/**
 * TB-1 · Wake-word service — "Hey MARCO" detection via expo-speech-recognition.
 *
 * Uses continuous on-device speech recognition to listen for the
 * wake phrase "hey marco". When detected, fires the MARCO voice
 * command pipeline (same as tapping the MarcoVoiceButton).
 *
 * Foreground-only: starts when app is active, stops on background.
 * Requires:
 *   - expo-speech-recognition (already installed, requires dev-client build)
 *   - wakeWordEnabled = true in AsyncStorage
 *   - voiceResponseEnabled = true (wake without TTS is not useful)
 *
 * Fallback note: Porcupine was evaluated but ruled out — no stock
 * "Hey Marco" keyword file, requires Picovoice Console training,
 * no Expo config plugin, and native asset wiring. This approach uses
 * the same expo-speech-recognition already proven in the Lana AI chat.
 */
import { AppState, type AppStateStatus } from "react-native";
import {
  getVoiceResponseEnabled,
  getWakeWordEnabled,
} from "@/src/services/marco/voicePreferences";

/* ── Dynamic import — safe for Expo Go ─────────────────────────── */
let _speech: any = null;
try {
  _speech = require("expo-speech-recognition");
} catch {
  _speech = null;
}

/* ── Types ─────────────────────────────────────────────────────── */
export type WakeWordStatus = "idle" | "listening" | "detected" | "unavailable" | "disabled";

type WakeCallback = () => void;
type StatusCallback = (status: WakeWordStatus) => void;

/* ── Module State ──────────────────────────────────────────────── */
let _running = false;
let _status: WakeWordStatus = "idle";
let _statusListeners: StatusCallback[] = [];
let _onWake: WakeCallback | null = null;
let _appStateListener: { remove(): void } | null = null;
let _cooldownActive = false;
const COOLDOWN_MS = 5000; // Prevent rapid re-triggers
const WAKE_PHRASES = ["hey marco", "hey, marco", "a marco", "hey marko"];

/* ── Public API ────────────────────────────────────────────────── */

export function getWakeWordStatus(): WakeWordStatus {
  return _status;
}

export function onWakeWordStatusChange(cb: StatusCallback): () => void {
  _statusListeners.push(cb);
  return () => {
    _statusListeners = _statusListeners.filter((l) => l !== cb);
  };
}

function _setStatus(s: WakeWordStatus) {
  if (_status === s) return;
  _status = s;
  _statusListeners.forEach((cb) => {
    try { cb(s); } catch { /* swallow */ }
  });
}

/**
 * Start the wake-word listener.
 * @param onWakeDetected — callback fired when "Hey MARCO" is detected
 * @returns true if started, false if can't start
 */
export async function startWakeWord(onWakeDetected: WakeCallback): Promise<boolean> {
  if (_running) return true;

  // Check prerequisites
  if (!_speech) {
    _setStatus("unavailable");
    return false;
  }

  const [wakeEnabled, ttsEnabled] = await Promise.all([
    getWakeWordEnabled(),
    getVoiceResponseEnabled(),
  ]);

  if (!wakeEnabled || !ttsEnabled) {
    _setStatus("disabled");
    return false;
  }

  // Request speech recognition permissions
  try {
    const { granted } = await _speech.requestPermissionsAsync?.() || { granted: true };
    if (!granted) {
      _setStatus("unavailable");
      return false;
    }
  } catch {
    _setStatus("unavailable");
    return false;
  }

  _onWake = onWakeDetected;
  _running = true;
  _cooldownActive = false;

  // Start listening
  _startListening();

  // AppState listener
  _appStateListener = AppState.addEventListener("change", _handleAppState);

  return true;
}

/** Stop the wake-word listener. */
export function stopWakeWord(): void {
  _running = false;
  _onWake = null;
  try {
    _speech?.stop?.();
  } catch { /* swallow */ }
  if (_appStateListener) {
    _appStateListener.remove();
    _appStateListener = null;
  }
  _setStatus("idle");
}

/** Check if wake-word is currently running */
export function isWakeWordRunning(): boolean {
  return _running;
}

/* ── Internals ─────────────────────────────────────────────────── */

function _startListening() {
  if (!_running || !_speech) return;

  try {
    // Remove any existing listeners to avoid doubles
    try { _speech.removeAllListeners?.("result"); } catch { /* ok */ }
    try { _speech.removeAllListeners?.("end"); } catch { /* ok */ }
    try { _speech.removeAllListeners?.("error"); } catch { /* ok */ }

    _speech.start?.({ lang: "en-US", interimResults: true, continuous: true });

    _speech.addListener?.("result", (ev: any) => {
      const transcript = (ev?.results?.[0]?.transcript || "").toLowerCase().trim();
      if (!transcript || _cooldownActive) return;

      // Check for wake phrase
      const detected = WAKE_PHRASES.some((phrase) => transcript.includes(phrase));
      if (detected) {
        _cooldownActive = true;
        _setStatus("detected");

        // Stop recognition so it doesn't conflict with MARCO recording
        try { _speech.stop?.(); } catch { /* ok */ }

        // Fire the callback
        if (_onWake) {
          try { _onWake(); } catch { /* swallow */ }
        }

        // Restart listening after cooldown
        setTimeout(() => {
          _cooldownActive = false;
          if (_running) {
            _setStatus("listening");
            _startListening();
          }
        }, COOLDOWN_MS);
      }
    });

    // Auto-restart on end (speech recognition stops after silence)
    _speech.addListener?.("end", () => {
      if (_running && !_cooldownActive) {
        // Restart after a short delay
        setTimeout(() => {
          if (_running && !_cooldownActive) {
            _startListening();
          }
        }, 500);
      }
    });

    // On error, retry
    _speech.addListener?.("error", () => {
      if (_running && !_cooldownActive) {
        setTimeout(() => {
          if (_running && !_cooldownActive) {
            _startListening();
          }
        }, 2000);
      }
    });

    _setStatus("listening");
  } catch {
    _setStatus("unavailable");
  }
}

function _handleAppState(state: AppStateStatus) {
  if (!_running) return;

  if (state === "active") {
    // Came to foreground — restart listening
    _startListening();
  } else {
    // Went to background — stop listening
    try { _speech?.stop?.(); } catch { /* ok */ }
    _setStatus("idle");
  }
}
