/**
 * Phase 8M · Marco wake-word mic controller (mobile parity with
 * frontend/src/components/marco/MarcoMicController.jsx).
 *
 * Hosts ``useMarcoWakeWord`` once at the root and exposes
 * arm / disarm / toggle via ``MarcoMicContext`` so <MicToggleButton>
 * can sit in the global <Header> without prop drilling.
 *
 *   * Role gate: admin / super_admin / manager / owner (same set as web).
 *   * 10-min idle auto-disarm — reset on arm() and every detection.
 *   * AppState: background / inactive → disarm (mobile analogue of
 *     web's beforeunload).  Armed state is never persisted.
 *   * Toasts on every transition.  Zero audible feedback.
 */
import React, { useCallback, useEffect, useMemo, useRef } from "react";
import { AppState, type AppStateStatus } from "react-native";

import { useAuth } from "@/src/auth";
import { useToast } from "@/src/components/ToastProvider";
import { aiDockEvents } from "@/src/events/aiDockEvents";
import { useMarcoWakeWord } from "@/src/hooks/useMarcoWakeWord";
import {
  EMPTY_MARCO_MIC,
  IDLE_AUTO_DISARM_MS,
  MARCO_WAKE_ROLES,
  MarcoMicContext,
} from "@/src/components/marco/marcoMicContext";

export { MicToggleButton } from "@/src/components/marco/MicToggleButton";
export { useMarcoMic, MARCO_WAKE_ROLES, IDLE_AUTO_DISARM_MS } from "@/src/components/marco/marcoMicContext";

type DisarmReason = "user" | "idle" | "background" | "silent";

const _openDock = () => aiDockEvents.emitOpen();

export function MarcoMicProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const { showToast } = useToast();
  const role = String((user as any)?.role || "").toLowerCase();
  const canUseMarco = MARCO_WAKE_ROLES.has(role);

  const idleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reasonRef = useRef<DisarmReason>("user");
  const disarmRef = useRef<() => void>(() => {});

  const clearIdle = useCallback(() => {
    if (idleTimerRef.current) clearTimeout(idleTimerRef.current);
    idleTimerRef.current = null;
  }, []);

  const scheduleIdle = useCallback(() => {
    clearIdle();
    idleTimerRef.current = setTimeout(() => {
      reasonRef.current = "idle";
      disarmRef.current();
    }, IDLE_AUTO_DISARM_MS);
  }, [clearIdle]);

  const wake = useMarcoWakeWord(_openDock, { onPhraseDetected: scheduleIdle });
  useEffect(() => { disarmRef.current = wake.disarm; }, [wake.disarm]);

  // Transition toasts + idle timer lifecycle.
  const prevArmedRef = useRef(false);
  useEffect(() => {
    if (prevArmedRef.current === wake.isArmed) return;
    prevArmedRef.current = wake.isArmed;
    if (wake.isArmed) {
      reasonRef.current = "user";
      scheduleIdle();
      showToast("Marco wake-word armed", "success");
      return;
    }
    clearIdle();
    const reason = reasonRef.current;
    reasonRef.current = "user";
    if (reason === "silent") return;
    if (reason === "idle") showToast("Marco wake-word auto-disarmed (10 min idle)", "info");
    else if (reason === "background") showToast("Marco wake-word disarmed (app in background)", "info");
    else showToast("Marco wake-word disarmed", "info");
  }, [wake.isArmed, scheduleIdle, clearIdle, showToast]);

  // Permission denied → one error toast.
  const prevPermittedRef = useRef<boolean | null>(null);
  useEffect(() => {
    if (prevPermittedRef.current === wake.permitted) return;
    prevPermittedRef.current = wake.permitted;
    if (wake.permitted === false) {
      showToast("Marco needs microphone access. Check your device settings.", "error");
    }
  }, [wake.permitted, showToast]);

  // App backgrounded / inactive → release the mic.
  const armedRef = useRef(false);
  armedRef.current = wake.isArmed;
  useEffect(() => {
    const sub = AppState.addEventListener("change", (next: AppStateStatus) => {
      if (next !== "active" && armedRef.current) {
        reasonRef.current = "background";
        disarmRef.current();
      }
    });
    return () => sub.remove();
  }, []);

  // Role lost (logout / role switch) → silent disarm.
  useEffect(() => {
    if (!canUseMarco && armedRef.current) {
      reasonRef.current = "silent";
      disarmRef.current();
    }
  }, [canUseMarco]);

  useEffect(() => () => clearIdle(), [clearIdle]);

  const value = useMemo(() => {
    if (!canUseMarco) return EMPTY_MARCO_MIC;
    return {
      canUseMarco,
      supported: wake.supported,
      permitted: wake.permitted,
      isArmed: wake.isArmed,
      listening: wake.listening,
      arm: wake.arm,
      disarm: wake.disarm,
      toggle: wake.toggle,
    };
  }, [canUseMarco, wake.supported, wake.permitted, wake.isArmed,
      wake.listening, wake.arm, wake.disarm, wake.toggle]);

  return <MarcoMicContext.Provider value={value}>{children}</MarcoMicContext.Provider>;
}

export default MarcoMicProvider;
