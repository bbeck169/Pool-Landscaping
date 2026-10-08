/**
 * Feb-2026 · MARCO-AI-CHAT Phase B — continuous "Hey Marco" wake-word hook.
 *
 * Design (per Phase A gate P4):
 *   - Uses the Web Speech API (``window.SpeechRecognition`` /
 *     ``window.webkitSpeechRecognition``). Firefox and Safari <14.5
 *     return ``{ supported: false }`` and the consumer silently skips
 *     mount — no console errors, no mic prompt.
 *   - Continuous recognition with ``interimResults=true`` so the match
 *     fires on partial transcripts (sub-second latency).
 *   - On every interim result, normalise the transcript (lowercase,
 *     strip punctuation, collapse whitespace) and match
 *     ``/\bhey\s+marco\b/``. On match, dispatch a
 *     ``CustomEvent("ai-dock:open-marco")`` on the window and enter a
 *     2 s cooldown so a long "Hey Marco, please..." utterance doesn't
 *     re-fire the event repeatedly.
 *   - Auto-restart on ``onend`` so continuous recognition survives the
 *     ~60 s silence timeout Chrome / Edge impose.
 *   - Request mic permission on mount (one-time). If denied, surface
 *     ``{ supported: true, permitted: false }`` so AppLayout can
 *     render a non-blocking toast.
 */
import React from "react";

const EVENT_OPEN_MARCO = "ai-dock:open-marco";
const WAKE_PATTERN = /\bhey\s+marco\b/;
const COOLDOWN_MS = 2000;

function _getRecognitionCtor() {
  if (typeof window === "undefined") return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function _normalize(text) {
  return String(text || "")
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export default function useWebWakeWord({ enabled = true } = {}) {
  const [supported, setSupported] = React.useState(false);
  const [permitted, setPermitted] = React.useState(null);
  const [listening, setListening] = React.useState(false);
  const [error, setError] = React.useState(null);
  const recognitionRef = React.useRef(null);
  const cooldownUntilRef = React.useRef(0);
  const shouldRunRef = React.useRef(false);

  React.useEffect(() => {
    const Ctor = _getRecognitionCtor();
    if (!Ctor) {
      setSupported(false);
      return undefined;
    }
    setSupported(true);
    if (!enabled) return undefined;

    let cancelled = false;

    const start = () => {
      if (cancelled) return;
      try {
        const rec = new Ctor();
        rec.continuous = true;
        rec.interimResults = true;
        rec.lang = "en-US";
        rec.maxAlternatives = 1;
        rec.onresult = (ev) => {
          const now = Date.now();
          if (now < cooldownUntilRef.current) return;
          const transcripts = [];
          for (let i = ev.resultIndex; i < ev.results.length; i += 1) {
            const r = ev.results[i];
            if (r && r[0]) transcripts.push(r[0].transcript);
          }
          const joined = _normalize(transcripts.join(" "));
          if (WAKE_PATTERN.test(joined)) {
            cooldownUntilRef.current = now + COOLDOWN_MS;
            try {
              window.dispatchEvent(new CustomEvent(EVENT_OPEN_MARCO, {
                detail: { source: "wake-word", transcript: joined },
              }));
            } catch (_e) {
              // swallow — the event is purely best-effort.
            }
          }
        };
        rec.onerror = (ev) => {
          const kind = ev?.error || "unknown";
          if (kind === "not-allowed" || kind === "service-not-allowed") {
            setPermitted(false);
            setError("mic-permission-denied");
            shouldRunRef.current = false;
            setListening(false);
            return;
          }
          if (kind === "no-speech" || kind === "aborted") {
            // Benign — the auto-restart in onend will relaunch.
            return;
          }
          setError(kind);
        };
        rec.onend = () => {
          setListening(false);
          if (!cancelled && shouldRunRef.current) {
            // 300ms stagger — avoids a tight restart loop if the
            // recogniser dies immediately on start.
            setTimeout(() => {
              if (!cancelled && shouldRunRef.current) start();
            }, 300);
          }
        };
        recognitionRef.current = rec;
        shouldRunRef.current = true;
        rec.start();
        setListening(true);
        setPermitted(true);
      } catch (e) {
        setError(String(e?.message || e || "start-failed"));
      }
    };

    start();

    return () => {
      cancelled = true;
      shouldRunRef.current = false;
      const rec = recognitionRef.current;
      if (rec) {
        try { rec.onresult = null; rec.onerror = null; rec.onend = null; }
        catch (_e) { /* noop */ }
        try { rec.stop(); } catch (_e) { /* noop */ }
      }
      recognitionRef.current = null;
      setListening(false);
    };
  }, [enabled]);

  return { supported, listening, permitted, error };
}
