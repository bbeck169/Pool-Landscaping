// Feb-2026 · Phase 8 — Marco wake-word mic controller.
//
// Owns the ``useWebWakeWord`` hook state at the AppLayout level and
// exposes an arm / disarm / toggle API via React Context so the
// mic button can be mounted anywhere in the header (AdminTopBar,
// mobile <header>, etc.) without prop drilling.
//
// Responsibilities:
//   * Host the hook (one instance per AppLayout mount).
//   * Role gate the controller — non-Marco roles get the empty
//     sentinel context value and <MicToggleButton> renders nothing.
//   * 10-min idle auto-disarm.  "Idle" means no wake-word detections;
//     the hook calls ``onPhraseDetected`` which resets the timer.
//   * ``beforeunload`` disarm so a hard reload / tab close never
//     leaves a phantom-armed state in a sessionStorage cache
//     (we deliberately do NOT persist armed state across reloads).
//   * Toast on every state transition via sonner (already in deps):
//       - arm      → "Marco wake-word armed"
//       - disarm   → "Marco wake-word disarmed"
//       - auto-off → "Marco wake-word auto-disarmed (10 min idle)"
//
// Explicitly NOT doing:
//   * No new Audio / AudioContext / Oscillator.  Zero audible
//     feedback on arm / disarm / detect.
//   * No touch on voice dictation (``marcoMic`` card) or Marco
//     TTS output.
//   * No widening of the role gate — same set as the pre-Phase-8
//     ``MarcoWakeMount`` + the ``AIDock`` ``_AI_DOCK_ROLES``.
import React from "react";
import { toast } from "sonner";
import { Mic, MicOff } from "lucide-react";
import useWebWakeWord from "@/hooks/useWebWakeWord";


export const MARCO_WAKE_ROLES = new Set(
  ["admin", "super_admin", "manager", "owner"],
);

export const IDLE_AUTO_DISARM_MS = 10 * 60 * 1000;   // 10 minutes


const _EMPTY = Object.freeze({
  canUseMarco: false,
  supported:   false,
  permitted:   null,
  isArmed:     false,
  listening:   false,
  arm:    () => {},
  disarm: () => {},
  toggle: () => {},
});


const MarcoMicContext = React.createContext(_EMPTY);


export function useMarcoMic() {
  return React.useContext(MarcoMicContext);
}


