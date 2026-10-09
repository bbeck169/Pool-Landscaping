/**
 * Phase 8M · Marco wake-word mic context (dependency-free).
 *
 * Lives in its own module so header surfaces (widgets.tsx → Header)
 * can read the armed state without importing expo-audio / the
 * wake-word hook.  The provider that fills it lives in
 * ``MarcoMicController.tsx``.
 */
import React from "react";

export const MARCO_WAKE_ROLES = new Set(["admin", "super_admin", "manager", "owner"]);

export const IDLE_AUTO_DISARM_MS = 10 * 60 * 1000; // 10 minutes

export type MarcoMicValue = {
  canUseMarco: boolean;
  supported: boolean;
  permitted: boolean | null;
  isArmed: boolean;
  listening: boolean;
  arm: () => void;
  disarm: () => void;
  toggle: () => void;
};

export const EMPTY_MARCO_MIC: MarcoMicValue = Object.freeze({
  canUseMarco: false,
  supported: false,
  permitted: null,
  isArmed: false,
  listening: false,
  arm: () => {},
  disarm: () => {},
  toggle: () => {},
});

export const MarcoMicContext = React.createContext<MarcoMicValue>(EMPTY_MARCO_MIC);

export function useMarcoMic(): MarcoMicValue {
  return React.useContext(MarcoMicContext);
}
