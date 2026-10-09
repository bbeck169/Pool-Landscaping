/**
 * Feb-2026 · MARCO-AI-CHAT Phase B · Phase 8 refit (Feb-2026).
 *
 * "Hey Marco" wake-word hook — ARM-ON-CLICK, idle until the user
 * explicitly flips ``isArmed=true`` via ``arm()`` / ``toggle()``.
 *
 * Pre-Phase-8 behaviour: hook auto-started SpeechRecognition on
 * mount (gated by ``{ enabled }``), causing continuous background
 * mic activity.  Phase 8 replaces that with an opt-in model —
 * recognition only runs when ``isArmed === true``.  The caller
 * owns the mic button that drives arming.
 *
 * Preserved from Phase B:
 *   * Uses ``window.SpeechRecognition`` / ``webkitSpeechRecognition``.
 *     Firefox + Safari <14.5 return ``supported: false`` and arming
 *     is a no-op there (``useTypedWakePhrase`` is the fallback path).
 *   * Continuous recognition with ``interimResults=true`` so a sub-
 *     second partial transcript can match.
 *   * ``/\bhey\s+marco\b/`` on a normalised transcript — same regex,
 *     same ``ai-dock:open-marco`` CustomEvent, same 2 s cooldown.
 *   * Auto-restart on ``onend`` so Chrome / Edge's 60 s silence
 *     timeout doesn't drop the listener while armed.
 *
 * NEW (Phase 8):
 *   * ``isArmed`` boolean + ``arm()`` / ``disarm()`` / ``toggle()``.
 *   * No ``useEffect`` auto-start.  The effect only wires up the
 *     recogniser; actual ``rec.start()`` is driven by ``isArmed``.
 *   * ``onPhraseDetected`` callback prop so the controller can
 *     reset the idle-disarm timer on each wake-word event WITHOUT
 *     re-adding a window event listener.
 *
 * Still ZERO audible feedback — the hook has no ``new Audio``,
 * no ``AudioContext``, no beeps.  Visual state is the only UX
 * signal, which is what Phase 8 enforces.
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


/**
 * @param {{ onPhraseDetected?: () => void }} [opts]
 *   ``onPhraseDetected`` fires every time a 'hey marco' match is
 *   accepted (post-cooldown).  Used by the Phase 8 controller to
 *   reset its 10-min idle-disarm timer.  Optional.
 *
 * @returns {{
 *   supported: boolean,     // SpeechRecognition available in this UA
 *   permitted: boolean|null,// null = unknown, false = denied
 *   listening: boolean,     // mic actually recognising right now
 *   isArmed:   boolean,     // user has opted in via arm()
 *   error:     string|null,
 *   arm:       () => void,
 *   disarm:    () => void,
 *   toggle:    () => void,
 * }}
 */
export default function useWebWakeWord(opts) {
  const { onPhraseDetected } = opts || {};
  const [supported, setSupported] = React.useState(false);
  const [permitted, setPermitted] = React.useState(null);
  const [listening, setListening] = React.useState(false);
  const [isArmed,   setIsArmed]   = React.useState(false);
  const [error,     setError]     = React.useState(null);

  const recognitionRef = React.useRef(null);
  const cooldownUntilRef = React.useRef(0);
  const shouldRunRef = React.useRef(false);
  const onDetectedRef = React.useRef(onPhraseDetected || null);
  React.useEffect(() => { onDetectedRef.current = onPhraseDetected || null;
    }, [onPhraseDetected]);

  // One-shot: detect whether the UA supports SpeechRecognition.
  // Does NOT start anything — the ARM gate drives all mic activity.
  React.useEffect(() => {
    setSupported(Boolean(_getRecognitionCtor()));
  }, []);

  const _start = React.useCallback(() => {
    const Ctor = _getRecognitionCtor();
    if (!Ctor) return;
    if (recognitionRef.current) return;  // idempotent
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
          } catch (_e) { /* best-effort */ }
          try {
            if (typeof onDetectedRef.current === "function") {
              onDetectedRef.current();
            }
          } catch (_e) { /* swallow — caller errors must not kill mic */ }
        }
      };
      rec.onerror = (ev) => {
        const kind = ev?.error || "unknown";
        if (kind === "not-allowed" || kind === "service-not-allowed") {
          setPermitted(false);
          setError("mic-permission-denied");
          shouldRunRef.current = false;
          setIsArmed(false);
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
        recognitionRef.current = null;
        if (shouldRunRef.current) {
          // 300 ms stagger — avoids a tight restart loop if the
          // recogniser dies immediately on start.
          setTimeout(() => {
            if (shouldRunRef.current) _start();
          }, 300);
        }
      };
      recognitionRef.current = rec;
      shouldRunRef.current = true;
      rec.start();
      setListening(true);
      setPermitted(true);
      setError(null);
    } catch (e) {
      setError(String(e?.message || e || "start-failed"));
    }
  }, []);

  const _stop = React.useCallback(() => {
    shouldRunRef.current = false;
    const rec = recognitionRef.current;
    if (rec) {
      try { rec.onresult = null; rec.onerror = null; rec.onend = null; }
      catch (_e) { /* noop */ }
      try { rec.stop(); } catch (_e) { /* noop */ }
    }
    recognitionRef.current = null;
    setListening(false);
  }, []);

  const arm = React.useCallback(() => {
    setIsArmed(true);
    _start();
  }, [_start]);

  const disarm = React.useCallback(() => {
    setIsArmed(false);
    _stop();
  }, [_stop]);

  const toggle = React.useCallback(() => {
    // Read fresh via setState callback so a double-click doesn't
    // race the arm/disarm pair.
    setIsArmed((prev) => {
      if (prev) { _stop(); return false; }
      _start();          return true;
    });
  }, [_start, _stop]);

  // Unmount cleanup — if the component owning the hook is torn
  // down (route change inside the SPA shouldn't trigger this
  // because the provider lives at AppLayout), release the mic.
  React.useEffect(() => () => { _stop(); }, [_stop]);

  return {
    supported, listening, permitted, isArmed, error,
    arm, disarm, toggle,
  };
}
