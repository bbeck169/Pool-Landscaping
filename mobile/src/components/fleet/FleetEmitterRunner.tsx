/**
 * TD-fleet-emitter-auth-wiring · provider-scoped host for the fleet emitter.
 *
 * `useFleetEmitter()` reads `useAuth()`. It used to be called directly in
 * `RootLayout` (app/_layout.tsx), the component that RENDERS <AuthProvider>,
 * so it only ever saw the context default `{}` → `user` undefined → the
 * emitter never started (since FLEET-B cedc6d5f8). Mounting this runner
 * INSIDE <AuthProvider> (same pattern as <PushTapRouter />) fixes that.
 * Renders nothing.
 *
 * TD-mobile-fleet-enrollment-pending-toast · when a ping is rejected with 403
 * (tech not in fleet_membership yet — e.g. before the BE backfill runs) the
 * emitter already stops (no retry loop) and the chip reads "Not in Fleet".
 * Additionally surface ONE toast per device so the tech knows to contact an
 * admin. Persisted so app restarts don't repeat it.
 */
import { useEffect } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";

import { useFleetEmitter } from "@/src/hooks/useFleetEmitter";
import { useToast } from "@/src/components/ToastProvider";
import { onStatusChange } from "@/src/services/fleet/locationEmitter";

export const ENROLLMENT_TOAST_KEY = "fleet_enrollment_pending_toast_shown";
export const ENROLLMENT_TOAST_COPY = "Enrollment pending — contact admin";

let _claimed = false; // synchronous guard: two quick 403s can't both toast

export default function FleetEmitterRunner() {
  useFleetEmitter();
  const { showToast } = useToast();

  useEffect(() => onStatusChange(async (status) => {
    if (status !== "not_in_fleet" || _claimed) return;
    _claimed = true;
    if (await AsyncStorage.getItem(ENROLLMENT_TOAST_KEY).catch(() => null)) return;
    await AsyncStorage.setItem(ENROLLMENT_TOAST_KEY, "1").catch(() => {});
    showToast(ENROLLMENT_TOAST_COPY, "info");
  }), [showToast]);

  return null;
}

/** Test-only: reset the in-memory guard. */
export function __resetEnrollmentToastGuard() { _claimed = false; }