export function MarcoMicProvider({ user, children }) {
  const role = String(user?.role || "").toLowerCase();
  const canUseMarco = MARCO_WAKE_ROLES.has(role);

  // Idle-disarm timer ref — reset every arm() and every detected
  // wake phrase; cleared on disarm().
  const idleTimerRef = React.useRef(null);
  const didAutoDisarmRef = React.useRef(false);

  const _clearIdleTimer = React.useCallback(() => {
    if (idleTimerRef.current) {
      clearTimeout(idleTimerRef.current);
      idleTimerRef.current = null;
    }
  }, []);

  const _scheduleIdleTimer = React.useCallback(() => {
    _clearIdleTimer();
    didAutoDisarmRef.current = false;
    idleTimerRef.current = setTimeout(() => {
      didAutoDisarmRef.current = true;
      // Flip into disarm via the hook's ref — the actual toast
      // fires on the ``isArmed`` transition inside the effect
      // below so we don't double-fire from here.
      _autoDisarmRef.current && _autoDisarmRef.current();
    }, IDLE_AUTO_DISARM_MS);
  }, [_clearIdleTimer]);

  // ``onPhraseDetected`` fires inside the hook every time the
  // regex matches.  The handler needs access to the schedule fn
  // defined above, so we route through a ref to avoid re-mounting
  // the SpeechRecognition instance when the fn identity flips.
  const _onDetected = React.useCallback(() => {
    _scheduleIdleTimer();
  }, [_scheduleIdleTimer]);

  const wake = useWebWakeWord({ onPhraseDetected: _onDetected });

  // Ref the hook's disarm so the idle timer can call it without
  // being in the hook's dep chain.
  const _autoDisarmRef = React.useRef(null);
  React.useEffect(() => { _autoDisarmRef.current = wake.disarm;
    }, [wake.disarm]);

  // Transition handlers — fire toast when ``isArmed`` flips.
  const prevArmedRef = React.useRef(false);
  React.useEffect(() => {
    if (!canUseMarco) return;
    const prev = prevArmedRef.current;
    if (prev === wake.isArmed) return;
    prevArmedRef.current = wake.isArmed;
    if (wake.isArmed) {
      _scheduleIdleTimer();
      toast.success("Marco wake-word armed", { id: "marco-wake-arm" });
    } else {
      _clearIdleTimer();
      if (didAutoDisarmRef.current) {
        didAutoDisarmRef.current = false;
        toast.info(
          "Marco wake-word auto-disarmed (10 min idle)",
          { id: "marco-wake-auto" },
        );
      } else {
        toast.message("Marco wake-word disarmed", { id: "marco-wake-off" });
      }
    }
  }, [wake.isArmed, canUseMarco, _scheduleIdleTimer, _clearIdleTimer]);

  // Permission-denied: the hook flips ``permitted`` to false and
  // disarms itself; surface a toast once.
  const prevPermittedRef = React.useRef(null);
  React.useEffect(() => {
    if (!canUseMarco) return;
    if (prevPermittedRef.current === wake.permitted) return;
    prevPermittedRef.current = wake.permitted;
    if (wake.permitted === false) {
      toast.error(
        "Marco needs microphone access. Check your browser site settings.",
        { id: "marco-wake-perm" },
      );
    }
  }, [wake.permitted, canUseMarco]);

  // beforeunload — hard reload / tab close must release the mic +
  // flip armed off so a reopened session doesn't start armed via
  // some future persistence layer (defense-in-depth: we don't
  // persist today, but this makes the invariant explicit).
  React.useEffect(() => {
    if (!canUseMarco) return undefined;
    const handler = () => {
      try { wake.disarm(); } catch (_e) { /* best-effort on unload */ }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [canUseMarco, wake.disarm]);

  // Final cleanup — provider unmount clears the timer.
  React.useEffect(() => () => { _clearIdleTimer(); }, [_clearIdleTimer]);

  const value = React.useMemo(() => {
    if (!canUseMarco) return _EMPTY;
    return {
      canUseMarco,
      supported:  wake.supported,
      permitted:  wake.permitted,
      isArmed:    wake.isArmed,
      listening:  wake.listening,
      arm:        wake.arm,
      disarm:     wake.disarm,
      toggle:     wake.toggle,
    };
  }, [canUseMarco, wake.supported, wake.permitted, wake.isArmed,
      wake.listening, wake.arm, wake.disarm, wake.toggle]);

  return (
    <MarcoMicContext.Provider value={value}>
      {children}
    </MarcoMicContext.Provider>
  );
}


// ──────────────────────────────────────────────────────────────────
//  <MicToggleButton>
//
//  Reads the ambient MarcoMicProvider state and renders a header-
//  slot button.  Hides itself entirely for roles / browsers where
//  Marco wake isn't available (zero accidental widening of the
//  role gate).
// ──────────────────────────────────────────────────────────────────
export function MicToggleButton({ className = "" }) {
  const ctx = useMarcoMic();
  if (!ctx.canUseMarco) return null;
  // UA has no SpeechRecognition — hide the button entirely so the
  // user doesn't see a dead control.  (``useTypedWakePhrase`` still
  // runs; it's the Firefox / Safari fallback.)
  if (!ctx.supported) return null;

  const armed = Boolean(ctx.isArmed);
  const label = armed
    ? "Disarm Marco wake-word"
    : "Arm Marco wake-word";

  return (
    <button
      type="button"
      onClick={ctx.toggle}
      aria-label={label}
      aria-pressed={armed}
      title={label}
      data-testid="marco-mic-toggle-btn"
      data-armed={armed ? "true" : "false"}
      className={
        "relative inline-flex items-center justify-center " +
        "w-9 h-9 rounded-full transition-colors " +
        (armed
          ? "bg-emerald-50 text-emerald-600 hover:bg-emerald-100"
          : "text-slate-400 hover:text-slate-600 hover:bg-slate-100")
        + (className ? " " + className : "")
      }
    >
      {armed ? (
        <>
          <Mic size={18} aria-hidden="true"
                data-testid="marco-mic-icon-armed" />
          {/* Pulsing ring — pure CSS, no audio.  ``animate-ping``
              from tailwind + the muted-outline swatch makes the
              armed state unmistakable without any sound. */}
          <span
            aria-hidden="true"
            data-testid="marco-mic-pulse-ring"
            className="absolute inset-0 rounded-full bg-emerald-400 opacity-60 animate-ping"
          />
        </>
      ) : (
        <MicOff size={18} aria-hidden="true"
                data-testid="marco-mic-icon-disarmed" />
      )}
    </button>
  );
}


export default MicToggleButton;
